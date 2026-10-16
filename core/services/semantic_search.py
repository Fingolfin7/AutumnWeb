"""Meaning-based retrieval for Sessions and Projects search.

Vectors are written in the background shortly after edits
(``core.services.embedding_sync``) and by ``manage.py embed_sessions``; a
search embeds just the query. Every path degrades to ordinary keyword search:
AI features off, no OpenAI key, no vectors yet, or any provider failure yields
no related results and never an error.

A long note is also embedded in sentence passages (SessionPassageEmbedding),
and a session scores the better of its whole vector and its best passage, so
one relevant sentence in a long log can still rank it.

Staleness is derived, not flagged: each vector stores a digest of the exact
text it was built from, so a note edit or a project/subproject rename makes it
stale whichever write path caused it (forms, API, import, merges, bulk
updates). Stale vectors are re-embedded by the next sync and are never used.
"""
from dataclasses import dataclass, field
import hashlib
import logging
import math
import re

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models.functions import Substr

from core.models import (
    ProjectEmbedding,
    Projects,
    RecommendationUsage,
    SessionEmbedding,
    SessionPassageEmbedding,
    SessionSubproject,
    Sessions,
    SubProjects,
)
from core.services.embedding_sync import request_sync
from core.services.recommendation_usage import capture_usage, collect_attempts, provider_attempt

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
DIMENSIONS = 512
VECTOR_BYTES = DIMENSIONS * 4
# Well under the model's 8,191-token input limit, whatever the script.
MAX_INPUT_CHARS = 2000
# Long notes are also embedded in passages of about this many characters
# (whole sentences, each passage repeating the previous one's last sentence),
# so a sentence that answers a search isn't outweighed by the rest of a long
# log. Notes that fit in one passage only have their whole vector.
PASSAGE_CHARS = 240
# Passages read this much of a note: more than the whole vector's
# MAX_INPUT_CHARS, so the tail of a long note is searchable too.
MAX_PASSAGE_NOTE_CHARS = 20000
# Part of every passage digest: changing how notes are split re-embeds them.
PASSAGE_SCHEME = "sentences-240-overlap-1"
MAX_QUERY_CHARS = 500
QUERY_TIMEOUT_SECONDS = 4.0
SYNC_TIMEOUT_SECONDS = 60.0
QUERY_CACHE_SECONDS = 15 * 60
# After a failed query embedding, that account skips semantic search for this
# long instead of waiting out the timeout on every search.
FAILURE_COOLDOWN_SECONDS = 5 * 60
# Best F0.5 in scripts/semantic_search_eval.py (fictional corpus) with nothing
# shown for the no-match query; override with SEMANTIC_SEARCH_MIN_SIMILARITY.
DEFAULT_MIN_SIMILARITY = 0.45
CANDIDATE_LIMIT = 50
# The "Related" sections show this many at a time and page through the rest
# (?related_page= on Sessions and Projects). Sessions search (core.search.rank_sessions) and counted related
# matches (Charts/Insights "Include related", the API's related=true) pass
# limit=None: every match above the cutoff is kept, so nothing is silently
# truncated. The cutoff is the only relevance control.
RELATED_LIMIT = 5
RRF_K = 60
# Session vectors are scored this many rows at a time, so a search's memory
# stays flat however many passages an account's long notes produce.
SCORE_BATCH_ROWS = 4000


# The range a search's own cutoff (?similarity=, the Related slider) or a
# profile default may take. Below the floor nearly everything is "related";
# above the ceiling almost nothing is. Steps are what the slider moves by.
SIMILARITY_FLOOR = 0.25
SIMILARITY_CEILING = 0.60
SIMILARITY_STEP = 0.01
# Named stops on the slider, loosest first.
SIMILARITY_MARKS = (("Loose", 0.30), ("Moderate", 0.45), ("Strict", 0.55))


def server_min_similarity():
    return float(getattr(settings, "SEMANTIC_SEARCH_MIN_SIMILARITY", DEFAULT_MIN_SIMILARITY))


def min_similarity(user=None):
    """The cutoff a search uses unless it names its own: the account's, else the server's."""
    profile = getattr(user, "profile", None)
    value = getattr(profile, "related_similarity", None)
    return float(value) if value is not None else server_min_similarity()


def parse_similarity(value):
    """A requested cutoff as a float on the slider's grid, or None when absent.

    Raises ValueError for anything that is not a number between
    SIMILARITY_FLOOR and SIMILARITY_CEILING.
    """
    if value is None or str(value).strip() == "":
        return None
    number = float(str(value).strip())
    if not SIMILARITY_FLOOR <= number <= SIMILARITY_CEILING:
        raise ValueError("similarity out of range")
    return round(number, 2)


def loosen_similarity(best, cutoff):
    """The slider step that includes ``best``, only when ``cutoff`` excludes it."""
    if best is None or best >= cutoff:
        return None
    return max(SIMILARITY_FLOOR, math.floor(best * 100 + 1e-9) / 100)


def semantic_search_available(user):
    """Whether a search could use meaning at all; decides if the toggle shows."""
    profile = getattr(user, "profile", None)
    return bool(profile and profile.ai_features_enabled and profile.openai_api_key_enc)


# ---------------------------------------------------------------- evidence --

def _join(first, names, text):
    parts = [first or ""]
    names = ", ".join(sorted({name for name in names if name}))
    if names:
        parts.append(names)
    text = (text or "").strip()
    if text:
        parts.append(text)
    return "\n".join(parts)[:MAX_INPUT_CHARS]


def session_text(project_name, subproject_names, note):
    """The evidence keyword search reads, in one bounded string."""
    return _join(project_name, subproject_names, note)


def project_text(name, subproject_names, description):
    return _join(name, subproject_names, description)


def text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def session_sources(sessions, *, note_chars=MAX_INPUT_CHARS):
    """Map session id -> (project name, subproject names, note[:note_chars])."""
    rows = sessions.order_by().values_list("pk", "project__name", Substr("note", 1, note_chars))
    subprojects = {}
    links = SessionSubproject.objects.filter(session__in=sessions.order_by().values("pk"))
    for session_id, name in links.values_list("session_id", "subproject__name"):
        subprojects.setdefault(session_id, []).append(name)
    return {
        pk: (project_name, subprojects.get(pk, ()), note or "")
        for pk, project_name, note in rows
    }


def session_texts(sessions):
    """Map session id -> embedding text for a queryset of sessions."""
    return {
        pk: session_text(project_name, names, note)
        for pk, (project_name, names, note) in session_sources(sessions).items()
    }


_SENTENCE_BREAK = re.compile(r"(?<=[.!?\u2026])\s+|\s*\n+\s*")


def _sentences(note):
    """The note's sentences, any longer than a passage cut at word breaks."""
    pieces = []
    for sentence in _SENTENCE_BREAK.split(note.strip()):
        sentence = sentence.strip()
        while len(sentence) > PASSAGE_CHARS:
            cut = sentence.rfind(" ", 0, PASSAGE_CHARS + 1)
            if cut <= 0:
                cut = PASSAGE_CHARS
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    return pieces


def split_passages(note):
    """A long note's passages, or [] when it fits in one.

    Whole sentences are grouped up to PASSAGE_CHARS; each passage after the
    first starts with the previous one's last sentence, so a thought that
    spans a boundary is still read together somewhere.
    """
    sentences = _sentences((note or "")[:MAX_PASSAGE_NOTE_CHARS])
    passages, start = [], 0
    while start < len(sentences):
        end, length = start + 1, len(sentences[start])
        while end < len(sentences) and length + 1 + len(sentences[end]) <= PASSAGE_CHARS:
            length += 1 + len(sentences[end])
            end += 1
        passages.append(" ".join(sentences[start:end]))
        if end == len(sentences):
            break
        start = end - 1 if end - start > 1 else end
    return passages if len(passages) > 1 else []


def passage_digest(project_name, subproject_names, note):
    """The digest every passage of a session carries; changes with any part of it."""
    names = ", ".join(sorted({name for name in subproject_names if name}))
    source = "\n".join([PASSAGE_SCHEME, project_name or "", names, note or ""])
    return text_digest(source)


def passage_sources(sessions):
    """Map session id -> (digest, [passage texts]) for those with long notes."""
    found = {}
    for pk, (project_name, names, note) in session_sources(
        sessions, note_chars=MAX_PASSAGE_NOTE_CHARS
    ).items():
        passages = split_passages(note)
        if passages:
            found[pk] = (
                passage_digest(project_name, names, note),
                [session_text(project_name, names, passage) for passage in passages],
            )
    return found


def project_texts(projects):
    """Map project id -> embedding text for a queryset of projects."""
    rows = projects.order_by().values_list("pk", "name", Substr("description", 1, MAX_INPUT_CHARS))
    subprojects = {}
    children = SubProjects.objects.filter(parent_project__in=projects.order_by().values("pk"))
    for project_id, name in children.values_list("parent_project_id", "name"):
        subprojects.setdefault(project_id, []).append(name)
    return {
        pk: project_text(name, subprojects.get(pk, ()), description)
        for pk, name, description in rows
    }


# ----------------------------------------------------------------- vectors --

def _numpy():
    # Imported lazily so web workers that never run a semantic search don't
    # pay for it in memory.
    import numpy
    return numpy


def encode_vector(values):
    np = _numpy()
    vector = np.asarray(values, dtype="<f4")
    if vector.shape != (DIMENSIONS,):
        raise ValueError("unexpected embedding size")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("unusable embedding")
    return (vector / norm).astype("<f4").tobytes()


def decode_vector(data):
    # PostgreSQL returns memoryview for BinaryField; SQLite returns bytes.
    return _numpy().frombuffer(bytes(data), dtype="<f4")


# ---------------------------------------------------------------- provider --

class Embedder:
    """One OpenAI client with explicit timeout/retry settings."""

    def __init__(self, api_key, *, timeout, max_retries=0):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)

    def embed(self, texts):
        texts = list(texts)
        with provider_attempt("openai", MODEL):
            response = self.client.embeddings.create(model=MODEL, input=texts, dimensions=DIMENSIONS)
            capture_usage(getattr(response, "usage", None))
        data = sorted(response.data, key=lambda item: item.index)
        if len(data) != len(texts):
            raise ValueError("embedding count mismatch")
        return [item.embedding for item in data]


def embedder_for(user, *, timeout=QUERY_TIMEOUT_SECONDS, max_retries=0):
    """The user's own OpenAI key, only while AI features are on for them."""
    profile = getattr(user, "profile", None)
    if profile is None or not profile.ai_features_enabled:
        return None
    api_key = profile.get_api_key("openai")
    if not api_key:
        return None
    return Embedder(api_key, timeout=timeout, max_retries=max_retries)


def _record_usage(user, attempts):
    if attempts:
        RecommendationUsage.objects.bulk_create(
            [RecommendationUsage(user=user, **attempt) for attempt in attempts]
        )


# -------------------------------------------------------------------- sync --

@dataclass
class SyncResult:
    total: int = 0
    fresh: int = 0
    pending: int = 0
    embedded: int = 0
    pending_chars: int = 0


@dataclass
class SyncReport:
    sessions: SyncResult = field(default_factory=SyncResult)
    projects: SyncResult = field(default_factory=SyncResult)
    # Counted in sessions with long notes; pending_chars covers every passage.
    passages: SyncResult = field(default_factory=SyncResult)


def sync_embeddings(user, embedder, *, batch_size=100, limit=None, dry_run=False):
    """Embed the user's completed sessions and projects whose vector is missing or stale.

    Idempotent: unchanged records are skipped by digest. Newest records go
    first so a ``limit``-bounded run (per kind) covers recent work. Each batch
    commits on its own, so a failure keeps earlier progress and the next run
    resumes.
    """
    completed = Sessions.objects.filter(user=user, end_time__isnull=False)
    sessions = _sync(
        user,
        embedder,
        texts=session_texts(completed),
        stored=SessionEmbedding.objects.filter(session__user=user).values_list(
            "session_id", "model", "text_digest"
        ),
        write=_write_sessions,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
    )
    projects = _sync(
        user,
        embedder,
        texts=project_texts(Projects.objects.filter(user=user)),
        stored=ProjectEmbedding.objects.filter(project__user=user).values_list(
            "project_id", "model", "text_digest"
        ),
        write=_write_projects,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
    )
    passages = _sync_passages(
        user, embedder, completed, batch_size=batch_size, limit=limit, dry_run=dry_run
    )
    return SyncReport(sessions=sessions, projects=projects, passages=passages)


def _sync(user, embedder, *, texts, stored, write, batch_size, limit, dry_run):
    stored = {pk: (model, digest) for pk, model, digest in stored}
    todo = []
    for pk in sorted(texts, reverse=True):
        digest = text_digest(texts[pk])
        if stored.get(pk) != (MODEL, digest):
            todo.append((pk, texts[pk], digest))
    result = SyncResult(total=len(texts), fresh=len(texts) - len(todo))
    if limit is not None:
        todo = todo[:limit]
    result.pending = len(todo)
    result.pending_chars = sum(len(text) for _, text, _ in todo)
    if dry_run:
        return result

    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        with collect_attempts() as attempts:
            try:
                vectors = embedder.embed([text for _, text, _ in batch])
            finally:
                _record_usage(user, attempts)
        rows = [(pk, digest, encode_vector(vector)) for (pk, _, digest), vector in zip(batch, vectors)]
        result.embedded += write(user, rows)
    return result


def _sync_passages(user, embedder, sessions, *, batch_size, limit, dry_run):
    """Replace the passages of every long note whose passages are missing or stale."""
    sources = passage_sources(sessions)
    stored = {}
    for pk, model, digest in (
        SessionPassageEmbedding.objects.filter(session__user=user)
        .values_list("session_id", "model", "text_digest")
        .distinct()
    ):
        # Two digests for one session can't both be current: re-embed it.
        stored[pk] = None if pk in stored else (model, digest)
    todo = [
        (pk, *sources[pk])
        for pk in sorted(sources, reverse=True)
        if stored.get(pk) != (MODEL, sources[pk][0])
    ]
    result = SyncResult(total=len(sources), fresh=len(sources) - len(todo))
    if limit is not None:
        todo = todo[:limit]
    result.pending = len(todo)
    result.pending_chars = sum(len(text) for _, _, texts in todo for text in texts)
    if dry_run:
        return result

    # Notes that no longer split (shortened, emptied or no longer completed).
    obsolete = [pk for pk in stored if pk not in sources]
    for chunk in _chunks(obsolete, 500):
        SessionPassageEmbedding.objects.filter(session__user=user, session_id__in=chunk).delete()

    # Batches of whole sessions, about batch_size passages each.
    batch, size = [], 0
    for item in todo + [None]:
        if batch and (item is None or size + len(item[2]) > batch_size):
            with collect_attempts() as attempts:
                try:
                    vectors = embedder.embed([text for _, _, texts in batch for text in texts])
                finally:
                    _record_usage(user, attempts)
            vectors = iter(vectors)
            rows = [
                (pk, digest, [encode_vector(next(vectors)) for _ in texts])
                for pk, digest, texts in batch
            ]
            result.embedded += _write_passages(user, rows)
            batch, size = [], 0
        if item is not None:
            batch.append(item)
            size += len(item[2])
    return result


def _write_passages(user, rows):
    """Swap in each session's new passages at once; returns sessions written.

    The sessions are locked first, in id order, so two syncs replacing the
    same session's passages take turns instead of colliding. A session whose
    text changed while its batch was at the provider is left alone: the
    passages just embedded are already stale, and the next sync embeds the
    new text rather than this one overwriting a newer write.
    """
    wanted = {pk: (digest, vectors) for pk, digest, vectors in rows}
    try:
        with transaction.atomic():
            locked = list(
                Sessions.objects.select_for_update()
                .filter(pk__in=list(wanted), user=user)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            current = passage_sources(Sessions.objects.filter(pk__in=locked, end_time__isnull=False))
            write = [pk for pk in locked if pk in current and current[pk][0] == wanted[pk][0]]
            SessionPassageEmbedding.objects.filter(session_id__in=write).delete()
            SessionPassageEmbedding.objects.bulk_create(
                [
                    SessionPassageEmbedding(
                        session_id=pk, position=position, model=MODEL, text_digest=wanted[pk][0], vector=vector
                    )
                    for pk in write
                    for position, vector in enumerate(wanted[pk][1])
                ]
            )
    except IntegrityError:
        logger.warning("semantic_sync_batch_skipped user_id=%s rows=%s", user.pk, len(rows))
        return 0
    return len(write)


def _write_sessions(user, rows):
    live = set(
        Sessions.objects.filter(pk__in=[pk for pk, _, _ in rows], user=user).values_list("pk", flat=True)
    )
    return _upsert(
        user,
        SessionEmbedding,
        "session",
        [
            SessionEmbedding(session_id=pk, model=MODEL, text_digest=digest, vector=vector)
            for pk, digest, vector in rows
            if pk in live
        ],
    )


def _write_projects(user, rows):
    live = set(
        Projects.objects.filter(pk__in=[pk for pk, _, _ in rows], user=user).values_list("pk", flat=True)
    )
    return _upsert(
        user,
        ProjectEmbedding,
        "project",
        [
            ProjectEmbedding(project_id=pk, model=MODEL, text_digest=digest, vector=vector)
            for pk, digest, vector in rows
            if pk in live
        ],
    )


def _upsert(user, model, unique_field, rows):
    # Records deleted while the batch was at the provider are dropped by the
    # callers; one whose text changed meanwhile carries the old digest and
    # stays stale.
    try:
        with transaction.atomic():
            model.objects.bulk_create(
                rows,
                update_conflicts=True,
                unique_fields=[unique_field],
                update_fields=["model", "text_digest", "vector", "updated_at"],
            )
    except IntegrityError:
        logger.warning("semantic_sync_batch_skipped user_id=%s rows=%s", user.pk, len(rows))
        return 0
    return len(rows)


# ------------------------------------------------------------------ search --

def reciprocal_rank_fusion(rankings, k=RRF_K):
    """Fuse ranked id lists; ties keep first-seen order (keyword list first)."""
    scores, first_seen = {}, {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(item, len(first_seen))
    return sorted(scores, key=lambda item: (-scores[item], first_seen[item]))


def _stack(rows):
    """(rows without their vector, matrix) for the rows whose last column is a usable vector."""
    kept, chunks = [], []
    for row in rows:
        data = bytes(row[-1])
        if len(data) != VECTOR_BYTES:
            continue
        kept.append(row[:-1])
        chunks.append(data)
    if not kept:
        return [], None
    np = _numpy()
    matrix = np.frombuffer(b"".join(chunks), dtype="<f4").reshape(len(kept), DIMENSIONS)
    # Stored vectors are unit length; anything else (NaN, inf, zero, a
    # corrupted blob of the right size) would compare as "similar" or worse.
    with np.errstate(all="ignore"):
        usable = np.isfinite(matrix).all(axis=1) & (np.abs(np.linalg.norm(matrix, axis=1) - 1.0) < 1e-3)
    if not usable.all():
        kept = [row for row, ok in zip(kept, usable) if ok]
        matrix = matrix[usable]
        if not kept:
            return [], None
    return kept, matrix


def _matrix(rows):
    kept, matrix = _stack(rows)
    return [pk for pk, _ in kept], {pk: digest for pk, digest in kept}, matrix


def _session_vector_rows(user, sessions, *, passages=True):
    """[(kind, rows)]: the current-model vector rows of the user's ``sessions``."""
    scope = {"session__user": user, "model": MODEL, "session__in": sessions.order_by().values("pk")}
    kinds = [("whole", SessionEmbedding.objects.filter(**scope))]
    if passages:
        kinds.append(("passage", SessionPassageEmbedding.objects.filter(**scope)))
    return kinds


def has_session_vectors(user, sessions):
    """Whether any of ``sessions`` has a vector, before paying to embed a query."""
    return any(rows.exists() for _, rows in _session_vector_rows(user, sessions))


def _scored_rows(rows, query_vector, cutoff):
    """(session id, digest, similarity) at or above ``cutoff`` for vector ``rows``.

    Reads SCORE_BATCH_ROWS rows at a time by row id, so memory stays bounded.
    """
    np = _numpy()
    last = 0
    while True:
        batch = list(
            rows.filter(pk__gt=last)
            .order_by("pk")
            .values_list("pk", "session_id", "text_digest", "vector")[:SCORE_BATCH_ROWS]
        )
        if not batch:
            return
        last = batch[-1][0]
        kept, matrix = _stack(batch)
        if matrix is not None:
            with np.errstate(all="ignore"):
                scores = matrix @ query_vector
            for (_, session_id, digest), score in zip(kept, scores):
                score = float(score)
                if np.isfinite(score) and score >= cutoff:
                    yield session_id, digest, score
        if len(batch) < SCORE_BATCH_ROWS:
            return


def load_project_vectors(user, projects):
    """Current-model vectors for the user's projects within ``projects``."""
    return _matrix(
        ProjectEmbedding.objects.filter(
            project__user=user, model=MODEL, project__in=projects.order_by().values("pk")
        )
        .order_by("project_id")
        .values_list("project_id", "text_digest", "vector")
    )


def semantic_ranking(ids, matrix, query_vector, *, cutoff, limit=CANDIDATE_LIMIT):
    """[(id, cosine)] at or above ``cutoff``, best first; ``limit=None`` keeps all."""
    if matrix is None:
        return []
    np = _numpy()
    with np.errstate(all="ignore"):
        scores = matrix @ query_vector
    scores = np.where(np.isfinite(scores), scores, -np.inf)
    ranked = []
    for index in np.argsort(-scores, kind="stable"):
        score = float(scores[index])
        if not score >= cutoff or (limit is not None and len(ranked) >= limit):
            break
        ranked.append((ids[index], score))
    return ranked


def _query_cache_key(user, term):
    return "semantic-search:q:" + hashlib.sha256(
        f"{user.pk}\0{MODEL}\0{DIMENSIONS}\0{term}".encode("utf-8")
    ).hexdigest()


def query_vector(user, embedder, term):
    """Embed the query once per user and wording for a short while."""
    key = _query_cache_key(user, term)
    cached = cache.get(key)
    if cached is not None:
        return decode_vector(cached)
    with collect_attempts() as attempts:
        try:
            [vector] = embedder.embed([term])
        finally:
            _record_usage(user, attempts)
    data = encode_vector(vector)
    cache.set(key, data, QUERY_CACHE_SECONDS)
    return decode_vector(data)


def _cooldown_key(user):
    return f"semantic-search:cooldown:{user.pk}"


def _query_vector_or_none(user, term):
    """The query's vector, or None on any failure, including building the client.

    A failure starts a short per-account cooldown, so while a key is broken
    or the provider is down, searches don't each wait out the timeout again.
    """
    try:
        cached = cache.get(_query_cache_key(user, term))
        if cached is not None:
            return decode_vector(cached)
        if cache.get(_cooldown_key(user)):
            return None
        embedder = embedder_for(user)
        if embedder is None:
            return None
        return query_vector(user, embedder, term)
    except Exception as exc:
        logger.warning(
            "semantic_search_unavailable user_id=%s error_category=%s", user.pk, type(exc).__name__
        )
        cache.set(_cooldown_key(user), True, FAILURE_COOLDOWN_SECONDS)
        return None


def session_scores(user, sessions, query_vector, *, cutoff, passages=True):
    """{session id: best similarity at or above ``cutoff``} within ``sessions``.

    A session scores the better of its whole-note vector and its best passage
    (``passages=False``: whole notes only), counting only vectors whose
    digest still matches the session's current text.
    """
    hits = {}
    for kind, rows in _session_vector_rows(user, sessions, passages=passages):
        for pk, digest, score in _scored_rows(rows, query_vector, cutoff):
            best = hits.setdefault(pk, {})
            best[kind, digest] = max(best.get((kind, digest), score), score)
    scores = {}
    for chunk in _chunks(sorted(hits), 500):
        sources = session_sources(
            Sessions.objects.filter(pk__in=chunk, user=user, end_time__isnull=False),
            note_chars=MAX_PASSAGE_NOTE_CHARS,
        )
        for pk, (project_name, names, note) in sources.items():
            current = {
                "whole": text_digest(session_text(project_name, names, note[:MAX_INPUT_CHARS])),
                "passage": passage_digest(project_name, names, note),
            }
            fresh = [score for (kind, digest), score in hits[pk].items() if digest == current[kind]]
            if fresh:
                scores[pk] = max(fresh)
    return scores


def fresh_project_ids(user, ids, digests):
    """Those of ``ids`` whose vector still matches the project's current text."""
    texts = project_texts(Projects.objects.filter(pk__in=ids, user=user))
    return {pk for pk, text in texts.items() if digests.get(pk) == text_digest(text)}


def _chunks(ids, size):
    for start in range(0, len(ids), size):
        yield ids[start:start + size]


def _select(candidates, keep, limit):
    """The best-first ``candidates`` that ``keep`` accepts, up to ``limit``.

    Works through the ranking in chunks, so rejected candidates (keyword
    matches) never use up a preview's slots, and each query's id list stays
    bounded.
    """
    chosen = []
    for chunk in _chunks(candidates, CANDIDATE_LIMIT if limit is not None else 500):
        accepted = keep(chunk)
        chosen.extend(pk for pk in chunk if pk in accepted)
        if limit is not None and len(chosen) >= limit:
            return chosen[:limit]
    return chosen


def _clean_term(term):
    return (term or "").strip()[:MAX_QUERY_CHARS]


@dataclass
class RelatedOutcome:
    """Whether related matches that were asked for could actually be added.

    Pass one down to the search so the page or response can say when a total
    is keyword-only because meaning-based matching was unavailable (no key,
    AI off, nothing embedded yet, or the provider failing).
    """
    requested: bool = False
    included: bool = False
    # The cutoff the search applied, once it ran.
    cutoff: float = None
    # Pages with the Related slider set this to also learn the score of every
    # related match down to SIMILARITY_FLOOR (``scores``, best first), so the
    # slider can show how many a looser or stricter cutoff would give.
    collect_scores: bool = False
    scores: list = field(default_factory=list)

    @property
    def unavailable(self):
        return self.requested and not self.included

    @property
    def best(self):
        """The closest related match's score, if any reaches SIMILARITY_FLOOR."""
        return self.scores[0] if self.scores else None

    def counts(self):
        """How many related matches each slider step, floor to ceiling, keeps."""
        steps = round((SIMILARITY_CEILING - SIMILARITY_FLOOR) / SIMILARITY_STEP)
        counts = []
        for index in range(steps + 1):
            cutoff = round(SIMILARITY_FLOOR + index * SIMILARITY_STEP, 2)
            counts.append(sum(1 for score in self.scores if score >= cutoff))
        return counts


def related_session_ids(
    user, sessions, keyword_sessions, term, *, limit=RELATED_LIMIT, cutoff=None, outcome=None
):
    """Ids of sessions in ``sessions`` that mean ``term`` but keyword search missed.

    ``limit=None`` returns every one at or above the cutoff: ``cutoff``, else
    the account's default (``min_similarity``).

    ``sessions`` must already carry the caller's ownership and filters (dates,
    context, tags, project include/exclude); ``keyword_sessions`` is the same
    set narrowed by the keyword term. Best match first. With no keyword rank,
    their reciprocal-rank-fusion order is simply their similarity order.
    """
    term = _clean_term(term)
    if not term:
        return []
    if outcome is not None:
        outcome.requested = True
    if not semantic_search_available(user):
        return []
    # Catch up on writes no edit hook saw (e.g. a CLI import on the server).
    request_sync(user.pk, recheck=True)
    if not has_session_vectors(user, sessions):
        return []
    vector = _query_vector_or_none(user, term)
    if vector is None:
        return []
    cutoff = min_similarity(user) if cutoff is None else cutoff
    if outcome is not None:
        outcome.included = True
        outcome.cutoff = cutoff
    floor = _scoring_floor(cutoff, outcome)
    scores = session_scores(user, sessions, vector, cutoff=floor)
    ranked = sorted(scores, key=lambda pk: (-scores[pk], pk))

    def keep(chunk):
        keyword = set(keyword_sessions.filter(pk__in=chunk).values_list("pk", flat=True))
        return {pk for pk in chunk if pk not in keyword}

    return _cut(ranked, scores, keep, limit=limit, cutoff=cutoff, outcome=outcome)


def _scoring_floor(cutoff, outcome):
    """Score down to the slider's floor only when its counts were asked for."""
    if outcome is not None and outcome.collect_scores:
        return min(cutoff, SIMILARITY_FLOOR)
    return cutoff


def _cut(ranked, scores, keep, *, limit, cutoff, outcome):
    """The ``keep``-accepted ``ranked`` ids at or above ``cutoff``, up to ``limit``.

    When the slider asked to collect scores, every accepted score is recorded
    on ``outcome`` before applying its current cutoff.
    """
    if outcome is not None and outcome.collect_scores:
        related = _select(ranked, keep, None)
        outcome.scores = [scores[pk] for pk in related]
        kept = [pk for pk in related if scores[pk] >= cutoff]
        return kept if limit is None else kept[:limit]
    return _select(ranked, keep, limit)


def related_project_ids(
    user, projects, keyword_projects, term, *, limit=RELATED_LIMIT, cutoff=None, outcome=None
):
    """Ids of projects in ``projects`` that mean ``term`` but keyword search missed.

    A project scores the better of its own vector (name, subprojects,
    description) and its best-matching session, mirroring keyword search,
    which also matches projects through their session notes. ``limit=None``
    returns every one at or above the cutoff (``cutoff``, else the account's).
    """
    term = _clean_term(term)
    if not term:
        return []
    if outcome is not None:
        outcome.requested = True
    if not semantic_search_available(user):
        return []
    # Catch up on writes no edit hook saw (e.g. a CLI import on the server).
    request_sync(user.pk, recheck=True)
    project_ids, project_digests, project_matrix = load_project_vectors(user, projects)
    project_sessions = Sessions.objects.filter(
        user=user, end_time__isnull=False, project__in=projects.order_by().values("pk")
    )
    if not project_ids and not has_session_vectors(user, project_sessions):
        return []
    vector = _query_vector_or_none(user, term)
    if vector is None:
        return []
    cutoff = min_similarity(user) if cutoff is None else cutoff
    if outcome is not None:
        outcome.included = True
        outcome.cutoff = cutoff

    # Every fresh score is aggregated per project before anything is cut.
    floor = _scoring_floor(cutoff, outcome)
    scores = {}
    project_hits = dict(semantic_ranking(project_ids, project_matrix, vector, cutoff=floor, limit=None))
    for chunk in _chunks(list(project_hits), 500):
        for pk in fresh_project_ids(user, chunk, project_digests):
            scores[pk] = max(scores.get(pk, project_hits[pk]), project_hits[pk])
    session_hits = session_scores(user, project_sessions, vector, cutoff=floor)
    for chunk in _chunks(list(session_hits), 500):
        for session_id, project_id in Sessions.objects.filter(pk__in=chunk, user=user).values_list(
            "pk", "project_id"
        ):
            score = session_hits[session_id]
            scores[project_id] = max(scores.get(project_id, score), score)
    if not scores:
        return []

    ranked = sorted(scores, key=lambda pk: (-scores[pk], pk))

    def keep(chunk):
        keyword = set(keyword_projects.filter(pk__in=chunk).values_list("pk", flat=True))
        return {pk for pk in chunk if pk not in keyword}

    return _cut(ranked, scores, keep, limit=limit, cutoff=cutoff, outcome=outcome)
