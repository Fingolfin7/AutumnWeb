"""Database-backed cache with short atomic leases, never locks during inference."""
from datetime import timedelta
import hashlib
import uuid

from django.db.models import Q
from django.utils import timezone

from core.models import RecommendationCache, RecommendationUsage
from .recommendation_usage import collect_attempts

CACHE_TTL = timedelta(minutes=30)
# Longer than both provider attempts plus their possible final blocked reads.
LEASE_TTL = timedelta(minutes=7)


class RecommendationPending(Exception):
    pass


def get_or_generate(user, provider, scope, key, generate):
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    row, _ = RecommendationCache.objects.get_or_create(user=user, provider=provider, scope=scope)
    now = timezone.now()
    if row.fingerprint == fingerprint and row.result is not None and row.expires_at > now:
        RecommendationUsage.objects.create(user=user, provider=provider, event="cache_hit", success=True)
        return row.result
    token = str(uuid.uuid4())
    acquired = RecommendationCache.objects.filter(pk=row.pk, lease_until__lte=now).filter(
        ~Q(fingerprint=fingerprint) | Q(expires_at__lte=now) | Q(result__isnull=True)
    ).update(lease_token=token, lease_until=now + LEASE_TTL,
             fingerprint=fingerprint, result=None, expires_at=now)
    if not acquired:
        raise RecommendationPending()
    owned = RecommendationCache.objects.filter(pk=row.pk, lease_token=token)
    with collect_attempts() as attempts:
        try:
            result = generate()
            finished = timezone.now()
            owned.update(result=result, generated_at=finished, expires_at=finished + CACHE_TTL,
                         lease_until=finished, lease_token="")
            return result
        except Exception:
            # A brief cooldown avoids hammering an unavailable provider.
            owned.update(lease_until=timezone.now() + timedelta(seconds=15), lease_token="")
            raise
        finally:
            RecommendationUsage.objects.bulk_create([
                RecommendationUsage(user=user, **attempt) for attempt in attempts
            ])
