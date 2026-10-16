# Shared Autumn MCP contract

The single remote server runs inside Autumn at `https://autumn-lg0b.onrender.com/mcp`, implemented by `core/mcp.py`. Authentication and account consent use `core/mcp_oauth.py` and django-oauth-toolkit. This directory contains no second server and no account credentials.

- `scripts/build.mjs`: generates the API tools in `src/operations.json` from the repository's `openapi-v2.yaml`.
- `scripts/verify-remote.mjs`: harmless remote reads using the official MCP v1 or v2 client and a privately supplied OAuth access token. Add `--modern` to pin `2026-07-28`.

Run `npm ci`, then `npm run build` to refresh the generated contract. Run the Django `core.test_mcp` and `core.test_mcp_oauth` suites from the repository root for authentication, account isolation, permissions, transport and real official-client checks.

See [client setup](../../docs/mcp-clients.md).
