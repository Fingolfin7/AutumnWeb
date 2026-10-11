"""Meaning-based retrieval for Sessions search.

Session vectors are written only by ``manage.py embed_sessions``; a search
embeds just the query. Every path degrades to ordinary keyword search: AI
features off, no OpenAI key, no vectors yet, or any provider failure yields no
related sessions and never an error.

Staleness is derived, not flagged: each vector stores a digest of the exact
text it was built from, so a note edit or a project/subproject rename makes it
stale whichever write path caused it (forms, API, import, merges, bulk
updates). Stale vectors are re-embedded by the next sync and are never shown.
"""
from dataclasses import dataclass
import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models.functions import Substr

from core.models import RecommendationUsage, SessionEmbedding, SessionSubproject, Sessions
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
# Chosen from scripts/semantic_search_eval.py; override with
# SEMANTIC_SEARCH_MIN_SIMILARITY once it has been run against real labels.
DEFAULT_MIN_SIMILARITY = 0.35
CANDIDATE_LIMIT = 50
RELATED_LIMIT = 5
RRF_K = 60


def min_similarity():
    return float(getattr(settings, "SEMANTIC_SEARCH_MIN_SIMILARITY", DEFAULT_MIN_SIMILARITY))


# ---------------------------------------------------------------- evidence --

def session_text(project_name, subproject_names, note):
    """The evidence keyword search reads, in one bounded string."""
    parts = [project_name or ""]
    names = ", ".join(sorted({name for name in subproject_names if name}))
    if names:
        parts.append(names)
    note = (note or "").strip()
    if note:
        parts.append(note)
    return "\n".join(parts)[:MAX_INPUT_CHARS]


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


def sync_embeddings(user, embedder, *, batch_size=100, limit=None, dry_run=False):
    """Embed the user's completed sessions whose vector is missing or stale.

    Idempotent: unchanged sessions are skipped by digest. Newest sessions go
    first so a ``limit``-bounded run covers recent work. Each batch commits on
    its own, so a failure keeps earlier progress and the next run resumes.
    """
    texts = session_texts(Sessions.objects.filter(user=user, end_time__isnull=False))
    stored = {
        session_id: (model, digest)
        for session_id, model, digest in SessionEmbedding.objects.filter(
            session__user=user
        ).values_list("session_id", "model", "text_digest")
    }
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
        rows = [
            SessionEmbedding(session_id=pk, model=MODEL, text_digest=digest, vector=encode_vector(vector))
            for (pk, _, digest), vector in zip(batch, vectors)
        ]
        result.embedded += _write(user, rows)
    return result


def _write(user, rows):
    # Sessions deleted while the batch was at the provider are dropped; a row
    # whose text changed meanwhile carries the old digest and stays stale.
    live = set(
        Sessions.objects.filter(pk__in=[row.session_id for row in rows], user=user)
        .values_list("pk", flat=True)
    )
    rows = [row for row in rows if row.session_id in live]
    try:
        with transaction.atomic():
            SessionEmbedding.objects.bulk_create(
                rows,
                update_conflicts=True,
                unique_fields=["session"],
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


def load_vectors(user, sessions):
    """Current-model vectors for the user's sessions within ``sessions``."""
    rows = (
        SessionEmbedding.objects.filter(
            session__user=user, model=MODEL, session__in=sessions.order_by().values("pk")
        )
        .order_by("session_id")
        .values_list("session_id", "text_digest", "vector")
    )
    ids, digests, chunks = [], {}, []
    for session_id, digest, data in rows:
        data = bytes(data)
        if len(data) != VECTOR_BYTES:
            continue
        ids.append(session_id)
        digests[session_id] = digest
        chunks.append(data)
    if not ids:
        return [], {}, None
    np = _numpy()
    matrix = np.frombuffer(b"".join(chunks), dtype="<f4").reshape(len(ids), DIMENSIONS)
    return ids, digests, matrix


def semantic_ranking(ids, matrix, query_vector, *, cutoff, limit=CANDIDATE_LIMIT):
    """[(session_id, cosine)] at or above ``cutoff``, best first."""
    np = _numpy()
    scores = matrix @ query_vector
    ranked = []
    for index in np.argsort(-scores, kind="stable"):
        score = float(scores[index])
        if score < cutoff or len(ranked) >= limit:
            break
        ranked.append((ids[index], score))
    return ranked


def query_vector(user, embedder, term):
    """Embed the query once per user and wording for a short while."""
    key = "semantic-search:q:" + hashlib.sha256(
        f"{user.pk}\0{MODEL}\0{DIMENSIONS}\0{term}".encode("utf-8")
    ).hexdigest()
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


def fresh_ids(user, ids, digests):
    """Those of ``ids`` whose vector still matches the session's current text."""
    texts = session_texts(Sessions.objects.filter(pk__in=ids, user=user, end_time__isnull=False))
    return {pk for pk, text in texts.items() if digests.get(pk) == text_digest(text)}


def find_related_sessions(user, sessions, keyword_sessions, term, *, limit=RELATED_LIMIT):
    """Sessions in ``sessions`` that mean ``term`` but keyword search missed.

    ``sessions`` must already carry the page's ownership and filters (dates,
    context, tags, project include/exclude); ``keyword_sessions`` is the same
    set narrowed by the keyword term. On the page the keyword list is left
    as-is, so these are its semantic-only additions: with no keyword rank
    their reciprocal-rank-fusion order is simply their similarity order.
    """
    term = (term or "").strip()[:MAX_QUERY_CHARS]
    if not term:
        return []
    embedder = embedder_for(user)
    if embedder is None:
        return []
    ids, digests, matrix = load_vectors(user, sessions)
    if not ids:
        return []
    try:
        vector = query_vector(user, embedder, term)
    except Exception as exc:
        logger.warning("semantic_search_unavailable", extra={"user_id": user.pk, "error_category": type(exc).__name__})
        return []
    hits = semantic_ranking(ids, matrix, vector, cutoff=min_similarity())
    if not hits:
        return []
    candidates = [pk for pk, _ in hits]
    keyword = set(keyword_sessions.filter(pk__in=candidates).values_list("pk", flat=True))
    candidates = [pk for pk in candidates if pk not in keyword]
    current = fresh_ids(user, candidates, digests)
    related = [pk for pk in candidates if pk in current][:limit]
    if not related:
        return []
    found = {
        session.pk: session
        for session in Sessions.objects.filter(pk__in=related, user=user)
        .select_related("project")
        .prefetch_related("subprojects")
    }
    return [found[pk] for pk in related if pk in found]
