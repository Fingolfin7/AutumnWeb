"""Shared search semantics for pages that browse tracked work."""

import json
import re
from dataclasses import dataclass, field
from functools import cached_property

from django.db import connections
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.db.models.expressions import RawSQL

from core.models import SessionSubproject, Sessions, SubProjects


# Words too common to narrow a search: "figured it out" looks for "figured"
# and "out". A term made only of them keeps them all.
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it its me my "
    "of on or our so than that the their them then this to was we were "
    "with you your".split()
)
_TOKENS = re.compile(r'"([^"]*)"|(\S+)')
_EDGE_PUNCTUATION = ".,;:!?()[]{}'\u2018\u2019\u201c\u201d"


def search_words(term):
    """The pieces of ``term`` that must each appear: its words, or quoted phrases.

    Every unquoted word must appear somewhere (any order, any field);
    "a quoted phrase" must appear as written. Common words are dropped unless
    nothing else is left.
    """
    words, phrases = [], []
    for phrase, word in _TOKENS.findall(term or ""):
        if phrase.strip():
            phrases.append(phrase.strip())
            continue
        word = word.strip(_EDGE_PUNCTUATION + '"')
        if word:
            words.append(word)
    meaningful = [word for word in words if word.lower() not in STOPWORDS]
    if meaningful or phrases:
        words = meaningful
    pieces = []
    for piece in phrases + words:
        if piece.lower() not in {seen.lower() for seen in pieces}:
            pieces.append(piece)
    return pieces


def search_projects(projects, term):
    """Projects where every word of ``term`` (``search_words``) appears in the
    name, description, a child's name, or one of its session notes."""
    for word in search_words(term):
        matching_subprojects = SubProjects.objects.filter(
            parent_project_id=OuterRef("pk"),
            user_id=OuterRef("user_id"),
            name__icontains=word,
        )
        matching_notes = Sessions.objects.filter(
            project_id=OuterRef("pk"),
            user_id=OuterRef("user_id"),
            note__icontains=word,
        )
        projects = projects.filter(
            Q(name__icontains=word)
            | Q(description__icontains=word)
            | Exists(matching_subprojects)
            | Exists(matching_notes)
        )
    return projects


#: The one order for session lists: newest first, ties by id.
SESSION_ORDER = ("-end_time", "-id")

DIRECT = "direct"
RELATED = "related"


@dataclass
class SessionSearch:
    """One Sessions search, shared by the Sessions page and API v2 (and so MCP).

    ``direct`` is the keyword matches; ``related_ids`` the sessions that match
    the term by meaning but not by keyword, best first, every one above the
    similarity cutoff. Ranked order is the direct matches newest first, then
    the related ones best first, so an equivalent request lists the same
    sessions in the same order wherever it is made; each interface only
    chooses how much of it to show at a time.
    """

    sessions: QuerySet
    direct: QuerySet
    related_ids: list = field(default_factory=list)

    @cached_property
    def direct_total(self):
        return self.direct.count()

    @property
    def total(self):
        return self.direct_total + len(self.related_ids)

    def combined(self):
        """Direct and related matches as one queryset, in no particular order."""
        return with_extra(self.sessions, self.direct, self.related_ids)

    def related_sessions(self, ids):
        """The sessions of ``ids`` (some of ``related_ids``), in that order."""
        found = {session.pk: session for session in self.sessions.filter(pk__in=list(ids))}
        return [found[pk] for pk in ids if pk in found]

    def page(self, offset, limit):
        """[(session, DIRECT|RELATED)] for ``offset``..``offset + limit`` of the ranked order."""
        rows = []
        if offset < self.direct_total:
            direct = self.direct.order_by(*SESSION_ORDER)[offset : offset + limit]
            rows.extend((session, DIRECT) for session in direct)
        start = max(offset - self.direct_total, 0)
        wanted = self.related_ids[start : start + limit - len(rows)]
        rows.extend((session, RELATED) for session in self.related_sessions(wanted))
        return rows


def keyword_sessions(sessions, term):
    """Sessions where every word of ``term`` (``search_words``) appears in the
    project's name, an assigned subproject's name, or the session's note."""
    for word in search_words(term):
        matching_subprojects = SessionSubproject.objects.filter(
            session_id=OuterRef("pk"),
            subproject__user_id=OuterRef("user_id"),
            subproject__name__icontains=word,
        )
        sessions = sessions.filter(
            Q(project__name__icontains=word)
            | Exists(matching_subprojects)
            | Q(note__icontains=word)
        )
    return sessions


def rank_sessions(sessions, term, *, user=None, related=False, cutoff=None, outcome=None):
    """The SessionSearch of ``term`` within ``sessions``.

    With ``related`` (and the ``user`` whose OpenAI key pays for the query),
    every session that matches the term by meaning is added after the keyword
    matches; see core.services.semantic_search. ``sessions`` must already
    carry every other filter, because related matches are drawn from it.
    ``cutoff`` overrides the account's similarity cutoff. ``outcome`` (a
    RelatedOutcome) records whether they could be added.
    """
    term = (term or "").strip()
    direct = keyword_sessions(sessions, term)
    related_ids = []
    if term and related:
        if user is None:
            if outcome is not None:
                outcome.requested = True
        else:
            from core.services.semantic_search import related_session_ids

            # Counted, not previewed: every match above the cutoff, no cap.
            related_ids = related_session_ids(
                user, sessions, direct, term, limit=None, cutoff=cutoff, outcome=outcome
            )
    return SessionSearch(sessions=sessions, direct=direct, related_ids=related_ids)


def search_sessions(sessions, term, *, user=None, related=False, cutoff=None, outcome=None):
    """``rank_sessions`` as one unordered queryset, for totals and charts."""
    if not (term or "").strip():
        return sessions
    return rank_sessions(
        sessions, term, user=user, related=related, cutoff=cutoff, outcome=outcome
    ).combined()


def with_extra(queryset, matches, extra_ids):
    """``matches`` plus the rows of ``queryset`` whose ids are ``extra_ids``."""
    if not extra_ids:
        return matches
    return queryset.filter(
        Q(pk__in=matches.order_by().values("pk"))
        | Q(pk__in=id_set(extra_ids, using=queryset.db))
    )


def id_set(ids, *, using="default"):
    """Any number of ids as ONE query parameter, for ``pk__in``.

    Counted related matches are uncapped, and a plain ``pk__in=[...]`` binds
    one variable per id: SQLite rejects a statement past 32,766 of them (999
    on older builds). A JSON array (SQLite) or an array (PostgreSQL) is one.
    """
    ids = [int(pk) for pk in ids]
    vendor = connections[using].vendor
    if vendor == "postgresql":
        return RawSQL("SELECT unnest(%s::bigint[])", [ids])
    if vendor == "sqlite":
        return RawSQL("SELECT value FROM json_each(%s)", [json.dumps(ids)])
    return ids


def is_truthy(value):
    """Checkbox and query-string booleans: on/true/1/yes."""
    return str(value or "").strip().lower() in {"on", "true", "1", "yes"}
