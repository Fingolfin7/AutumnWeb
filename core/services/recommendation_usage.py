"""Collect provider-reported usage without recording prompts or responses."""
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
import time

_attempts = ContextVar("recommendation_attempts", default=None)
_current = ContextVar("recommendation_attempt", default=None)


@contextmanager
def collect_attempts():
    rows = []
    token = _attempts.set(rows)
    try:
        yield rows
    finally:
        _attempts.reset(token)


@contextmanager
def provider_attempt(provider, model, effort="", auth_route="api_key"):
    row = dict(provider=provider, model=model, effort=effort, auth_route=auth_route, success=False)
    token = _current.set(row)
    started = time.perf_counter()
    try:
        yield
        row["success"] = True
    except Exception as exc:
        row["error_category"] = type(exc).__name__[:80]
        raise
    finally:
        row["duration_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        _current.reset(token)
        if _attempts.get() is not None:
            _attempts.get().append(row)


def _get(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def capture_usage(usage):
    row = _current.get()
    if row is None or usage is None:
        return
    details = _get(usage, "input_tokens_details")
    output_details = _get(usage, "output_tokens_details")
    fields = {
        "input_tokens": _get(usage, "input_tokens"),
        "output_tokens": _get(usage, "output_tokens"),
        "cached_input_tokens": _get(details, "cached_tokens"),
        "cache_write_tokens": _get(details, "cache_creation_tokens"),
        "reasoning_tokens": _get(output_details, "reasoning_tokens"),
    }
    for field, value in fields.items():
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            row[field] = value
    if row["model"] == "jev-1.13.0" and "input_tokens" in row:
        row["estimated_cost_usd"] = (Decimal(row["input_tokens"]) * Decimal("0.042") / Decimal(1000000)).quantize(Decimal("0.00000001"))
        row["pricing"] = {"usd_per_million": {"input": "0.042", "output": "0"},
                          "as_of": "2026-09-22", "basis": "published API rate estimate",
                          "source": "https://docs.typesafe.ai/models"}
    # Reasoning tokens are already included in output_tokens: never add twice.
    if row["model"] in {"gpt-5.6-luna", "gpt-6-luna"} and all(k in row for k in ("input_tokens", "output_tokens")):
        inputs, outputs = row["input_tokens"], row["output_tokens"]
        cached = min(row.get("cached_input_tokens", 0), inputs)
        writes = min(row.get("cache_write_tokens", 0), inputs - cached)
        rates = {"input": "0.20", "cached": "0.02", "write": "0.25", "output": "1.20"}
        if inputs > 272000:
            rates = {"input": "0.40", "cached": "0.04", "write": "0.50", "output": "1.80"}
        if row["model"] == "gpt-6-luna":
            rates = {"input": "0.10", "cached": "0.01", "write": "0.125", "output": "0.50"}
            if inputs > 272000:
                rates = {"input": "0.20", "cached": "0.02", "write": "0.25", "output": "0.75"}
        cost = ((inputs - cached - writes) * Decimal(rates["input"])
                + cached * Decimal(rates["cached"]) + writes * Decimal(rates["write"])
                + outputs * Decimal(rates["output"])) / Decimal(1000000)
        row["estimated_cost_usd"] = cost.quantize(Decimal("0.00000001"))
        row["pricing"] = {"usd_per_million": rates, "as_of": "2026-09-23",
                          "basis": "API-equivalent, not an OAuth bill",
                          "source": "https://developers.openai.com/api/docs/pricing",
                          "cache_detail_reported": details is not None,
                          "unreported_cache_writes": "not included"}
