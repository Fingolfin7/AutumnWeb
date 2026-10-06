// Read-only interoperability check with the official v1 client used by many MCP harnesses.
// Credential file is outside the repo: {url, token}. Never print the credential or private rows.
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const file = process.argv[2];
if (!file) throw new Error('Supply a private connector credential JSON file.');
const { url, token } = JSON.parse(await readFile(file, 'utf8'));
const modern = process.argv.includes('--modern');
const { Client } = modern ? await import('@modelcontextprotocol/client') : await import('@modelcontextprotocol/sdk/client/index.js');
const { StreamableHTTPClientTransport } = modern ? await import('@modelcontextprotocol/client') : await import('@modelcontextprotocol/sdk/client/streamableHttp.js');
const endpoint = new URL(url);
if (endpoint.protocol !== 'https:' && endpoint.hostname !== '127.0.0.1') throw new Error('Use HTTPS or loopback.');
const client = new Client({ name: 'Autumn interoperability verification', version: '1.0.0' }, modern ? { versionNegotiation: { mode: { pin: '2026-07-28' } } } : {});
const transport = new StreamableHTTPClientTransport(endpoint, { requestInit: { headers: { Authorization: `Bearer ${token}` } } });
try {
  await client.connect(transport);
  if (modern) await client.discover();
  else await client.ping();
  const catalog = await client.listTools();
  assert.ok(catalog.tools.find(tool => tool.name === 'list_accounts'));
  const selected = await client.callTool({ name: 'list_accounts', arguments: {} });
  assert.ok(!selected.isError);
  const accounts = selected.structuredContent ?? JSON.parse(selected.content[0].text);
  for (const { name, username } of accounts.accounts) {
    const identity = await client.callTool({ name: 'me', arguments: { account: name } });
    assert.ok(!identity.isError);
    const data = identity.structuredContent ?? JSON.parse(identity.content[0].text);
    assert.equal(data.user.username, username);
    assert.equal(data._autumn_account, name);
    for (const tool of ['list_projects', 'list_sessions', 'status']) {
      const args = { account: name, ...(['list_projects', 'list_sessions'].includes(tool) ? { limit: 1 } : {}) };
      const result = await client.callTool({ name: tool, arguments: args });
      assert.ok(!result.isError, `${name}: ${tool} failed`);
      assert.equal(result.structuredContent._autumn_account, name);
    }
    console.log(`${name}: identity, projects, sessions and timers passed.`);
  }
  const invalid = await client.callTool({ name: 'me', arguments: { account: 'not-authorized' } });
  assert.equal(invalid.isError, true);
  const unauthorized = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }) });
  assert.equal(unauthorized.status, 401);
  console.log(`Official MCP client (${modern ? '2026-07-28' : 'legacy'}): discovery, ${catalog.tools.length} tools, account isolation and anonymous denial passed.`);
} finally {
  await client.close();
}
