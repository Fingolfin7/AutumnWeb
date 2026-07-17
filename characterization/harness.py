"""Shared support for clone-backed characterization tests."""

import difflib
import hashlib
import json
import os
import re
import unittest
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from freezegun import freeze_time


ROOT = Path(__file__).resolve().parent
META_PATH = ROOT / "meta.json"
GOLDENS = ROOT / "goldens"
CHZ_DB_ENV = os.environ.get("AUTUMN_CHZ_DB")
_CLONE_EXISTED_AT_IMPORT = bool(CHZ_DB_ENV and Path(CHZ_DB_ENV).is_file())
_META_EXISTED_AT_IMPORT = META_PATH.is_file()

# Populate only when an endpoint proves to have unstable list ordering. Values are
# dotted paths mapped to a list-item key. Empty is intentional at initial capture.
ENDPOINT_SORT_KEYS = {}


def load_meta():
    """Load clone metadata, failing with the workflow command when unavailable."""
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssertionError(
            "characterization/meta.json is missing or invalid; run manage.py chz_clone"
        ) from exc


def safe_slug(path, params=None):
    """Return a readable, stable filesystem slug for a request and its params."""
    params = params or {}
    full_repr = path + "?" + repr(sorted(params.items()))
    readable = path.strip("/").replace("/", "-") or "root"
    if params:
        readable += "--" + "--".join(
            "%s-%s" % (key, value) for key, value in sorted(params.items())
        )
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "-", readable).strip("-.")
    if len(readable) > 100:
        readable = readable[:91].rstrip("-.") + "-" + hashlib.sha1(
            full_repr.encode("utf-8")
        ).hexdigest()[:8]
    return readable


def _round_floats(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    return value


def normalize_semantic(payload, endpoint=None):
    """Normalize numeric precision while retaining contract-significant list order."""
    normalized = _round_floats(payload)
    # Explicit endpoint-specific sorting is deliberately opt-in and documented.
    sort_map = ENDPOINT_SORT_KEYS.get(endpoint, {})
    for dotted_path, key in sort_map.items():
        current = normalized
        for part in dotted_path.split(".") if dotted_path else []:
            current = current[int(part)] if isinstance(current, list) else current[part]
        current.sort(key=lambda item: item.get(key))
    return normalized


class CharacterizationTestCase(TestCase):
    """Clone-only TestCase with frozen time, authentication, and golden support."""

    @classmethod
    def setUpClass(cls):
        if not CHZ_DB_ENV:
            raise unittest.SkipTest(
                "AUTUMN_CHZ_DB is unset; clone-backed characterization tests skipped"
            )
        if not _CLONE_EXISTED_AT_IMPORT or not _META_EXISTED_AT_IMPORT:
            raise AssertionError(
                "AUTUMN_CHZ_DB clone or characterization/meta.json is missing; "
                "run manage.py chz_clone"
            )
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.meta = load_meta()
        self._freezer = freeze_time(self.meta["frozen_at"])
        self._freezer.start()
        try:
            user = get_user_model().objects.get(username=self.meta["username"])
        except get_user_model().DoesNotExist as exc:
            self._freezer.stop()
            raise AssertionError(
                "meta.json username is absent from the clone; run manage.py chz_clone"
            ) from exc
        self.user = user
        self.client.force_login(user)

    def tearDown(self):
        self._freezer.stop()
        super().tearDown()

    def golden_check(self, kind, slug, payload):
        if kind not in {"raw", "semantic"}:
            raise ValueError("kind must be raw or semantic")
        mode = os.environ.get("AUTUMN_CHZ_MODE", "compare").lower()
        if mode not in {"capture", "compare"}:
            self.fail("AUTUMN_CHZ_MODE must be capture or compare")

        fingerprint_path = GOLDENS / "fingerprint.json"
        golden_path = GOLDENS / kind / (slug + ".json")
        actual = normalize_semantic(payload, endpoint=slug) if kind == "semantic" else payload
        actual_text = json.dumps(
            actual, ensure_ascii=False, indent=2, sort_keys=True, default=str
        ) + "\n"

        if mode == "capture":
            golden_path.parent.mkdir(parents=True, exist_ok=True)
            fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
            if fingerprint_path.exists():
                fingerprint = json.loads(fingerprint_path.read_text(encoding="utf-8"))
                if fingerprint.get("clone_id") != self.meta["clone_id"]:
                    self.fail(
                        "goldens were captured against a different clone; "
                        "re-run chz_clone + capture"
                    )
            else:
                fingerprint_path.write_text(
                    json.dumps({"clone_id": self.meta["clone_id"]}, indent=2) + "\n",
                    encoding="utf-8",
                )
            golden_path.write_text(actual_text, encoding="utf-8")
            return

        if not fingerprint_path.exists():
            self.fail("no golden fingerprint; run capture mode")
        fingerprint = json.loads(fingerprint_path.read_text(encoding="utf-8"))
        if fingerprint.get("clone_id") != self.meta["clone_id"]:
            self.fail(
                "goldens were captured against a different clone; "
                "re-run chz_clone + capture"
            )
        if not golden_path.exists():
            self.fail("no golden captured for %s; run capture mode" % slug)
        expected_text = golden_path.read_text(encoding="utf-8")
        if expected_text != actual_text:
            diff = "".join(
                difflib.unified_diff(
                    expected_text.splitlines(True),
                    actual_text.splitlines(True),
                    fromfile="golden/%s" % slug,
                    tofile="actual/%s" % slug,
                )
            )
            self.fail("golden mismatch for %s:\n%s" % (slug, diff))

    def raw_request(self, method, path, params=None, body=None, slug=None):
        """Issue a request and capture its exact decoded HTTP representation."""
        params = params or {}
        method = method.upper()
        previous_raise = self.client.raise_request_exception
        self.client.raise_request_exception = False
        try:
            if method == "GET":
                response = self.client.get(path, data=params)
            else:
                response = self.client.generic(
                    method,
                    path,
                    data=json.dumps(body or {}),
                    content_type="application/json",
                )
        finally:
            self.client.raise_request_exception = previous_raise
        payload = {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "content_type": response.get("Content-Type", ""),
            "body_text": response.content.decode(response.charset or "utf-8"),
        }
        payload["params" if method == "GET" else "body"] = params if method == "GET" else (body or {})
        self.golden_check("raw", slug or safe_slug(path, params if method == "GET" else body), payload)
        return response

    def semantic_request(self, path, params=None, slug=None):
        response = self.client.get(path, data=params or {})
        self.assertEqual(response.status_code, 200, response.content.decode("utf-8"))
        self.golden_check(
            "semantic", slug or safe_slug(path, params), response.json()
        )
        return response.json()
