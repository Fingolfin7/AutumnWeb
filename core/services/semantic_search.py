"""Meaning-based retrieval for Sessions and Projects search.

Vectors are written only by ``manage.py embed_sessions``; a search embeds just
the query. Every path degrades to ordinary keyword search: AI features off, no
OpenAI key, no vectors yet, or any provider failure yields no related results
and never an error.

Staleness is derived, not flagged: each vector stores a digest of the exact
text it was built from, so a note edit or a project/subproject rename makes it
stale whichever write path caused it (forms, API, import, merges, bulk
updates). Stale vectors are re-embedded by the next sync and are never used.
"""
from dataclasses import dataclass, field
import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models.functions import Substr

from core.models import (
    ProjectEmbedding,
    Projects,
    RecommendationUsage,
    SessionEmbedding,
    SessionSubproject,
    Sessions,
    SubProjects,
)
from core.services.recommendation_usage import capture_usage, collect_attempts, provider_attempt

logger = logging.getLogger(__name__)

MODEL = "text-embedding-3-small"
DIMENSIONS = 512
VECTOR_BYTES = DIMENSIONS * 4
# Well under the model's 8,191-token input limit, whatever the script.
MAX_INPUT_CHARS = 2000
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
# The "Related" sections preview this many. When related matches are counted
# instead (Charts/Insights "Include related", the API's related=true), callers
# pass limit=None: every match above the cutoff counts, so a total is never
# silently truncated. The cutoff is the only relevance control.
RELATED_LIMIT = 5
RRF_K = 60


def min_similarity():
    return float(getattr(settings, "SEMANTIC_SEARCH_MIN_SIMILARITY", DEFAULT_MIN_SIMILARITY))


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


def session_texts(sessions):
    """Map session id -> embedding text for a queryset of sessions."""
    rows = sessions.order_by().values_list("pk", "project__name", Substr("note", 1, MAX_INPUT_CHARS))
    subprojects = {}
    links = SessionSubproject.objects.filter(session__in=sessions.order_by().values("pk"))
    for session_id, name in links.values_list("session_id", "subproject__name"):
        subprojects.setdefault(session_id, []).append(name)
    return {
        pk: session_text(project_name, subprojects.get(pk, ()), note)
        for pk, project_name, note in rows
    }


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


def sync_embeddings(user, embedder, *, batch_size=100, limit=None, dry_run=False):
    """Embed the user's completed sessions and projects whose vector is missing or stale.

    Idempotent: unchanged records are skipped by digest. Newest records go
    first so a ``limit``-bounded run (per kind) covers recent work. Each batch
    commits on its own, so a failure keeps earlier progress and the next run
    resumes.
    """
    sessions = _sync(
        user,
        embedder,
        texts=session_texts(Sessions.objects.filter(user=user, end_time__isnull=False)),
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
    return SyncReport(sessions=sessions, projects=projects)


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
        logger.warning("semantic_sync_batch_skipped", extra={"user_id": user.pk, "rows": len(rows)})
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


def _matrix(rows):
    ids, digests, chunks = [], {}, []
    for pk, digest, data in rows:
        data = bytes(data)
        if len(data) != VECTOR_BYTES:
            continue
        ids.append(pk)
        digests[pk] = digest
        chunks.append(data)
    if not ids:
        return [], {}, None
    np = _numpy()
    matrix = np.frombuffer(b"".join(chunks), dtype="<f4").reshape(len(ids), DIMENSIONS)
    # Stored vectors are unit length; anything else (NaN, inf, zero, a
    # corrupted blob of the right size) would compare as "similar" or worse.
    with np.errstate(all="ignore"):
        usable = np.isfinite(matrix).all(axis=1) & (np.abs(np.linalg.norm(matrix, axis=1) - 1.0) < 1e-3)
    if not usable.all():
        ids = [pk for pk, ok in zip(ids, usable) if ok]
        digests = {pk: digests[pk] for pk in ids}
        matrix = matrix[usable]
        if not ids:
            return [], {}, None
    return ids, digests, matrix


def load_vectors(user, sessions):
    """Current-model vectors for the user's sessions within ``sessions``."""
    return _matrix(
        SessionEmbedding.objects.filter(
            session__user=user, model=MODEL, session__in=sessions.order_by().values("pk")
        )
        .order_by("session_id")
        .values_list("session_id", "text_digest", "vector")
    )


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
        logger.warning("semantic_search_unavailable", extra={"user_id": user.pk, "error_category": type(exc).__name__})
        cache.set(_cooldown_key(user), True, FAILURE_COOLDOWN_SECONDS)
        return None


def fresh_ids(user, ids, digests):
    """Those of ``ids`` whose vector still matches the session's current text."""
    texts = session_texts(Sessions.objects.filter(pk__in=ids, user=user, end_time__isnull=False))
    return {pk for pk, text in texts.items() if digests.get(pk) == text_digest(text)}


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
    matches, stale vectors) never use up a preview's slots, and each query's
    id list stays bounded.
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

    @property
    def unavailable(self):
        return self.requested and not self.included


def related_session_ids(user, sessions, keyword_sessions, term, *, limit=RELATED_LIMIT, outcome=None):
    """Ids of sessions in ``sessions`` that mean ``term`` but keyword search missed.

    ``limit=None`` returns every one above the cutoff.

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
    ids, digests, matrix = load_vectors(user, sessions)
    if not ids:
        return []
    vector = _query_vector_or_none(user, term)
    if vector is None:
        return []
    if outcome is not None:
        outcome.included = True
    candidates = [pk for pk, _ in semantic_ranking(ids, matrix, vector, cutoff=min_similarity(), limit=None)]

    def keep(chunk):
        keyword = set(keyword_sessions.filter(pk__in=chunk).values_list("pk", flat=True))
        return fresh_ids(user, [pk for pk in chunk if pk not in keyword], digests)

    return _select(candidates, keep, limit)


def find_related_sessions(user, sessions, keyword_sessions, term, *, limit=RELATED_LIMIT):
    """The sessions of ``related_session_ids``, ready to render."""
    related = related_session_ids(user, sessions, keyword_sessions, term, limit=limit)
    if not related:
        return []
    found = {
        session.pk: session
        for session in Sessions.objects.filter(pk__in=related, user=user)
        .select_related("project")
        .prefetch_related("subprojects")
    }
    return [found[pk] for pk in related if pk in found]


def related_project_ids(user, projects, keyword_projects, term, *, limit=RELATED_LIMIT, outcome=None):
    """Ids of projects in ``projects`` that mean ``term`` but keyword search missed.

    A project scores the better of its own vector (name, subprojects,
    description) and its best-matching session, mirroring keyword search,
    which also matches projects through their session notes. ``limit=None``
    returns every one above the cutoff.
    """
    term = _clean_term(term)
    if not term:
        return []
    if outcome is not None:
        outcome.requested = True
    if not semantic_search_available(user):
        return []
    project_ids, project_digests, project_matrix = load_project_vectors(user, projects)
    session_ids, session_digests, session_matrix = load_vectors(
        user,
        Sessions.objects.filter(
            user=user, end_time__isnull=False, project__in=projects.order_by().values("pk")
        ),
    )
    if not project_ids and not session_ids:
        return []
    vector = _query_vector_or_none(user, term)
    if vector is None:
        return []
    if outcome is not None:
        outcome.included = True

    # Every fresh score is aggregated per project before anything is cut.
    cutoff = min_similarity()
    scores = {}
    project_hits = dict(semantic_ranking(project_ids, project_matrix, vector, cutoff=cutoff, limit=None))
    for chunk in _chunks(list(project_hits), 500):
        for pk in fresh_project_ids(user, chunk, project_digests):
            scores[pk] = max(scores.get(pk, project_hits[pk]), project_hits[pk])
    session_hits = dict(semantic_ranking(session_ids, session_matrix, vector, cutoff=cutoff, limit=None))
    for chunk in _chunks(list(session_hits), 500):
        current = fresh_ids(user, chunk, session_digests)
        for session_id, project_id in Sessions.objects.filter(pk__in=current, user=user).values_list(
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

    return _select(ranked, keep, limit)
