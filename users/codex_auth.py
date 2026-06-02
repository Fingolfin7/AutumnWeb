import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone


CODEX_CLIENT_ID = getattr(
    settings,
    "CODEX_CLIENT_ID",
    "app_EMoamEEZ73f0CkXaXp7hrann",
)
CODEX_AUTH_ISSUER = getattr(settings, "CODEX_AUTH_ISSUER", "https://auth.openai.com")
CODEX_CHATGPT_BASE_URL = getattr(
    settings,
    "CODEX_CHATGPT_BASE_URL",
    "https://chatgpt.com/backend-api/codex",
)
CODEX_DEVICE_LOGIN_TIMEOUT_MINUTES = 15


class CodexAuthError(RuntimeError):
    pass


class CodexDevicePending(CodexAuthError):
    pass


@dataclass(frozen=True)
class CodexDeviceCode:
    verification_url: str
    user_code: str
    device_auth_id: str
    interval: int
    expires_at: str

    def as_session_dict(self) -> dict[str, Any]:
        return {
            "verification_url": self.verification_url,
            "user_code": self.user_code,
            "device_auth_id": self.device_auth_id,
            "interval": self.interval,
            "expires_at": self.expires_at,
        }


def _issuer() -> str:
    return CODEX_AUTH_ISSUER.rstrip("/")


def _device_auth_base_url() -> str:
    return f"{_issuer()}/api/accounts"


def _post_json(url: str, payload: dict[str, Any], timeout: int = 15) -> dict[str, Any]:
    response = requests.post(url, json=payload, timeout=timeout)
    if not response.ok:
        raise CodexAuthError(f"Codex auth request failed with status {response.status_code}.")
    data = response.json()
    if not isinstance(data, dict):
        raise CodexAuthError("Codex auth response was not an object.")
    return data


def start_device_code_login() -> CodexDeviceCode:
    data = _post_json(
        f"{_device_auth_base_url()}/deviceauth/usercode",
        {"client_id": CODEX_CLIENT_ID},
    )
    user_code = str(data.get("user_code") or data.get("usercode") or "").strip()
    device_auth_id = str(data.get("device_auth_id") or "").strip()
    if not user_code or not device_auth_id:
        raise CodexAuthError("Codex auth response did not include a user code.")

    try:
        interval = int(str(data.get("interval") or "5").strip())
    except ValueError:
        interval = 5

    return CodexDeviceCode(
        verification_url=f"{_issuer()}/codex/device",
        user_code=user_code,
        device_auth_id=device_auth_id,
        interval=max(1, interval),
        expires_at=(
            timezone.now() + timedelta(minutes=CODEX_DEVICE_LOGIN_TIMEOUT_MINUTES)
        ).isoformat(),
    )


def poll_device_code_login(device_code: dict[str, Any]) -> dict[str, str]:
    expires_at_raw = device_code.get("expires_at")
    if expires_at_raw:
        expires_at = datetime.fromisoformat(str(expires_at_raw))
        if timezone.is_naive(expires_at):
            expires_at = timezone.make_aware(expires_at)
        if timezone.now() > expires_at:
            raise CodexAuthError("Codex login code expired. Start a new login.")

    response = requests.post(
        f"{_device_auth_base_url()}/deviceauth/token",
        json={
            "device_auth_id": device_code.get("device_auth_id"),
            "user_code": device_code.get("user_code"),
        },
        timeout=15,
    )
    if response.status_code in {403, 404}:
        raise CodexDevicePending("Codex login is still waiting for authorization.")
    if not response.ok:
        raise CodexAuthError(f"Codex auth polling failed with status {response.status_code}.")

    code_data = response.json()
    if not isinstance(code_data, dict):
        raise CodexAuthError("Codex auth polling response was not an object.")

    authorization_code = str(code_data.get("authorization_code") or "").strip()
    code_verifier = str(code_data.get("code_verifier") or "").strip()
    if not authorization_code or not code_verifier:
        raise CodexAuthError("Codex auth polling response did not include login credentials.")

    return exchange_code_for_tokens(authorization_code, code_verifier)


def exchange_code_for_tokens(authorization_code: str, code_verifier: str) -> dict[str, str]:
    response = requests.post(
        f"{_issuer()}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": f"{_issuer()}/deviceauth/callback",
            "client_id": CODEX_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    if not response.ok:
        raise CodexAuthError(f"Codex token exchange failed with status {response.status_code}.")
    data = response.json()
    return _validate_token_bundle(data)


def refresh_token_bundle(bundle: dict[str, Any]) -> dict[str, str]:
    refresh_token = str(bundle.get("refresh_token") or "").strip()
    if not refresh_token:
        raise CodexAuthError("Codex login does not include a refresh token.")

    response = requests.post(
        f"{_issuer()}/oauth/token",
        json={
            "client_id": CODEX_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    if not response.ok:
        raise CodexAuthError(f"Codex token refresh failed with status {response.status_code}.")

    refreshed = response.json()
    merged = {**bundle, **{k: v for k, v in refreshed.items() if v}}
    return _validate_token_bundle(merged)


def serialize_token_bundle(bundle: dict[str, Any]) -> str:
    return json.dumps(_validate_token_bundle(bundle), separators=(",", ":"))


def deserialize_token_bundle(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _validate_token_bundle(data)
    except CodexAuthError:
        return None


def token_bundle_summary(bundle: dict[str, Any] | None) -> dict[str, Any]:
    if not bundle:
        return {}
    summary = {
        "email": None,
        "plan": None,
        "account_id": None,
        "expires_at": None,
    }
    id_token = bundle.get("id_token")
    if isinstance(id_token, str):
        payload = decode_jwt_payload(id_token) or {}
        profile = payload.get("https://api.openai.com/profile") or {}
        auth = payload.get("https://api.openai.com/auth") or {}
        summary["email"] = payload.get("email") or profile.get("email")
        summary["plan"] = auth.get("chatgpt_plan_type")
        summary["account_id"] = auth.get("chatgpt_account_id")
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            summary["expires_at"] = datetime.fromtimestamp(
                exp, tz=dt_timezone.utc
            ).isoformat()
    return summary


def access_token_expires_soon(bundle: dict[str, Any], leeway_seconds: int = 300) -> bool:
    access_token = bundle.get("access_token")
    if not isinstance(access_token, str):
        return True
    payload = decode_jwt_payload(access_token)
    if not payload:
        return False
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    expires_at = datetime.fromtimestamp(exp, tz=dt_timezone.utc)
    return expires_at <= datetime.now(dt_timezone.utc) + timedelta(seconds=leeway_seconds)


def decode_jwt_payload(jwt: str) -> dict[str, Any] | None:
    parts = jwt.split(".")
    if len(parts) < 2 or not parts[1]:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded.decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _validate_token_bundle(data: dict[str, Any]) -> dict[str, str]:
    id_token = str(data.get("id_token") or "").strip()
    access_token = str(data.get("access_token") or "").strip()
    refresh_token = str(data.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise CodexAuthError("Codex token response did not include access and refresh tokens.")
    return {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
