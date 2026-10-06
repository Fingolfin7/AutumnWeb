# Autumn MCP launch and consolidation

Autumn MCP first launched privately on ChatGPT Sites on October 3, 2026. The original owner-only Worker used configured API credentials for two accounts. A separate Django endpoint was later added for Claude.

On October 6, 2026, these implementations were consolidated into the Autumn application's single OAuth MCP endpoint:

`https://autumn-lg0b.onrender.com/mcp`

ChatGPT and Claude now use the same server and sign-in flow. Every user signs into Autumn and explicitly chooses their own accounts and permissions. Additional accounts require signing in to them; no personal/work accounts or API keys are preset. The local Autumn CLI remains available for CLI workflows.

The former Sites deployment is retained privately as a connection guide after migration. It no longer hosts an MCP server or stores Autumn account credentials. Its old plugin must be replaced by a custom MCP plugin connected to the shared endpoint.

See [client setup and account management](mcp-clients.md). Server code lives in `core/mcp.py` and `core/mcp_oauth.py`; the generated API-v2 contract and interoperability clients live in [`integrations/mcp`](../integrations/mcp/README.md).

The original launch exposed 46 API operations plus `list_accounts`. The shared server preserves these tools, per-request account selection, API ownership checks, minute-based durations, timezone handling, pagination, and compatibility with both traditional and modern MCP discovery.
