"""One stateless Streamable HTTP MCP, with user-consented OAuth account access."""
import io
import json
import logging
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, RequestDataTooBig
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, JsonResponse
from django.urls import resolve
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from jsonschema import Draft202012Validator
from rest_framework.authentication import BaseAuthentication
from oauth2_provider.oauth2_backends import get_oauthlib_core

from core.models import MCPAccountLink, MCPGrant

logger = logging.getLogger(__name__)
MAX_BODY = 1024 * 1024
VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}
LATEST_VERSION = "2025-11-25"
MODERN_VERSION = "2026-07-28"
META_PREFIX = "io.modelcontextprotocol/"
OPERATIONS = json.loads((Path(settings.BASE_DIR) / "integrations/mcp/src/operations.json").read_text())
BY_NAME = {op["name"]: op for op in OPERATIONS}
VALIDATORS = {op["name"]: Draft202012Validator(op["inputSchema"]) for op in OPERATIONS}
INSTRUCTIONS = (
    "Autumn time tracking across your authorized accounts. Call list_accounts first; set account explicitly "
    "when comparing accounts. Resolve every numeric ID in the same account. There is no shared account switch. "
    "Only mutate records when the user asks, and never automatically retry an uncertain write. "
    "API-v2 durations are minutes. Preserve timezone offsets. Advance pagination using count and total. "
    "Set include=note when session notes are needed. Responses identify _autumn_account."
)


def _response(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _error(request_id, code, message, status=200):
    return _response({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status)


def _tool_result(value, failed=False):
    return {"content": [{"type": "text", "text": json.dumps(value)}], "structuredContent": value,
            **({"isError": True} if failed else {})}


def _zone(user):
    try:
        return ZoneInfo(user.profile.timezone)
    except (AttributeError, ObjectDoesNotExist, ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(settings.TIME_ZONE)


class _GrantAuthentication(BaseAuthentication):
    """Used only by the internally constructed request, never an HTTP auth class."""
    def authenticate(self, request):
        return request._request._mcp_user, None


def _dispatch(op, args, user):
    path = op["path"]
    query, headers = {}, {}
    for param in op["parameters"]:
        value = args.get(param["argument"])
        if value is None:
            continue
        if param["in"] == "path":
            # All generated path parameters are validated numeric IDs.
            path = path.replace("{" + param["name"] + "}", str(value))
        elif param["in"] == "query":
            query[param["name"]] = str(value)
        elif param["in"] == "header":
            headers["HTTP_" + param["name"].upper().replace("-", "_")] = str(value)
    body = json.dumps({key: args[key] for key in op["bodyKeys"] if key in args}).encode()
    internal = WSGIRequest({
        "REQUEST_METHOD": op["method"], "PATH_INFO": path, "QUERY_STRING": urlencode(query),
        "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
        "SERVER_NAME": "localhost", "SERVER_PORT": "443", "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(body), **headers,
    })
    internal._mcp_user = user
    match = resolve(path)
    if match.namespace != "api_v2":
        raise ValueError("Invalid MCP operation")
    with timezone.override(_zone(user)):
        response = match.func.cls.as_view(authentication_classes=[_GrantAuthentication])(
            internal, *match.args, **match.kwargs
        )
        response.render()
    if response.status_code == 204:
        return {"ok": True}, False
    return json.loads(response.content), response.status_code >= 400


def _call(grant, name, args):
    accounts = grant.accounts.select_related("user", "user__profile").filter(user__is_active=True)
    if grant.oauth_application_id:
        # Unlinking an account takes effect even for an already-issued access token.
        linked = set(MCPAccountLink.objects.filter(owner=grant.owner).values_list("user_id", flat=True))
        accounts = [item for item in accounts if item.user_id == grant.owner_id or item.user_id in linked]
    if name == "list_accounts":
        if args:
            return _tool_result({"error": "list_accounts accepts no arguments."}, True)
        return _tool_result({
            "default_account": grant.default_account,
            "access": "read_write" if grant.allow_writes else "read_only",
            "expires_at": grant.expires_at.isoformat(),
            "accounts": [{"name": item.name, "username": item.user.username, "timezone": str(_zone(item.user))}
                         for item in accounts],
        })
    op = BY_NAME.get(name)
    if not op or (not grant.allow_writes and op["method"] != "GET"):
        return _tool_result({"error": "Tool is unavailable for this connector."}, True)
    if not VALIDATORS[name].is_valid(args):
        # Do not reflect submitted values, which could accidentally contain credentials.
        return _tool_result({"error": "Invalid tool arguments. Follow the tool's input schema."}, True)
    requested = args.get("account", grant.default_account)
    account = next((item for item in accounts
                    if item.name.casefold() == requested.casefold() and item.user.is_active), None)
    if account is None:
        return _tool_result({"error": "Unknown or unavailable account. Use list_accounts."}, True)
    try:
        data, failed = _dispatch(op, args, account.user)
    except Exception:
        # Avoid exception strings, request bodies, bearer tokens, and private notes in logs.
        logger.error("Autumn MCP operation failed: %s", name)
        return _tool_result({"error": "Autumn did not confirm this operation. Check its current state before retrying.",
                             "_autumn_account": account.name}, True)
    value = data if isinstance(data, dict) else {"data": data}
    return _tool_result({**value, "_autumn_account": account.name}, failed)


@csrf_exempt
def mcp_endpoint(request):
    origin = request.headers.get("Origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return _error(None, -32600, "Invalid Origin.", 403)
        if parsed.scheme != request.scheme or parsed.netloc != request.get_host() or parsed.path or parsed.query or parsed.fragment:
            return _error(None, -32600, "Invalid Origin.", 403)
    auth = request.headers.get("Authorization", "").split()
    token = auth[1] if len(auth) == 2 and auth[0].lower() == "bearer" else ""
    grant = None
    if token:
        valid, oauth_request = get_oauthlib_core().verify_request(request, scopes=["autumn:read"])
        if (valid and oauth_request.user and oauth_request.user.is_active
                and oauth_request.access_token.resource == [settings.MCP_RESOURCE]
                and request.build_absolute_uri(request.path) == settings.MCP_RESOURCE):
            grant = MCPGrant.objects.filter(owner=oauth_request.user, oauth_application=oauth_request.client,
                                            revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
            if grant:
                grant.allow_writes = grant.allow_writes and "autumn:write" in oauth_request.scopes
    if grant is None:
        response = _error(None, -32001, "Sign in to Autumn to connect your accounts.", 401)
        response["WWW-Authenticate"] = f'Bearer resource_metadata="{settings.MCP_ORIGIN}/.well-known/oauth-protected-resource/mcp", scope="autumn:read"'
        return response
    if request.method != "POST":
        response = HttpResponse(status=405)
        response["Allow"] = "POST"
        return response
    if request.content_type != "application/json":
        return _error(None, -32600, "Use application/json.", 415)
    accept = request.headers.get("Accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        return _error(None, -32600, "Accept application/json and text/event-stream.", 406)
    try:
        if int(request.headers.get("Content-Length") or 0) > MAX_BODY:
            return _error(None, -32600, "Request too large.", 413)
        raw = request.body
        if len(raw) > MAX_BODY:
            return _error(None, -32600, "Request too large.", 413)
        body = json.loads(raw)
    except RequestDataTooBig:
        return _error(None, -32600, "Request too large.", 413)
    except (ValueError, UnicodeError):
        return _error(None, -32700, "Invalid JSON.", 400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _error(None, -32600, "Expected one JSON-RPC message.", 400)
    request_id, method, params = body.get("id"), body["method"], body.get("params", {})
    if not isinstance(params, dict) or ("id" in body and (type(request_id) not in (str, int))):
        return _error(None, -32600, "Invalid JSON-RPC request.", 400)
    version = request.headers.get("MCP-Protocol-Version", "2025-03-26")
    meta = params.get("_meta", {})
    if not isinstance(meta, dict):
        return _error(request_id, -32602, "Invalid request metadata.", 400)
    modern_claim = meta.get(META_PREFIX + "protocolVersion")
    modern = modern_claim is not None
    if modern:
        if modern_claim != MODERN_VERSION:
            response = _error(request_id, -32022, "Unsupported protocol version", 400)
            payload = json.loads(response.content)
            payload["error"]["data"] = {"supported": [MODERN_VERSION], "requested": modern_claim}
            return _response(payload, 400)
        info = meta.get(META_PREFIX + "clientInfo")
        capabilities = meta.get(META_PREFIX + "clientCapabilities")
        if (request.headers.get("MCP-Protocol-Version", modern_claim) != modern_claim
                or request.headers.get("MCP-Method", method) != method
                or (method == "tools/call" and request.headers.get("MCP-Name", params.get("name")) != params.get("name"))
                or not isinstance(info, dict) or not isinstance(info.get("name"), str)
                or not isinstance(info.get("version"), str) or not isinstance(capabilities, dict)):
            return _error(request_id, -32600, "Invalid or conflicting MCP metadata.", 400)
        if method == "initialize":
            return _error(request_id, -32601, "Modern requests use server/discover.")
        if "requestState" in params or "inputResponses" in params:
            return _error(request_id, -32602, "This server does not request input retries.")
    elif method != "initialize" and version not in VERSIONS:
        return _error(request_id, -32600, "Unsupported MCP protocol version. Initialize to negotiate a supported version.", 400)
    if "id" not in body:
        if not method.startswith("notifications/"):
            return _error(None, -32600, "Requests need an id.", 400)
        return HttpResponse(status=202)
    if method == "server/discover" and modern:
        value = {"supportedVersions": [MODERN_VERSION], "capabilities": {"tools": {}},
                 "instructions": INSTRUCTIONS, "ttlMs": 0, "cacheScope": "private"}
    elif method == "initialize":
        if not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
            return _error(request_id, -32602, "Invalid initialize parameters.")
        requested = params["protocolVersion"]
        value = {"protocolVersion": requested if requested in VERSIONS else LATEST_VERSION,
                 "capabilities": {"tools": {"listChanged": False}},
                 "serverInfo": {"name": "Autumn", "version": "2.0.0"}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        value = {}
    elif method == "tools/list":
        if params.get("cursor"):
            return _error(request_id, -32602, "Invalid cursor.")
        value = {"tools": [{"name": "list_accounts", "description": "List your authorized accounts, default, access and expiry. No credentials are returned.",
                            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
                           *[{key: op[key] for key in ("name", "description", "inputSchema", "annotations")}
                             for op in OPERATIONS if grant.allow_writes or op["method"] == "GET"]]}
    elif method == "tools/call":
        if not isinstance(params.get("name"), str) or not isinstance(params.get("arguments", {}), dict):
            return _error(request_id, -32602, "Invalid tool call.")
        value = _call(grant, params["name"], params.get("arguments", {}))
    else:
        return _error(request_id, -32601, "Method not found.")
    if method == "tools/list":
        for tool in value["tools"]:
            scopes = ["autumn:read"] + ([] if tool["annotations"]["readOnlyHint"] else ["autumn:write"])
            tool["securitySchemes"] = [{"type": "oauth2", "scopes": scopes}]
            tool["_meta"] = {"securitySchemes": tool["securitySchemes"]}
    if modern:
        value = {**value, "resultType": "complete", "_meta": {META_PREFIX + "serverInfo": {"name": "Autumn", "version": "2.0.0"}}}
        if method == "tools/list":
            value.update(ttlMs=0, cacheScope="private")
    return _response({"jsonrpc": "2.0", "id": request_id, "result": value})
