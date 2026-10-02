// Read-only verification against the active local Autumn account. No credentials are logged.
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { parse } from 'yaml';
import worker from '../dist/server/index.js';

const config = parse(await readFile(join(homedir(), '.autumn', 'config.yaml'), 'utf8'));
const owner = config.accounts.kuda;
const configured = Object.fromEntries(Object.entries(config.accounts).map(([name, entry]) => [name === 'account' ? 'Henry' : name, { base: entry.base_url ?? config.base_url, token: entry.api_key, username: entry.username ?? (name === 'account' ? 'Henry' : name) }]));
const env = { AUTUMN_ACCOUNTS_JSON: JSON.stringify(configured), AUTUMN_DEFAULT_ACCOUNT: 'kuda', AUTUMN_OWNER_EMAIL: owner.email };
for (const account of Object.keys(configured)) for (const [name, args] of [['me', {}], ['list_projects', { limit: 1 }], ['list_sessions', { limit: 1, include: 'note' }], ['status', {}]]) {
  const request = new Request('https://local.example/mcp', { method: 'POST', headers: { accept: 'application/json, text/event-stream', 'content-type': 'application/json', 'mcp-protocol-version': '2025-11-25', 'oai-authenticated-user-id': 'local-verification', 'oai-authenticated-user-email': owner.email }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: { ...args, account } } }) });
  const response = await worker.fetch(request, env);
  const text = await response.text();
  const payload = response.headers.get('content-type')?.includes('event-stream') ? JSON.parse(text.split('\n').find(line => line.startsWith('data: ')).slice(6)) : JSON.parse(text);
  if (payload.error || payload.result?.isError) throw new Error(`${name} failed: ${JSON.stringify(payload.error ?? payload.result?.structuredContent)}`);
  const data = payload.result.structuredContent;
  if (name === 'me' && data.user?.username !== configured[account].username) throw new Error('Unexpected Autumn account');
  if (data._autumn_account !== account) throw new Error('Incorrect account label');
  console.log(JSON.stringify({ tool: name, ok: true, account, response_fields: Object.keys(data) }));
}
