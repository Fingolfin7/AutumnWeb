import test from 'node:test';
import assert from 'node:assert/strict';
import { Miniflare } from 'miniflare';

test('bundled Worker performs authenticated reads for both accounts in workerd', async () => {
  const visited = [];
  const runtime = new Miniflare({
    modules: true, compatibilityDate: '2026-08-06', scriptPath: 'dist/server/index.js',
    bindings: { AUTUMN_OWNER_EMAIL: 'owner@example.com', AUTUMN_DEFAULT_ACCOUNT: 'kuda', AUTUMN_ACCOUNTS_JSON: JSON.stringify({ kuda: { base: 'https://autumn.example', token: 'kuda-token' }, Henry: { base: 'https://autumn.example', token: 'henry-token' } }) },
    outboundService: request => {
      const authorization = request.headers.get('authorization');
      visited.push({ url: request.url, authorization });
      return Response.json({ api_version: '2', user: { username: authorization === 'Token henry-token' ? 'Henry' : 'kuda' } });
    },
  });
  try {
    for (const account of ['kuda', 'Henry']) {
      const response = await runtime.dispatchFetch('https://site.example/mcp', { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream', 'mcp-protocol-version': '2025-11-25', 'oai-authenticated-user-id': 'owner', 'oai-authenticated-user-email': 'owner@example.com' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'me', arguments: { account } } }) });
      assert.equal(response.status, 200);
      const text = await response.text();
      const payload = response.headers.get('content-type')?.includes('event-stream') ? JSON.parse(text.split('\n').find(line => line.startsWith('data: ')).slice(6)) : JSON.parse(text);
      assert.ok(!payload.result.isError, JSON.stringify(payload.result.structuredContent));
      assert.equal(payload.result.structuredContent.user.username, account);
      assert.equal(payload.result.structuredContent._autumn_account, account);
    }
    assert.equal(visited.length, 2);
    assert.ok(visited.every(request => request.url === 'https://autumn.example/api/v2/me/'));
  } finally { await runtime.dispose(); }
});
