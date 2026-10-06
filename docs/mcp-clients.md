# Autumn MCP clients

Autumn has one remote MCP server for ChatGPT, Claude, and other OAuth-capable clients:

`https://autumn-lg0b.onrender.com/mcp`

It runs inside the existing Autumn application. There are no preset personal or work accounts and no server-wide account switch. Each connection belongs to the signed-in Autumn user and has its own chosen accounts and permissions.

## Connect

In ChatGPT, create a custom MCP plugin with the URL above and OAuth authentication. Leave static client credentials empty; client metadata or automatic registration is supported. Install/connect the resulting plugin.

In Claude, add a custom connector using the same URL, select OAuth sign-in, and use Claude's published client identity or automatic registration. Do not add a fixed Authorization header.

Both clients open Autumn's normal sign-in page. An existing signed-in session can be used. Choose at least one account, a default account, and whether the client may change records. Access is read-only by default and lasts up to 90 days. Sign in again to renew it.

To add another account, choose **Sign in to another Autumn account** during consent, or use **Profile → Manage MCP connections**. Enter that account's Autumn username/email and password. This proves access without changing the primary session or saving the password/API key. Return to consent and select the additional account. A linked account is available to choose; it is not automatically shared with every client.

Manage and revoke clients or unlink accounts at [MCP connections](https://autumn-lg0b.onrender.com/mcp/connections/). Unlinking revokes affected connections immediately; reconnect them to choose the remaining accounts. Another Autumn user sees only their own account and accounts they personally signed into.

## Tools and account selection

Call `list_accounts` first. Every API tool accepts an optional `account` name returned by that tool. Omission uses the connection's chosen default. Set it explicitly when comparing accounts; an unknown/unavailable account never falls back to another one. Resolve numeric IDs in the same account. Responses identify `_autumn_account`; durations are minutes, timestamps include timezone offsets, and paginated reads expose count/total.

Read-only consent hides mutation tools and rejects write calls. With explicit write consent, the server exposes 46 API-v2 operations plus `list_accounts`. Existing API ownership checks remain enforced.

## Implementation and security

The only server implementation is `core/mcp.py`, with self-service consent in `core/mcp_oauth.py`. `integrations/mcp` contains the generated API-v2 tool contract and official-client verification, not another server. Local Autumn CLI workflows remain independent.

OAuth is provided by django-oauth-toolkit 3.4.1: authorization code with S256 PKCE, automatic registration and client metadata, resource-bound tokens, issuer validation, one-hour access tokens, rotating refresh tokens with replay protection, and hashed token storage. Account consent and account linking require session authentication and CSRF protection. Discovery metadata is public; data and MCP tool discovery require a valid bearer token and active user consent. The MCP endpoint does not accept browser session cookies as authentication.

Transport supports modern `2026-07-28` per-request metadata alongside traditional initialization revisions `2025-03-26`, `2025-06-18`, and `2025-11-25`. Missing optional routing headers are derived from the validated request, while conflicting supplied headers fail. Requests and discovery are stateless; GET/DELETE return 405, private discovery has zero TTL, and uncertain writes are never retried automatically.

## Verification

Run `python manage.py test core.test_mcp core.test_mcp_oauth` for real OAuth exchange, account isolation, proof of account access, read/write consent, PKCE/code replay, refresh replay, revocation, CSRF and official MCP v1/v2 client checks. Install the verification clients with `npm ci` in `integrations/mcp`.

The optional `scripts/verify-remote.mjs` consumes a private file outside the repository containing a current OAuth access token and URL. It makes harmless identity/project/session/timer reads and prints check results rather than private rows or tokens. Never paste credentials into chats or commit them.

References: [OpenAI MCP authentication](https://developers.openai.com/plugins/build/auth), [django-oauth-toolkit security settings](https://django-oauth-toolkit.readthedocs.io/en/3.4.1/settings.html).
