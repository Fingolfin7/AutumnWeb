"""Keep the Insights instructions while rebuilding their session payload per request."""

import hashlib
import json
import re

from django.core.cache import caches
from toon import decode, encode

from core.utils import build_project_json_from_sessions


SESSION_DATA_SLOT = "[Autumn inserts current filtered sessions here.]"
SESSION_FILTERS_KEY = "session_filters"
MIN_CACHE_SESSIONS = 300
MAX_CACHED_BYTES = 4 * 1024 * 1024

_PROMPT_START = re.compile(
    r"\A\s*(?:You are an expert project and time tracking analyst\. "
    r"Your job is to analyze projects, sessions,\n"
    r"        and session logs to provide insights based on the data provided\."
    r"|[^\n]+ has updated their session data\.[ \t]*\n"
    r"        Refer to the new session data for the remainder of the conversation\.)"
)
_DATA_HEADING = re.compile(r"\n        (?:Sessions data|New sessions data):\n        ")
_SLOT_LINE = re.compile(
    r"\n[ \t]*(?:Sessions data|New sessions data):[ \t]*\n[ \t]*("
    + re.escape(SESSION_DATA_SLOT)
    + r")\s*\Z"
)
_FOOTER = "\n        "
_PROJECT_FIELDS = {
    "Start Date", "Last Updated", "Total Time", "Status", "Description",
    "Sub Projects", "Session History",
}


def encode_session_data(sessions, *, username, force_refresh=False):
    """Reuse TOON encoding only when the current model-visible data matches."""
    projects = build_project_json_from_sessions(sessions, autumn_compatible=True)
    if len(sessions) < MIN_CACHE_SESSIONS:
        return encode(projects)

    # Include names, notes, ordering and rendered times, so database edits,
    # timezone changes and related-search results need no separate invalidation.
    try:
        source = json.dumps([username, projects], ensure_ascii=True, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        return encode(projects)
    if len(source) > MAX_CACHED_BYTES:
        return encode(projects)

    key = hashlib.sha256(source).hexdigest()
    cache = caches["insights_session_data"]
    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached

    payload = encode(projects)
    if len(payload.encode("utf-8")) <= MAX_CACHED_BYTES:
        cache.set(key, payload)
    return payload


def compact_session_prompt(content):
    """Replace the trailing data block of a known legacy system prompt."""
    if has_session_slot(content) or not _PROMPT_START.match(content) or not content.endswith(_FOOTER):
        return content
    # In older templates the user's question was also interpolated above the
    # data. Leave an ambiguous heading alone instead of cutting into a question.
    headings = list(_DATA_HEADING.finditer(content))
    if len(headings) != 1:
        return content
    data_start = headings[0].end()
    data = content[data_start:-len(_FOOTER)]
    if data:
        try:
            try:
                projects = json.loads(data)
            except json.JSONDecodeError:
                projects = decode(data)
                if encode(projects) != data:
                    return content
        except Exception:
            # Imported historical text can exercise parser errors beyond the
            # documented exception types. An unsafe cut is worse than a skip.
            return content
        if not isinstance(projects, dict) or any(
            not isinstance(project, dict) or project.keys() != _PROJECT_FIELDS
            for project in projects.values()
        ):
            return content
    return f"{content[:data_start]}{SESSION_DATA_SLOT}{_FOOTER}"


def has_session_slot(content):
    return bool(_SLOT_LINE.search(content))


def render_session_prompt(content, session_data):
    if session_data is None:
        return content
    content = compact_session_prompt(content)
    slot = _SLOT_LINE.search(content)
    if slot:
        return f"{content[:slot.start(1)]}{session_data}{content[slot.end(1):]}"
    return content
