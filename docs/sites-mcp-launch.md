# Autumn MCP on ChatGPT Sites

Launch date: October 3, 2026.

Autumn's remote MCP server is hosted privately on ChatGPT Sites. It uses Autumn
API v2 and exposes 46 API operations plus `list_accounts`: projects,
subprojects, saved sessions, live timers, contexts, tags, reports, commitments,
export and import. The existing packaged Python MCP server remains the local
client entry point.

## Connection and accounts

The owner's deployment is [Autumn MCP](https://autumn-mcp.fingolfin7.chatgpt.site).
Its MCP endpoint is `/mcp`. In ChatGPT, open Plugins → Personal → Created by you
and install or connect Autumn MCP. Start a new conversation and select the
plugin after reconnecting or refreshing its tools.

Call `list_accounts` to discover configured names. Every API tool accepts
optional `account`; omission uses the configured default. Examples:

- `me(account="kuda")`
- `list_sessions(account="Henry", start_date="2026-10-01", end_date="2026-12-31", include="note")`

Each response includes `_autumn_account`. Account selection belongs to each
request; it does not change shared server state or the local CLI's selected
account. Resolve project, session, subproject, context and tag IDs separately
for each account. Unknown names fail without falling back to another account.
Use `total`, `count`, `limit` and `offset` to retrieve the complete requested
history. Durations remain in minutes and timestamps should carry an explicit
timezone offset.

## Runtime configuration

Source: [`integrations/sites-mcp`](../integrations/sites-mcp/README.md).

Sites stores these runtime values:

- `AUTUMN_ACCOUNTS_JSON`: a secret mapping account names to their Autumn server,
  API token, username and timezone.
- `AUTUMN_DEFAULT_ACCOUNT`: the account used when a call omits `account`.
- `AUTUMN_OWNER_EMAIL`: the verified ChatGPT email permitted to use the tools.

The account JSON structure is documented with empty tokens in
[`.env.example`](../integrations/sites-mcp/.env.example). Every data-bearing
request requires both the trusted Sites user identity and the permitted email.
Discovery is free of private data. Source, browser pages and account-discovery
responses contain no API tokens. A Sites service credential does not substitute
for the owner's identity.

## Discovery compatibility and verification

The first ChatGPT discovery attempt returned HTTP 400: the client advertised
MCP `2026-07-28` without the routing headers required by the SDK. The Worker now
supplies missing `Mcp-Method` and `Mcp-Name` from the JSON-RPC request. It
preserves explicit header values so conflicts still fail validation.
Traditional wire-format clients advertising that revision negotiate the
supported `2025-11-25` format. Owner authorization is preserved on both paths.

Regression coverage checks both discovery formats, missing routing headers,
explicit routing conflicts, account isolation, rejected unknown accounts,
schema validation, note and pagination filters, optimistic concurrency,
credential redaction, and uncertain writes without automatic retries. The
bundled Worker also passed live identity, project, session and timer reads for
both configured accounts. Writes were checked with mock API responses.

For future updates, refresh the OpenAPI contract from AutumnWeb, run `npm ci`,
`npm run build` and `npm test`, then publish through the same Sites project.
After publication, verify a read-only tool through the connected ChatGPT plugin;
a successful deployment alone does not prove client tool discovery.
