"""One-off, read-only comparison of Luna prompt-cache layouts.

Run locally with a username. Prints usage totals only; never prints prompts,
session notes, credentials, or model responses. Does not use Autumn's result
cache or modify timers/sessions. The OAuth token may refresh normally.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
import logging
import os
import time
from types import SimpleNamespace
from unittest import mock

logging.getLogger("environ.environ").disabled = True
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AutumnWeb.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from openai import OpenAI

from core.services.jev_timer_context import build_jev_candidates, build_jev_context
from core.services.luna_recommendations import _rank_response
from users.codex_auth import CODEX_CHATGPT_BASE_URL, get_profile_access_token


class _CapturedEvents:
    def __iter__(self):
        return iter([SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", output_text='{"recommendations": []}', usage=None),
        )])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _CaptureClient:
    captured = None

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        self.responses = self
        return self

    def __exit__(self, *_args):
        return False

    def create(self, **kwargs):
        _CaptureClient.captured = kwargs
        return _CapturedEvents()


def _request_for(state, original, *, layout):
    request = deepcopy(original)
    if layout == "current":
        request["input"][0]["content"][0]["text"] = json.dumps(state, ensure_ascii=False)
        return request

    # Keep the large, less-frequently-changing portion before the breakpoint.
    # Every original field is present once in either stable or dynamic.
    stable_names = ("decision_rules", "projects", "older_latest_sessions")
    stable = {name: state[name] for name in stable_names}
    dynamic = {name: value for name, value in state.items()
               if name not in stable_names and name != "now"}
    dynamic["now"] = state["now"]
    assert set(stable).isdisjoint(dynamic)
    assert set(stable) | set(dynamic) == set(state)
    # The pinned SDK predates this named parameter, but supports extra_body.
    if layout == "explicit":
        request["extra_body"] = {"prompt_cache_options": {"mode": "explicit"}}
    request["input"] = [
        {"role": "user", "content": [{
            "type": "input_text", "text": json.dumps(stable, ensure_ascii=False),
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }]},
        {"role": "user", "content": [{
            "type": "input_text", "text": json.dumps(dynamic, ensure_ascii=False),
        }]},
    ]
    return request


def _usage(response):
    usage = getattr(response, "usage", None)
    details = getattr(usage, "input_tokens_details", None)
    return {
        "input": getattr(usage, "input_tokens", None),
        "cached": getattr(details, "cached_tokens", None),
        "write": getattr(details, "cache_write_tokens", None),
        "output": getattr(usage, "output_tokens", None),
    }


def _call(client, request):
    started = time.monotonic()
    response = None
    events = client.responses.create(**request)
    with events:
        for event in events:
            if event.type in ("response.completed", "response.incomplete", "response.failed"):
                response = event.response
    return {"status": getattr(response, "status", None),
            "seconds": round(time.monotonic() - started, 2),
            **_usage(response)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--layouts", default="current,explicit")
    args = parser.parse_args()
    user = get_user_model().objects.get(username=args.username)

    request = RequestFactory().get("/timers/")
    request.user = user
    request.session = {}
    candidates = build_jev_candidates(user, request)
    context = build_jev_context(user, request, candidates)
    with mock.patch("core.services.luna_recommendations.OpenAI", _CaptureClient):
        _rank_response("capture-only", candidates, context, oauth=True)
    original = _CaptureClient.captured
    state = json.loads(original["input"][0]["content"][0]["text"])
    changed_time = deepcopy(state)
    local = datetime.fromisoformat(changed_time["now"]["local_datetime"]) + timedelta(minutes=5)
    changed_time["now"]["local_datetime"] = local.isoformat()
    changed_time["now"]["local_time"] = local.strftime("%H:%M:%S")
    changed_time["context"]["local_time"] = local.strftime("%H:%M:%S")
    edited_session = deepcopy(changed_time)
    if edited_session["recent_completed_sessions"]:
        edited_session["recent_completed_sessions"][0]["note"] += " [benchmark edit]"
    snapshots = (state, changed_time, edited_session)
    layouts = args.layouts.split(",")
    if any(layout not in {"current", "explicit", "breakpoint_only"} for layout in layouts):
        raise ValueError("Unknown benchmark layout")
    for snapshot in snapshots:
        for layout in layouts:
            candidate_request = _request_for(snapshot, original, layout=layout)
            assert candidate_request["model"] == original["model"]
            assert candidate_request["reasoning"] == original["reasoning"]
    if args.dry_run:
        print(json.dumps({"valid_layouts": True,
                          "stable_bytes": len(json.dumps({key: state[key] for key in (
                              "decision_rules", "projects", "older_latest_sessions")}, ensure_ascii=False).encode()),
                          "state_bytes": len(json.dumps(state, ensure_ascii=False).encode())}))
        return
    token = get_profile_access_token(user.profile)
    if not token:
        raise RuntimeError("Account OAuth is unavailable")
    print(json.dumps({"snapshot_bytes": len(json.dumps(state, ensure_ascii=False).encode()),
                      "stable_bytes": len(json.dumps({key: state[key] for key in (
                          "decision_rules", "projects", "older_latest_sessions")}, ensure_ascii=False).encode()),
                      "candidates": len(state["candidates"]), "sessions": len(state["recent_completed_sessions"])}),
          flush=True)
    with OpenAI(api_key=token, base_url=CODEX_CHATGPT_BASE_URL, timeout=150, max_retries=0) as client:
        for layout in layouts:
            for step, snapshot in zip(("cold", "time", "session"), snapshots):
                request_data = _request_for(snapshot, original, layout=layout)
                try:
                    result = _call(client, request_data)
                except Exception as exc:
                    result = {"error_type": type(exc).__name__, "error_code": getattr(exc, "code", None),
                              "error_param": getattr(exc, "param", None)}
                    print(json.dumps({"layout": layout, "step": step, **result}), flush=True)
                    break
                print(json.dumps({"layout": layout, "step": step, **result}), flush=True)


if __name__ == "__main__":
    main()
