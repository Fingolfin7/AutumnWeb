import test from 'node:test';
import assert from 'node:assert/strict';
import { createWorker, callAutumn } from './worker.mjs';
import operations from './operations.json' with { type: 'json' };

const token = 'test-token';
const env = { AUTUMN_ACCOUNTS_JSON: JSON.stringify({ kuda: { base: 'https://autumn.example', token, username: 'kuda' }, Henry: { base: 'https://work-autumn.example', token: 'henry-token', username: 'Henry' } }), AUTUMN_DEFAULT_ACCOUNT: 'kuda', AUTUMN_OWNER_EMAIL: 'owner@example.com' };
function request(method, params = {}, owner = true, protocol = '2025-11-25') {
  if (protocol === '2026-07-28') params = { ...params, _meta: { 'io.modelcontextprotocol/protocolVersion': protocol, 'io.modelcontextprotocol/clientInfo': { name: 'test', version: '1' }, 'io.modelcontextprotocol/clientCapabilities': {} } };
  const headers = { 'content-type': 'application/json', accept: 'application/json, text/event-stream', 'mcp-protocol-version': protocol };
  if (protocol === '2026-07-28') { headers['mcp-method'] = method; if (params.name) headers['mcp-name'] = params.name; }
  if (owner) Object.assign(headers, { 'oai-authenticated-user-id': 'site-owner', 'oai-authenticated-user-email': env.AUTUMN_OWNER_EMAIL });
  return new Request('https://site.example/mcp', { method: 'POST', headers, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
}
async function payload(response) {
  const body = await response.text();
  return response.headers.get('content-type')?.includes('event-stream') ? JSON.parse(body.split('\n').find(line => line.startsWith('data: ')).slice(6)) : JSON.parse(body);
}
test('legacy initialization and discovery expose the complete schema without credentials', async () => {
  const worker = createWorker(() => { throw new Error('Discovery must not call Autumn'); });
  const init = await payload(await worker.fetch(request('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'test', version: '1' } }, false), env));
  assert.equal(init.result.serverInfo.name, 'Autumn');
  const discovery = await payload(await worker.fetch(request('tools/list', {}, false), env));
  assert.equal(discovery.result.tools.length, 47);
  assert.ok(!JSON.stringify(discovery).includes(token));
  assert.ok(discovery.result.tools.find(tool => tool.name === 'list_projects').annotations.readOnlyHint);
  assert.ok(discovery.result.tools.find(tool => tool.name === 'delete_project').annotations.destructiveHint);
});
test('modern protocol supports discovery and owner tool calls', async () => {
  const worker = createWorker(async () => Response.json({ user: { username: 'owner' }, api_version: '2' }));
  const discovery = await payload(await worker.fetch(request('tools/list', {}, true, '2026-07-28'), env));
  assert.equal(discovery.result.tools.length, 47);
  const call = await payload(await worker.fetch(request('tools/call', { name: 'me', arguments: {} }, true, '2026-07-28'), env));
  assert.equal(call.result.structuredContent.user.username, 'owner');
});
test('ChatGPT modern discovery and calls work without routing headers', async () => {
  const worker = createWorker(async () => Response.json({ user: { username: 'Henry' } }));
  for (const [method, params] of [['tools/list', {}], ['tools/call', { name: 'me', arguments: { account: 'Henry' } }]]) {
    const req = request(method, params, true, '2026-07-28');
    req.headers.delete('mcp-method');
    req.headers.delete('mcp-name');
    const response = await worker.fetch(req, env);
    assert.equal(response.status, 200);
    const output = await payload(response);
    if (method === 'tools/list') assert.equal(output.result.tools.length, 47);
    else assert.equal(output.result.structuredContent._autumn_account, 'Henry');
  }
});
test('traditional wire format advertising the modern version negotiates legacy discovery', async () => {
  const worker = createWorker(() => { throw new Error('Discovery must not call Autumn'); });
  const init = request('initialize', { protocolVersion: '2026-07-28', capabilities: {}, clientInfo: { name: 'test', version: '1' } }, false);
  init.headers.set('mcp-protocol-version', '2026-07-28');
  const initialized = await payload(await worker.fetch(init, env));
  assert.equal(initialized.result.protocolVersion, '2025-11-25');
  const discovery = request('tools/list', {}, false);
  discovery.headers.set('mcp-protocol-version', '2026-07-28');
  const output = await payload(await worker.fetch(discovery, env));
  assert.equal(output.result.tools.length, 47);
});
test('explicit modern routing conflicts remain rejected', async () => {
  const worker = createWorker(() => { throw new Error('Must not reach Autumn'); });
  const req = request('tools/list', {}, true, '2026-07-28');
  req.headers.set('mcp-method', 'tools/call');
  const output = await payload(await worker.fetch(req, env));
  assert.ok(output.error);
});
test('anonymous, different owner, missing identity and service-only calls are denied', async () => {
  const worker = createWorker(() => { throw new Error('Must not reach Autumn'); });
  for (const variant of ['anonymous', 'other', 'no-id', 'service']) {
    const req = request('tools/call', { name: 'me', arguments: {} }, variant !== 'anonymous' && variant !== 'service');
    if (variant === 'other') req.headers.set('oai-authenticated-user-email', 'other@example.com');
    if (variant === 'no-id') req.headers.delete('oai-authenticated-user-id');
    if (variant === 'service') req.headers.set('OAI-Sites-Authorization', 'Bearer service-token');
    assert.equal((await worker.fetch(req, env)).status, 401);
  }
});
test('API reads preserve v2 filters, notes and pagination', async () => {
  const worker = createWorker(async (url, init) => {
    assert.equal(url.pathname, '/api/v2/sessions/');
    assert.equal(url.searchParams.get('project_ids'), '7,8');
    assert.equal(url.searchParams.get('include'), 'note');
    assert.equal(url.searchParams.get('offset'), '100');
    assert.equal(init.headers.Authorization, 'Token test-token');
    assert.equal(init.redirect, 'manual');
    return Response.json({ count: 150, limit: 100, offset: 100, results: [{ note: 'Preserved' }] });
  });
  const call = await payload(await worker.fetch(request('tools/call', { name: 'list_sessions', arguments: { project_ids: '7,8', include: 'note', offset: 100 } }), env));
  assert.equal(call.result.structuredContent.count, 150);
  assert.equal(call.result.structuredContent.results[0].note, 'Preserved');
});
test('schema validation prevents malformed writes and unknown arguments', async () => {
  const worker = createWorker(() => { throw new Error('Invalid input must not reach Autumn'); });
  for (const args of [{ project_id: 'wrong' }, { project_id: 1, invented: true }, { project_id: 1, stop_after_minutes: -3 }]) {
    const call = await payload(await worker.fetch(request('tools/call', { name: 'start', arguments: args }), env));
    assert.ok(call.result?.isError || call.error);
  }
});
test('writes preserve explicit null and concurrency versions', async () => {
  const op = operations.find(o => o.name === 'update_session');
  const output = await callAutumn(op, { session_id: 42, expected_version: 3, note: null }, env, async (url, init) => {
    assert.equal(url.pathname, '/api/v2/sessions/42');
    assert.equal(init.headers['If-Match'], '3');
    assert.equal(init.method, 'PATCH');
    assert.deepEqual(JSON.parse(init.body), { note: null });
    return Response.json({ id: 42, note: null });
  });
  assert.equal(output.structuredContent.note, null);
});
test('conflicts, empty deletes and uncertain writes are reported honestly', async () => {
  const conflict = await callAutumn(operations.find(o => o.name === 'update_session'), {}, env, async () => Response.json({ error: 'Version conflict' }, { status: 409 }));
  assert.equal(conflict.isError, true);
  const deletion = await callAutumn(operations.find(o => o.name === 'delete_session'), {}, env, async () => new Response(null, { status: 204 }));
  assert.deepEqual(deletion.structuredContent, { ok: true, _autumn_account: 'kuda' });
  let attempts = 0;
  const uncertain = await callAutumn(operations.find(o => o.name === 'track'), {}, env, async () => { attempts++; throw new Error('timeout'); });
  assert.equal(attempts, 1);
  assert.match(uncertain.structuredContent.error, /may already have succeeded/);
});
test('upstream credential reflections are redacted', async () => {
  const output = await callAutumn(operations.find(o => o.name === 'me'), {}, env, async () => Response.json({ error: 'test-token' }, { status: 400 }));
  assert.ok(!JSON.stringify(output).includes(token));
});
test('account discovery exposes names and the default without credentials', async () => {
  const worker = createWorker(() => { throw new Error('Discovery must not call Autumn'); });
  const output = await payload(await worker.fetch(request('tools/call', { name: 'list_accounts', arguments: {} }), env));
  assert.equal(output.result.structuredContent.default_account, 'kuda');
  assert.deepEqual(output.result.structuredContent.accounts.map(account => account.name), ['kuda', 'Henry']);
  assert.ok(!JSON.stringify(output).includes('henry-token'));
});
test('explicit accounts isolate concurrent reads and writes without changing the default', async () => {
  const worker = createWorker(async (url, init) => {
    const isHenry = url.origin === 'https://work-autumn.example';
    assert.equal(init.headers.Authorization, `Token ${isHenry ? 'henry-token' : token}`);
    if (init.body) assert.ok(!Object.hasOwn(JSON.parse(init.body), 'account'));
    return Response.json({ account_identity: isHenry ? 'Henry' : 'kuda' });
  });
  const requests = [
    ['me', { account: 'Henry' }], ['me', { account: 'kuda' }],
    ['start', { account: 'henry', project_id: 2 }], ['me', {}],
  ];
  const outputs = await Promise.all(requests.map(async ([name, args]) => payload(await worker.fetch(request('tools/call', { name, arguments: args }), env))));
  assert.deepEqual(outputs.map(output => output.result.structuredContent._autumn_account), ['Henry', 'kuda', 'Henry', 'kuda']);
  assert.deepEqual(outputs.map(output => output.result.structuredContent.account_identity), ['Henry', 'kuda', 'Henry', 'kuda']);
});
test('unknown accounts do not fall back to the default', async () => {
  const worker = createWorker(() => { throw new Error('Unknown accounts must not reach Autumn'); });
  const output = await payload(await worker.fetch(request('tools/call', { name: 'me', arguments: { account: 'unknown' } }), env));
  assert.equal(output.result.isError, true);
  assert.match(output.result.structuredContent.error, /Unknown Autumn account/);
});
test('redirects are rejected without forwarding credentials to another origin', async () => {
  let calls = 0;
  const output = await callAutumn(operations.find(o => o.name === 'me'), {}, env, async (url, init) => {
    calls++;
    assert.equal(url.origin, 'https://autumn.example');
    assert.equal(init.redirect, 'manual');
    return new Response(null, { status: 302, headers: { location: 'https://other.example/' } });
  });
  assert.equal(calls, 1);
  assert.equal(output.isError, true);
  assert.match(output.structuredContent.error, /unexpected redirect/);
});
test('network exceptions expose useful causes without tokens or query values', async () => {
  const output = await callAutumn(operations.find(o => o.name === 'me'), {}, env, async () => { throw new TypeError('Failed test-token at https://autumn.example/api/v2/me/?note_snippet=private-note'); });
  assert.equal(output.isError, true);
  assert.equal(output.structuredContent.cause.type, 'TypeError');
  assert.ok(!JSON.stringify(output).includes(token));
  assert.ok(!JSON.stringify(output).includes('private-note'));
});
