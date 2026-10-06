import base64
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, Grant, RefreshToken
from oauth2_provider.cimd import CIMDError

from core.models import MCPAccountLink, MCPGrant, MCPGrantAccount, Projects
from core.mcp_oauth import OAUTH_REQUEST_FIELDS, MCPMetadataFetcher, display_host


@override_settings(MCP_ORIGIN="http://testserver", MCP_RESOURCE="http://testserver/mcp")
class MCPOAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user("oauth-owner", "owner@example.com", "owner-test-password")
        self.extra = User.objects.create_user("oauth-extra", "extra@example.com", "extra-test-password")
        self.other = User.objects.create_user("oauth-stranger", "other@example.com", "other-test-password")
        self.verifier = "v" * 64
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        registered = self.client.post("/oauth/register/", json.dumps({
            "client_name": "Test client", "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "scope": "autumn:read autumn:write",
        }), content_type="application/json")
        self.assertEqual(registered.status_code, 201, registered.content)
        self.client_id = registered.json()["client_id"]
        self.application = Application.objects.get(client_id=self.client_id)
        self.query = {"client_id": self.client_id, "redirect_uri": "https://client.example/callback",
                      "response_type": "code", "scope": "autumn:read autumn:write", "state": "client-state",
                      "code_challenge": self.challenge, "code_challenge_method": "S256", "resource": settings.MCP_RESOURCE}
        self.client.force_login(self.owner)

    def authorize(self, accounts=None, writes=False, **overrides):
        accounts = accounts or [self.owner]
        values = {**self.query, "allow": "true", "accounts": [user.pk for user in accounts],
                  "default_account": accounts[0].pk, **({"allow_writes": "true"} if writes else {}), **overrides}
        return self.client.post("/oauth/authorize/", values)

    def token(self, response=None, verifier=None):
        response = response or self.authorize()
        self.assertEqual(response.status_code, 302, response.content)
        parsed = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(parsed["state"], ["client-state"])
        self.assertEqual(parsed["iss"], [settings.OAUTH2_PROVIDER["OIDC_ISS_ENDPOINT"]])
        exchange = self.client.post("/oauth/token/", {
            "grant_type": "authorization_code", "client_id": self.client_id, "code": parsed["code"][0],
            "redirect_uri": self.query["redirect_uri"], "code_verifier": verifier or self.verifier,
            "resource": settings.MCP_RESOURCE,
        })
        self.assertEqual(exchange.status_code, 200, exchange.content)
        return exchange.json()

    def rpc(self, token, method="tools/call", params=None, **headers):
        return self.client.post("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                   "params": params or {"name": "list_accounts", "arguments": {}}}),
                                content_type="application/json", HTTP_AUTHORIZATION="Bearer " + token,
                                HTTP_ACCEPT="application/json, text/event-stream", **headers)

    def link(self, user=None, password="extra-test-password"):
        return self.client.post("/mcp/accounts/add/", {"username": (user or self.extra).username, "password": password})

    def refresh(self, refresh_token):
        return self.client.post("/oauth/token/", {"grant_type": "refresh_token", "client_id": self.client_id,
                                                  "refresh_token": refresh_token, "resource": settings.MCP_RESOURCE})

    def test_metadata_and_unauthorized_challenge(self):
        auth = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(auth["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(auth["grant_types_supported"], ["authorization_code", "refresh_token"])
        self.assertTrue(auth["client_id_metadata_document_supported"])
        self.assertTrue(auth["authorization_response_iss_parameter_supported"])
        self.assertIn("none", auth["token_endpoint_auth_methods_supported"])
        resource = self.client.get("/.well-known/oauth-protected-resource/mcp").json()
        self.assertEqual(resource["resource"], settings.OAUTH2_PROVIDER["OAUTH2_PROTECTED_RESOURCE_IDENTIFIER"])
        self.assertEqual(set(resource["scopes_supported"]), {"autumn:read", "autumn:write"})
        self.assertEqual(self.rpc("").status_code, 401)
        self.assertIn("resource_metadata=", self.rpc("")["WWW-Authenticate"])
        # MCP clients prefer a challenge's scope over resource metadata. Restricting
        # discovery to read here would hide the optional write choice during consent.
        self.assertNotIn("scope=", self.rpc("")["WWW-Authenticate"])
        self.assertNotIn("error=", self.rpc("")["WWW-Authenticate"])
        self.assertIn('error="invalid_token"', self.rpc("not-a-token")["WWW-Authenticate"])

    def test_client_requested_read_only_cannot_be_escalated_by_the_consent_checkbox(self):
        page = self.client.get("/oauth/authorize/", {**self.query, "scope": "autumn:read"})
        self.assertNotContains(page, 'name="allow_writes"')
        token = self.token(self.authorize(writes=True, scope="autumn:read"))
        self.assertEqual(token["scope"], "autumn:read")
        self.assertFalse(MCPGrant.objects.get().allow_writes)
        result = self.rpc(token["access_token"], params={"name": "create_project", "arguments": {"name": "denied"}}).json()["result"]
        self.assertTrue(result["isError"])
        self.assertFalse(Projects.objects.exists())

    def test_official_sdk_discovery_can_request_optional_write_consent(self):
        import shutil
        import subprocess
        from pathlib import Path

        root = Path(settings.BASE_DIR) / "integrations/mcp"
        if not shutil.which("node") or not (root / "node_modules/@modelcontextprotocol/sdk").exists():
            self.skipTest("Run npm ci in integrations/mcp for official SDK scope verification")
        challenge = self.rpc("")["WWW-Authenticate"]
        discovery = {
            "challenge": challenge,
            "resourceMetadata": self.client.get("/.well-known/oauth-protected-resource/mcp").json(),
            "authorizationMetadata": self.client.get("/.well-known/oauth-authorization-server").json(),
        }
        for header, expected in [(challenge, {"autumn:read", "autumn:write"}),
                                  (challenge + ', scope="autumn:read"', {"autumn:read"})]:
            discovery["challenge"] = header
            result = subprocess.run(["node", "scripts/verify-scope-discovery.mjs"], cwd=root,
                                    input=json.dumps(discovery), capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            requested = json.loads(result.stdout)["scope"]
            self.assertEqual(set(requested.split()), expected)
            page = self.client.get("/oauth/authorize/", {**self.query, "scope": requested})
            self.assertEqual(page.status_code, 200)
            self.assertEqual('name="allow_writes"' in page.content.decode(), "autumn:write" in expected)

    def test_new_user_has_only_their_own_account_and_consent_is_always_shown(self):
        response = self.client.get("/oauth/authorize/", self.query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["form"].fields["accounts"].queryset), [self.owner])
        token = self.token()["access_token"]
        listed = self.rpc(token).json()["result"]["structuredContent"]
        self.assertEqual([item["name"] for item in listed["accounts"]], [self.owner.username])
        self.assertEqual(listed["access"], "read_only")
        self.assertNotIn(token, json.dumps(listed))
        self.assertEqual(self.client.get("/oauth/authorize/", {**self.query, "approval_prompt": "auto"}).status_code, 200)

    def test_account_link_requires_password_and_preserves_primary_session(self):
        self.assertEqual(self.link(password="incorrect").status_code, 200)
        self.assertFalse(MCPAccountLink.objects.exists())
        self.assertEqual(self.link().status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.owner.pk)
        self.assertEqual(MCPAccountLink.objects.get().user, self.extra)
        token = self.token(self.authorize([self.owner, self.extra]))["access_token"]
        for account in [self.owner, self.extra, self.owner]:
            result = self.rpc(token, params={"name": "me", "arguments": {"account": account.username}}).json()["result"]
            self.assertEqual(result["structuredContent"]["user"]["id"], account.pk)
        foreign = self.rpc(token, params={"name": "me", "arguments": {"account": self.other.username}}).json()["result"]
        self.assertTrue(foreign["isError"])

    def test_unproved_account_and_unselected_default_are_rejected(self):
        for values in [{"accounts": [self.other]}, {"default_account": self.other.pk}]:
            response = self.authorize(**values)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(Grant.objects.exists())
            self.assertFalse(MCPGrant.objects.exists())

    def test_other_user_cannot_inherit_accounts_or_manage_connections(self):
        self.link()
        token = self.token(self.authorize([self.owner, self.extra]))["access_token"]
        owner_grant = MCPGrant.objects.get(owner=self.owner)
        link = MCPAccountLink.objects.get(owner=self.owner)
        self.client.force_login(self.other)
        form = self.client.get("/oauth/authorize/", self.query).context["form"]
        self.assertEqual(list(form.fields["accounts"].queryset), [self.other])
        self.client.post("/mcp/connections/", {"action": "revoke", "id": owner_grant.pk})
        self.client.post("/mcp/connections/", {"action": "unlink", "id": link.pk})
        self.assertEqual(self.rpc(token).status_code, 200)
        self.assertTrue(MCPAccountLink.objects.filter(pk=link.pk).exists())
        other_token = self.token(self.authorize([self.other]))["access_token"]
        listed = self.rpc(other_token).json()["result"]["structuredContent"]
        self.assertEqual([item["name"] for item in listed["accounts"]], [self.other.username])

    def test_pkce_code_single_use_and_audience_binding(self):
        response = self.authorize()
        code = parse_qs(urlsplit(response["Location"]).query)["code"][0]
        body = {"grant_type": "authorization_code", "client_id": self.client_id, "code": code,
                "redirect_uri": self.query["redirect_uri"], "code_verifier": "wrong" * 12, "resource": settings.MCP_RESOURCE}
        self.assertEqual(self.client.post("/oauth/token/", body).status_code, 400)
        token = self.token(response)["access_token"]
        body["code_verifier"] = self.verifier
        self.assertEqual(self.client.post("/oauth/token/", body).status_code, 400)
        self.assertEqual(self.rpc(token).status_code, 200)
        stored = AccessToken.objects.get(token_checksum=hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(stored.token, token)
        self.assertEqual(stored.resource, [settings.MCP_RESOURCE])
        stored.resource = []
        stored.save()
        self.assertEqual(self.rpc(token).status_code, 401)
        stored.resource = ["https://another.example/mcp"]
        stored.save()
        self.assertEqual(self.rpc(token).status_code, 401)

    def test_refresh_rotation_and_replay_revoke_the_family(self):
        first = self.token()
        body = {"grant_type": "refresh_token", "client_id": self.client_id, "refresh_token": first["refresh_token"],
                "resource": settings.MCP_RESOURCE}
        refreshed = self.client.post("/oauth/token/", body)
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        second = refreshed.json()
        self.assertNotEqual(first["refresh_token"], second["refresh_token"])
        self.assertEqual(self.rpc(second["access_token"]).status_code, 200)
        self.assertEqual(self.client.post("/oauth/token/", body).status_code, 400)
        self.assertEqual(self.rpc(second["access_token"]).status_code, 401)

    def test_scope_enforcement_for_real_api_writes(self):
        token = self.token()["access_token"]
        self.assertTrue(self.rpc(token, params={"name": "create_project", "arguments": {"name": "denied"}}).json()["result"]["isError"])
        self.assertFalse(Projects.objects.exists())
        token = self.token(self.authorize(writes=True))["access_token"]
        result = self.rpc(token, params={"name": "create_project", "arguments": {"name": "explicitly approved"}}).json()["result"]
        self.assertFalse(result.get("isError"))
        self.assertEqual(Projects.objects.get().user, self.owner)

    def test_reconsent_replaces_accounts_and_invalidates_previous_codes_and_tokens(self):
        self.link()
        pending = self.authorize([self.owner, self.extra])
        first = self.token(self.authorize([self.owner, self.extra]))
        second = self.token(self.authorize([self.owner]))
        self.assertEqual(self.rpc(first["access_token"]).status_code, 401)
        self.assertEqual(self.rpc(second["access_token"]).status_code, 200)
        self.assertEqual(MCPGrantAccount.objects.count(), 1)
        code = parse_qs(urlsplit(pending["Location"]).query)["code"][0]
        self.assertEqual(self.client.post("/oauth/token/", {"grant_type": "authorization_code", "client_id": self.client_id,
                            "code": code, "code_verifier": self.verifier, "redirect_uri": self.query["redirect_uri"]}).status_code, 400)

    def test_unlink_and_revoke_are_immediate(self):
        self.link()
        first = self.token(self.authorize([self.owner, self.extra]))
        self.client.post("/mcp/connections/", {"action": "unlink", "id": MCPAccountLink.objects.get().pk})
        self.assertEqual(self.rpc(first["access_token"]).status_code, 401)
        self.assertFalse(MCPAccountLink.objects.exists())
        second = self.token()
        self.client.post("/mcp/connections/", {"action": "revoke", "id": MCPGrant.objects.get().pk})
        self.assertEqual(self.rpc(second["access_token"]).status_code, 401)
        self.assertFalse(RefreshToken.objects.exists())

    def test_forged_resource_plain_pkce_and_bad_redirects_fail(self):
        for query in [{"code_challenge_method": "plain"}, {"code_challenge": "", "code_challenge_method": ""},
                      {"redirect_uri": "https://attacker.example/callback"}]:
            response = self.client.get("/oauth/authorize/", {**self.query, **query})
            self.assertNotIn("code=", response.get("Location", ""))
            self.assertFalse(Grant.objects.exists())
        response = self.authorize(resource="https://attacker.example/mcp")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Grant.objects.exists())

    def test_failed_consent_does_not_change_existing_permissions(self):
        first = self.token()
        response = self.authorize(writes=True, redirect_uri="https://attacker.example/callback")
        self.assertNotIn("code=", response.get("Location", ""))
        self.assertFalse(MCPGrant.objects.get().allow_writes)
        self.assertEqual(self.rpc(first["access_token"]).status_code, 200)

    def test_csrf_for_consent_linking_and_revocation_but_not_bearer_requests(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for path in ["/oauth/authorize/", "/mcp/accounts/add/", "/mcp/connections/"]:
            self.assertEqual(client.post(path, {}).status_code, 403)
        token = self.token()["access_token"]
        self.assertEqual(client.post("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
                                    content_type="application/json", HTTP_AUTHORIZATION="Bearer " + token,
                                    HTTP_ACCEPT="application/json, text/event-stream").status_code, 200)

    def test_account_sign_in_throttling_and_safe_return_url(self):
        for _ in range(10):
            self.assertEqual(self.link(password="wrong").status_code, 200)
        self.assertEqual(self.link().status_code, 429)
        cache.clear()
        response = self.client.post("/mcp/accounts/add/", {"username": self.extra.username, "password": "extra-test-password",
                                                           "next": "//attacker.example"})
        self.assertEqual(response["Location"], "/mcp/connections/")

    def test_modern_chatgpt_requests_can_omit_optional_routing_headers(self):
        token = self.token()["access_token"]
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "ChatGPT", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {}}
        response = self.rpc(token, "tools/list", {"_meta": meta})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["resultType"], "complete")

    def test_published_client_identity_can_advertise_additional_grants(self):
        with patch("oauth2_provider.cimd.SafeMetadataFetcher.fetch", return_value=({"grant_types": [
            "authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"]}, 300)):
            metadata, age = MCPMetadataFetcher().fetch("https://client.example/metadata")
            self.assertEqual(metadata["grant_types"], ["authorization_code", "refresh_token"])
            self.assertEqual(age, 300)
        for grants in [["password"], "authorization_code", [{"authorization_code": True}]]:
            with patch("oauth2_provider.cimd.SafeMetadataFetcher.fetch", return_value=({"grant_types": grants}, 300)):
                with self.assertRaises(CIMDError):
                    MCPMetadataFetcher().fetch("https://client.example/metadata")

    def test_invalid_client_identity_shows_an_error_instead_of_empty_consent(self):
        response = self.client.get("/oauth/authorize/", {**self.query, "client_id": "not-a-client"})
        self.assertContains(response, "Unable to connect", status_code=400)

    def test_published_claude_metadata_completes_code_flow_without_enabling_jwt_grants(self):
        self.client_id = "https://client.example/oauth/metadata"
        self.query["client_id"] = self.client_id
        metadata = {"client_id": self.client_id, "client_name": "Published client",
                    "redirect_uris": [self.query["redirect_uri"]], "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"],
                    "response_types": ["code"]}
        with patch("oauth2_provider.cimd.SafeMetadataFetcher.fetch", return_value=(metadata, 300)):
            response = self.client.get("/oauth/authorize/", self.query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["application"].name, "Published client")
            self.assertEqual(response.context["client_host"], "client.example")
            self.assertContains(response, "App details published at")
            self.assertContains(response, "comes from the details published at client.example")
            self.assertEqual(list(response.context["form"].fields["accounts"].queryset), [self.owner])
            token = self.token()["access_token"]
            self.assertEqual(self.rpc(token).status_code, 200)
            jwt = self.client.post("/oauth/token/", {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                    "client_id": self.client_id, "assertion": "untrusted"})
            self.assertEqual(jwt.status_code, 400)

    def test_additional_account_owner_can_withdraw_the_link(self):
        self.link()
        token = self.token(self.authorize([self.owner, self.extra]))["access_token"]
        link = MCPAccountLink.objects.get()
        self.client.force_login(self.other)
        self.client.post("/mcp/connections/", {"action": "revoke-link", "id": link.pk})
        self.assertEqual(self.rpc(token).status_code, 200)
        self.client.force_login(self.extra)
        self.assertContains(self.client.get("/mcp/connections/"), "Revoke access for oauth-owner")
        self.client.post("/mcp/connections/", {"action": "revoke-link", "id": link.pk})
        self.assertEqual(self.rpc(token).status_code, 401)
        self.assertFalse(MCPAccountLink.objects.exists())

    def test_fixed_account_credentials_are_not_accepted(self):
        from datetime import timedelta
        from django.utils import timezone
        token = "autumn_mcp_retired_test_credential"
        MCPGrant.objects.create(owner=self.owner, name="Retired connection", default_account=self.owner.username,
                                token_digest=hashlib.sha256(token.encode()).hexdigest(),
                                expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.rpc(token).status_code, 401)

    def test_consent_identifies_where_the_answer_goes_and_that_the_name_is_self_supplied(self):
        Application.objects.filter(pk=self.application.pk).update(name="ChatGPT")
        page = self.client.get("/oauth/authorize/", self.query)
        self.assertEqual((page.context["redirect_host"], page.context["client_host"]), ("client.example", ""))
        self.assertContains(page, "Your answer is sent to")
        self.assertContains(page, "was supplied by the app itself")
        # Only the host is shown; the full callback stays in the hidden form field.
        self.assertContains(page, self.query["redirect_uri"], count=1)
        invalid = self.authorize(default_account="")
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.context["redirect_host"], "client.example")
        self.assertContains(invalid, "was supplied by the app itself")
        self.assertEqual(display_host("https://Bücher.example:8443/cb?state=private"), "xn--bcher-kva.example:8443")
        self.assertEqual(display_host("https://[::1]/cb"), "[::1]")
        for unusable in ["", "javascript:alert(1)", "/relative", "https://a..b/cb", "https://host:99999/"]:
            self.assertEqual(display_host(unusable), "")

    def test_add_account_return_url_must_stay_on_this_site(self):
        consent = "/oauth/authorize/?" + urlencode(self.query)
        for target in ["/\t/attacker.example", "/\n/attacker.example", "/\r\n/attacker.example", "/\x7f/attacker.example",
                       "//attacker.example", "/\\attacker.example", "https://attacker.example/", "attacker.example"]:
            cache.clear()
            page = self.client.get("/mcp/accounts/add/", {"next": target})
            self.assertEqual(page.context["next"], "/mcp/connections/")
            self.assertNotContains(page, "attacker.example")
            linked = self.client.post("/mcp/accounts/add/", {"username": self.extra.username,
                                                             "password": "extra-test-password", "next": target})
            self.assertEqual(linked["Location"], "/mcp/connections/")
        # A legitimate return to consent keeps its query string exactly.
        self.assertEqual(self.client.get("/mcp/accounts/add/", {"next": consent}).context["next"], consent)
        linked = self.client.post("/mcp/accounts/add/", {"username": self.extra.username,
                                                         "password": "extra-test-password", "next": consent})
        self.assertEqual(linked["Location"], consent)

    def test_refresh_requires_live_consent_and_an_active_owner(self):
        refreshed = self.refresh(self.token()["refresh_token"])
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        current = refreshed.json()["refresh_token"]
        grant = MCPGrant.objects.get()

        def refused(refresh_token):
            issued = AccessToken.objects.count()
            response = self.refresh(refresh_token)
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(response.json()["error"], "invalid_grant")
            self.assertEqual(AccessToken.objects.count(), issued)

        expires = grant.expires_at
        grant.expires_at = timezone.now() - timedelta(seconds=1)
        grant.save()
        refused(current)
        grant.expires_at, grant.revoked_at = expires, timezone.now()
        grant.save()
        refused(current)
        grant.revoked_at = None
        grant.save()
        self.owner.is_active = False
        self.owner.save()
        refused(current)
        self.owner.is_active = True
        self.owner.save()
        restored = self.refresh(current)
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(self.rpc(restored.json()["access_token"]).status_code, 200)
        MCPGrant.objects.all().delete()
        refused(restored.json()["refresh_token"])

    def test_throttled_account_sign_in_never_checks_the_password(self):
        with patch("core.mcp_oauth._limited", return_value=True), \
                patch("django.contrib.auth.forms.authenticate") as authenticate:
            for password in ["wrong", "extra-test-password"]:
                response = self.link(password=password)
                self.assertEqual(response.status_code, 429)
                self.assertNotIn("form", response.context)
                self.assertNotContains(response, 'name="password"', status_code=429)
        authenticate.assert_not_called()
        self.assertFalse(MCPAccountLink.objects.exists())

    def test_adding_an_account_after_invalid_consent_returns_to_the_same_request(self):
        invalid = self.authorize(default_account="")
        self.assertEqual(invalid.status_code, 200)
        back = parse_qs(urlsplit(invalid.context["link_url"]).query)["next"][0]
        self.assertTrue(back.startswith("/oauth/authorize/?"))
        self.assertLessEqual(set(parse_qs(urlsplit(back).query)), set(OAUTH_REQUEST_FIELDS))
        linked = self.client.post("/mcp/accounts/add/", {"username": self.extra.username,
                                                         "password": "extra-test-password", "next": back})
        self.assertEqual(linked["Location"], back)
        consent = self.client.get(back)
        self.assertEqual(consent.status_code, 200)
        form = consent.context["form"]
        for name in ["client_id", "redirect_uri", "response_type", "scope", "state",
                     "code_challenge", "code_challenge_method", "resource"]:
            self.assertEqual(form[name].value(), self.query[name])
        self.assertIn(self.extra, form.fields["accounts"].queryset)
        # A browser posts to the URL it was shown, which keeps the original query as is.
        original = "/oauth/authorize/?" + urlencode(self.query)
        resubmitted = self.client.post(original, {**self.query, "allow": "true", "accounts": [self.owner.pk], "default_account": ""})
        self.assertEqual(parse_qs(urlsplit(resubmitted.context["link_url"]).query)["next"][0], original)

    def test_cancel_keeps_existing_connection_tokens_and_pending_codes(self):
        self.link()
        pending = self.authorize([self.owner, self.extra])
        grant = MCPGrant.objects.get()

        def snapshot():
            grant.refresh_from_db()
            return (grant.allow_writes, grant.default_account, grant.expires_at, grant.revoked_at,
                    sorted(grant.accounts.values_list("name", flat=True)))

        before = snapshot()
        cancel = self.authorize([self.owner], writes=True, allow="")
        self.assertEqual(cancel.status_code, 302)
        answer = parse_qs(urlsplit(cancel["Location"]).query)
        self.assertEqual((answer["error"], answer["state"]), (["access_denied"], ["client-state"]))
        self.assertNotIn("code", answer)
        self.assertEqual(snapshot(), before)
        tokens = self.token(pending)
        self.assertEqual(self.authorize(allow="").status_code, 302)
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.rpc(tokens["access_token"]).status_code, 200)
        self.assertEqual(self.refresh(tokens["refresh_token"]).status_code, 200)

    def test_preapproved_clients_cannot_skip_account_consent(self):
        Application.objects.filter(pk=self.application.pk).update(skip_authorization=True)
        response = self.client.get("/oauth/authorize/", self.query)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("code=", response.get("Location", ""))
        self.assertFalse(Grant.objects.exists())
        self.assertFalse(MCPGrant.objects.exists())

    def test_inactive_or_unlinked_accounts_are_excluded_at_runtime(self):
        self.link()
        token = self.token(self.authorize([self.owner, self.extra]))["access_token"]

        def listed():
            return sorted(item["name"] for item in self.rpc(token).json()["result"]["structuredContent"]["accounts"])

        def extra_refused():
            call = self.rpc(token, params={"name": "me", "arguments": {"account": self.extra.username}})
            return call.json()["result"].get("isError", False)

        self.assertEqual(listed(), sorted([self.owner.username, self.extra.username]))
        self.extra.is_active = False
        self.extra.save()
        self.assertEqual(listed(), [self.owner.username])
        self.assertTrue(extra_refused())
        self.assertNotIn(self.extra, self.client.get("/oauth/authorize/", self.query).context["form"].fields["accounts"].queryset)
        self.extra.is_active = True
        self.extra.save()
        self.assertFalse(extra_refused())
        # A link removed outside the revoke path (for example by a race) leaves no usable grant entry.
        MCPAccountLink.objects.all().delete()
        self.assertEqual(listed(), [self.owner.username])
        self.assertTrue(extra_refused())
