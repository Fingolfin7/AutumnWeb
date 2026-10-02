# Autumn MCP on Sites

Private, owner-only remote MCP tools backed by Autumn API v2. The Python MCP entry point in the parent repo remains available for local clients.

The Worker exposes all 46 operations in the checked-in OpenAPI contract plus `list_accounts`: projects, subprojects, sessions, timers, contexts, tags, reports, commitments, export and import. Names and inputs are generated from `openapi-v2.yaml`. Tools use native API v2 numeric IDs and response shapes, rather than the older compact facade. Search projects before writing; use returned IDs. Session reads support `include=note`, and list responses preserve pagination.

Every API tool accepts optional `account`, such as `kuda` or `Henry`. Omission uses `AUTUMN_DEFAULT_ACCOUNT`. Call `list_accounts` to discover configured names. Every API response includes `_autumn_account`. Explicit account selection is isolated per request, supports concurrent comparisons, and never changes the local CLI account or a shared server setting. Resolve IDs separately in each account. Unknown account names fail without falling back to another account.

Run `npm ci`, `npm run build`, then `npm test`. Build regenerates `src/operations.json` and bundles the official MCP SDK for Cloudflare Workers at `dist/server/index.js`. Both modern MCP and legacy Streamable HTTP traffic are supported by the SDK's per-request handler. No local MCP configuration is required.

ChatGPT discovery can advertise MCP `2026-07-28` without the redundant `Mcp-Method` and `Mcp-Name` routing headers. The Worker supplies missing routing headers from the validated JSON-RPC request, preserving explicit headers so mismatches still fail. Traditional wire-format clients advertising that revision negotiate `2025-11-25`. These compatibility paths preserve the same owner authorization and schema validation.

Refresh the schema from the parent AutumnWeb repository when its API changes, rebuild, test and publish a new Sites version. Manage runtime settings through Sites: secret `AUTUMN_ACCOUNTS_JSON`, `AUTUMN_DEFAULT_ACCOUNT`, and `AUTUMN_OWNER_EMAIL`. The JSON maps names to `{base, token, username, timezone}`; see `.env.example` for the shape. Credentials never enter the source tree or browser. Calls require both Sites identity headers and the owner's verified email. Do not broaden the Site audience without first implementing separate Autumn credentials and authorization for each user.

Mutations are never automatically retried. Conflicts and API errors are returned as MCP tool errors. Optional `expected_version` is sent as `If-Match`. Timestamps should include timezone offsets. Durations remain in minutes.
