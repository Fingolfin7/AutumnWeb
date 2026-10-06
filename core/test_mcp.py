import hashlib
import io
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, LiveServerTestCase, TestCase, override_settings
from oauth2_provider.models import AccessToken, Application
from django.utils import timezone

from core.models import MCPAccountLink, MCPGrant, MCPGrantAccount, Projects


@override_settings(MCP_RESOURCE="http://testserver/mcp")
class MCPTests(TestCase):
    def setUp(self):
        self.kuda = User.objects.create_user(username="mcp-kuda", email="mcp-kuda@example.com")
        self.henry = User.objects.create_user(username="mcp-henry", email="mcp-henry@example.com")
        self.stranger = User.objects.create_user(username="mcp-other", email="mcp-other@example.com")
        self.token = "oauth-test-secret"
        application = Application.objects.create(name="fixture", client_type="public", authorization_grant_type="authorization-code")
        self.grant = MCPGrant.objects.create(owner=self.kuda, name="test", default_account="kuda",
                                            oauth_application=application,
                                            expires_at=timezone.now() + timedelta(days=90))
        AccessToken.objects.create(user=self.kuda, application=application, token=self.token,
                                   scope="autumn:read autumn:write", resource=["http://testserver/mcp"],
                                   expires=timezone.now() + timedelta(hours=1))
        MCPAccountLink.objects.create(owner=self.kuda, user=self.henry)
        MCPGrantAccount.objects.create(grant=self.grant, user=self.kuda, name="kuda")
        MCPGrantAccount.objects.create(grant=self.grant, user=self.henry, name="Henry")
        self.headers = {"HTTP_AUTHORIZATION": "Bearer " + self.token,
                        "HTTP_ACCEPT": "application/json, text/event-stream", "HTTP_MCP_PROTOCOL_VERSION": "2025-11-25"}

    def rpc(self, method, params=None, **headers):
        return self.client.post("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}),
                                content_type="application/json", **{**self.headers, **headers})

    def tool(self, name, args=None):
        return self.rpc("tools/call", {"name": name, "arguments": args or {}}).json()["result"]

    def test_authentication_revocation_expiry_and_inactive_users(self):
        for bad in ["", "Bearer wrong", "Token " + self.token]:
            self.assertEqual(self.rpc("tools/list", HTTP_AUTHORIZATION=bad).status_code, 401)
        self.client.force_login(self.kuda)
        self.assertEqual(self.rpc("tools/list", HTTP_AUTHORIZATION="").status_code, 401)
        for field, value in [("revoked_at", timezone.now()), ("expires_at", timezone.now() - timedelta(seconds=1))]:
            old = getattr(self.grant, field)
            setattr(self.grant, field, value)
            self.grant.save()
            self.assertEqual(self.rpc("tools/list").status_code, 401)
            setattr(self.grant, field, old)
            self.grant.save()
        self.kuda.is_active = False
        self.kuda.save()
        self.assertEqual(self.rpc("tools/list").status_code, 401)

    def test_standard_lifecycle_and_transport(self):
        for version in ["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]:
            r = self.rpc("initialize", {"protocolVersion": version, "clientInfo": {"name": "Claude", "version": "1"}, "capabilities": {}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["result"]["protocolVersion"], "2025-11-25" if version == "2026-07-28" else version)
            self.assertNotIn("Mcp-Session-Id", r)
        self.assertEqual(self.rpc("ping").json()["result"], {})
        notice = self.client.post("/mcp", json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), content_type="application/json", **self.headers)
        self.assertEqual(notice.status_code, 202)
        self.assertEqual(notice.content, b"")
        self.assertEqual(self.client.get("/mcp", **self.headers).status_code, 405)
        self.assertEqual(self.client.delete("/mcp", **self.headers).status_code, 405)
        self.assertEqual(self.rpc("ping", HTTP_MCP_PROTOCOL_VERSION="unknown").status_code, 400)
        self.assertEqual(self.rpc("ping", HTTP_ACCEPT="text/event-stream").status_code, 406)
        self.assertEqual(self.rpc("ping", HTTP_ORIGIN="https://evil.example").status_code, 403)
        self.assertEqual(self.rpc("ping", HTTP_ORIGIN="http://[").status_code, 403)
        self.assertEqual(self.rpc("ping", HTTP_ORIGIN="http://testserver").status_code, 200)
        self.assertEqual(self.rpc("unknown").json()["error"]["code"], -32601)
        malformed = self.client.post("/mcp", "[1,2]", content_type="application/json", **self.headers)
        self.assertEqual(malformed.status_code, 400)
        oversized = self.client.post("/mcp", "x" * (1024 * 1024 + 1), content_type="application/json", **self.headers)
        self.assertEqual(oversized.status_code, 413)

    def test_modern_metadata_discovery_and_conflicts(self):
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {}}
        for method, params in [("server/discover", {}), ("tools/list", {}), ("tools/call", {"name": "me", "arguments": {"account": "Henry"}})]:
            output = self.rpc(method, {**params, "_meta": meta}, HTTP_MCP_PROTOCOL_VERSION="2026-07-28", HTTP_MCP_METHOD=method, HTTP_MCP_NAME=params.get("name", ""))
            self.assertEqual(output.status_code, 200)
            self.assertEqual(output.json()["result"]["resultType"], "complete")
            if method == "tools/call":
                self.assertEqual(output.json()["result"]["structuredContent"]["_autumn_account"], "Henry")
        conflict = self.rpc("tools/list", {"_meta": meta}, HTTP_MCP_PROTOCOL_VERSION="2026-07-28", HTTP_MCP_METHOD="tools/call")
        self.assertEqual(conflict.status_code, 400)
        unsupported = self.rpc("server/discover", {"_meta": {**meta, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}}, HTTP_MCP_PROTOCOL_VERSION="2099-01-01", HTTP_MCP_METHOD="server/discover")
        self.assertEqual(unsupported.json()["error"]["code"], -32022)
        self.assertEqual(unsupported.json()["error"]["data"]["supported"], ["2026-07-28"])

    def test_discovery_and_read_only_scope(self):
        tools = self.rpc("tools/list").json()["result"]["tools"]
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))
        self.assertNotIn(self.token, json.dumps(tools))
        self.assertTrue(self.tool("create_project", {"name": "denied"})["isError"])
        self.assertFalse(Projects.objects.exists())
        self.grant.allow_writes = True
        self.grant.save()
        self.assertEqual(len(self.rpc("tools/list").json()["result"]["tools"]), 47)

    def test_per_call_account_isolation_and_permissions(self):
        accounts = self.tool("list_accounts")["structuredContent"]
        self.assertEqual([a["name"] for a in accounts["accounts"]], ["kuda", "Henry"])
        for alias, user in [("kuda", self.kuda), ("henry", self.henry), ("kuda", self.kuda)]:
            value = self.tool("me", {"account": alias})["structuredContent"]
            self.assertEqual(value["user"]["id"], user.id)
        self.assertEqual(self.tool("me")["structuredContent"]["_autumn_account"], "kuda")
        self.assertTrue(self.tool("me", {"account": "mcp-other"})["isError"])
        foreign = Projects.objects.create(user=self.stranger, name="private")
        own = Projects.objects.create(user=self.kuda, name="own")
        self.assertTrue(self.tool("get_project", {"project_id": foreign.id})["isError"])
        self.assertTrue(self.tool("get_project", {"account": "Henry", "project_id": own.id})["isError"])
        self.assertEqual(self.tool("get_project", {"project_id": own.id})["structuredContent"]["name"], "own")
        self.henry.is_active = False
        self.henry.save()
        self.assertTrue(self.tool("me", {"account": "Henry"})["isError"])

    def test_validated_writes_and_filters_use_existing_api(self):
        self.grant.allow_writes = True
        self.grant.save()
        self.assertTrue(self.tool("create_project", {"name": "bad", "invented": True})["isError"])
        self.assertTrue(self.tool("get_project", {"project_id": "../../admin"})["isError"])
        project = self.tool("create_project", {"name": "created", "account": "Henry"})["structuredContent"]
        saved = Projects.objects.get(pk=project["id"])
        self.assertEqual(saved.user, self.henry)
        rows = self.tool("list_projects", {"search": "created", "account": "Henry", "limit": 1})["structuredContent"]
        self.assertEqual(rows["projects"][0]["id"], saved.id)
        self.assertEqual(rows["count"], 1)
        self.assertTrue(self.tool("update_project", {"project_id": saved.id, "account": "kuda", "name": "stolen"})["isError"])
        result = self.tool("delete_project", {"project_id": saved.id, "account": "Henry"})
        self.assertFalse(result.get("isError", False))
        self.assertFalse(Projects.objects.filter(pk=saved.id).exists())

    def test_bearer_endpoint_is_csrf_independent(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), content_type="application/json", **self.headers).status_code, 200)

    def test_management_listing_and_revocation_do_not_expose_tokens(self):
        listing = io.StringIO()
        call_command("mcp_grant", "list", stdout=listing)
        self.assertNotIn(self.token, listing.getvalue())
        call_command("mcp_grant", "revoke", grant_id=self.grant.id, stdout=io.StringIO())
        self.assertEqual(self.rpc("tools/list").status_code, 401)


class MCPOfficialClientTests(LiveServerTestCase):
    host = "127.0.0.1"

    def test_official_client_connects_and_reads_both_accounts(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        from django.conf import settings

        root = Path(settings.BASE_DIR) / "integrations/mcp"
        if not shutil.which("node") or not (root / "node_modules/@modelcontextprotocol/sdk").exists():
            self.skipTest("Run npm ci in integrations/mcp for the official client check")
        users = [User.objects.create_user(username=name, email=name + "@example.com") for name in ["client-kuda", "client-henry"]]
        resource = self.live_server_url + "/mcp"
        resource_override = override_settings(MCP_RESOURCE=resource)
        resource_override.enable()
        self.addCleanup(resource_override.disable)
        token = "oauth-fixture-secret"
        application = Application.objects.create(name="SDK fixture", client_type="public", authorization_grant_type="authorization-code")
        grant = MCPGrant.objects.create(owner=users[0], name="client fixture", default_account="kuda",
                                       oauth_application=application,
                                       expires_at=timezone.now() + timedelta(days=1))
        MCPAccountLink.objects.create(owner=users[0], user=users[1])
        AccessToken.objects.create(user=users[0], application=application, token=token, scope="autumn:read",
                                   resource=[resource], expires=timezone.now() + timedelta(hours=1))
        for alias, user in zip(["kuda", "Henry"], users):
            MCPGrantAccount.objects.create(grant=grant, user=user, name=alias)
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "fixture.json"
            credential.write_text(json.dumps({"url": self.live_server_url + "/mcp", "token": token}))
            for flags in [[], ["--modern"]]:
                checked = subprocess.run(["node", "scripts/verify-remote.mjs", str(credential), *flags], cwd=root,
                                         capture_output=True, text=True, timeout=45)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertIn("Official MCP client", checked.stdout)
