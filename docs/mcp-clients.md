# Autumn MCP clients

Autumn has two secure remote MCP connections using the same API-v2 tool contract:

| Client | Endpoint | Authentication |
| --- | --- | --- |
| ChatGPT / installed Autumn Sites plugin | `https://autumn-mcp.fingolfin7.chatgpt.site/mcp` | Existing Sites-managed OAuth and owner identity |
| Claude, clients supporting fixed request headers | `https://autumn-lg0b.onrender.com/mcp` | Dedicated Autumn MCP bearer credential |

The Sites audience and owner authorization remain unchanged. Its OpenAI OAuth metadata currently advertises neither Dynamic Client Registration nor Client ID Metadata Documents. Claude detects a required pre-registered OAuth client. Do not put the Site's own sign-in client ID into Claude, copy OpenAI session tokens, spoof Sites identity headers, or use a Sites service bypass token as a user credential.

The independent endpoint runs on the existing Autumn Render service. It requires authentication for discovery and calls, offers stateless Streamable HTTP, and supports modern `2026-07-28` per-request metadata and `server/discover`, alongside `2025-03-26`, `2025-06-18`, or `2025-11-25` initialization. Newer traditional initialization requests negotiate `2025-11-25`. Modern routing-header conflicts fail; results identify the server and discovery caches are private with zero TTL. GET and DELETE return 405 because it provides no persistent SSE stream or session. JSON responses preserve API-v2 fields and errors. Anonymous callers, expired/revoked credentials, inactive users, invalid origins, unknown accounts and invalid arguments fail closed.

## Create and revoke a credential

An Autumn deployment administrator creates a separate credential for each client. This privileged command explicitly binds aliases to existing users; it must not be exposed as an unrestricted web API.

```powershell
python manage.py mcp_grant create --owner kuda --name Claude --account kuda=kuda --account Henry=Henry --default-account kuda
```

The command returns a token once. Store the output outside the repository in a private file or password manager. The database stores only its SHA-256 digest and authorized account bindings. Default access is read-only, expires after 90 days, and omits mutation tools. Use `--allow-writes` only for a client intended to have the same mutation capabilities as the Sites connector. `--expires-days` accepts 1–365. Account IDs and ownership checks are enforced by the existing API views; each request selects an account independently. Existing Autumn API keys are not transmitted to the MCP client.

```powershell
python manage.py mcp_grant list --owner kuda
python manage.py mcp_grant revoke --grant-id <id>
```

Revocation takes effect on the next HTTP request. Deleting/deactivating a bound user removes that account's access; deactivating the grant owner denies the entire connection. Connector credentials cannot authenticate to ordinary Autumn API endpoints.

## Claude

In Customize → Connectors → Add custom connector, use the independent endpoint. Select **No sign-in** (Claude's label for fixed-header credentials, not anonymous server access). Add a request header named `Authorization` with value `Bearer <dedicated MCP token>`. Claude stores the value encrypted. Do not paste the secret into a chat. Add the connector and enable it for a new conversation. Verify with `list_accounts`, then `me` explicitly for each account. Remote connectors are associated with the Claude account and work in Claude Desktop as well as the web; the network connection originates from Anthropic.

## Other harnesses

Use Streamable HTTP and send the bearer header on every request. For clients with environment-backed headers, keep the token out of checked-in configuration. OAuth-only clients cannot use the independent endpoint's fixed-header authentication; the existing Sites plugin remains the supported ChatGPT route. The Python stdio entry point and local Autumn CLI remain available.

Run the independent verification client from `integrations/sites-mcp`:

```powershell
npm ci
node scripts/verify-remote.mjs C:/path/outside/repository/credential.json
node scripts/verify-remote.mjs C:/path/outside/repository/credential.json --modern
```

The private file contains `{"url":"https://autumn-lg0b.onrender.com/mcp","token":"<secret>"}`. Verification uses the official MCP v1 client (legacy) and v2 client pinned to `2026-07-28`, with harmless reads for each available account; it prints checks, not private records or credentials. Django tests exercise both real clients against a live test server, API dispatch, account permissions, transport negotiation, scoped writes, expiry and revocation. Keep the existing Sites/workerd tests for ChatGPT compatibility.

References: [Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
