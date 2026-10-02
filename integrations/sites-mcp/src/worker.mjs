import { McpServer, createMcpHandler, fromJsonSchema } from '@modelcontextprotocol/server';
import { CfWorkerJsonSchemaValidator } from '@modelcontextprotocol/server/validators/cf-worker';
import operations from './operations.json' with { type: 'json' };

const validator = new CfWorkerJsonSchemaValidator();
const inputs = new Map(operations.map(op => [op.name, fromJsonSchema(op.inputSchema, validator)]));
async function readMcpBody(request) {
  const reader = request.clone().body?.getReader();
  if (!reader) throw new Error('Missing body');
  const chunks = [];
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 1024 * 1024) { void reader.cancel(); throw new Error('Request too large'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const body = JSON.parse(new TextDecoder().decode(bytes));
  if (!body || Array.isArray(body) || typeof body !== 'object') throw new Error('Invalid JSON-RPC object');
  return body;
}
function compatibleMcpRequest(request, body) {
  if (request.headers.get('mcp-protocol-version') !== '2026-07-28') return request;
  const headers = new Headers(request.headers);
  const modernEnvelope = body.params?._meta?.['io.modelcontextprotocol/protocolVersion'];
  if (modernEnvelope) {
    // ChatGPT may supply a modern envelope without the redundant routing headers.
    // Preserve explicit headers so the SDK still rejects conflicting values.
    if (!headers.has('mcp-method') && typeof body.method === 'string') headers.set('mcp-method', body.method);
    if (!headers.has('mcp-name') && typeof body.params?.name === 'string') headers.set('mcp-name', body.params.name);
  } else {
    // Traditional initialize/tools/list clients can advertise the modern revision
    // while retaining the older wire format. Negotiate the supported legacy format.
    headers.set('mcp-protocol-version', '2025-11-25');
    if (body.method === 'initialize' && body.params?.protocolVersion === '2026-07-28') body = { ...body, params: { ...body.params, protocolVersion: '2025-11-25' } };
  }
  headers.delete('content-length');
  return new Request(request.url, { method: request.method, headers, body: JSON.stringify(body), signal: request.signal });
}
function authorized(request, env) {
  const email = request.headers.get('oai-authenticated-user-email');
  return Boolean(env.AUTUMN_OWNER_EMAIL && request.headers.get('oai-authenticated-user-id') && email && email.toLowerCase() === env.AUTUMN_OWNER_EMAIL.toLowerCase());
}
function result(value, isError = false) {
  return { content: [{ type: 'text', text: JSON.stringify(value) }], structuredContent: value, ...(isError ? { isError: true } : {}) };
}
function accounts(env) {
  try {
    const configured = JSON.parse(env.AUTUMN_ACCOUNTS_JSON);
    if (!configured || Array.isArray(configured) || typeof configured !== 'object' || !Object.keys(configured).length) throw new Error();
    return configured;
  } catch { throw new Error('Autumn accounts are not configured.'); }
}
function accountConfig(args, env) {
  const configured = accounts(env);
  const requested = args.account ?? env.AUTUMN_DEFAULT_ACCOUNT;
  const name = Object.keys(configured).find(key => typeof requested === 'string' && key.toLowerCase() === requested.toLowerCase());
  if (!name) throw new Error('Unknown Autumn account. Use list_accounts to choose an available account.');
  const entry = configured[name];
  if (!entry.token || !entry.base) throw new Error('This Autumn account is not configured.');
  return { name, ...entry };
}
export async function callAutumn(op, args, env, fetcher = fetch) {
  let account;
  try { account = accountConfig(args, env); } catch (error) { return result({ error: error.message }, true); }
  const respond = (data, failed = false) => result({ ...data, _autumn_account: account.name }, failed);
  let base;
  try { base = new URL(account.base); } catch { return respond({ error: 'Invalid Autumn server configuration.' }, true); }
  if (base.protocol !== 'https:' || base.username || base.password || base.search || base.hash || base.pathname !== '/') return result({ error: 'Invalid Autumn server configuration.' }, true);
  let path = op.path;
  const headers = { Authorization: `Token ${account.token}`, Accept: 'application/json' };
  const query = new URLSearchParams();
  for (const param of op.parameters) {
    const value = args[param.argument];
    if (value === undefined || value === null) continue;
    if (param.in === 'path') path = path.replace(`{${param.name}}`, encodeURIComponent(String(value)));
    if (param.in === 'query') query.set(param.name, String(value));
    if (param.in === 'header') headers[param.name] = String(value);
  }
  const url = new URL(path, base);
  url.search = query.toString();
  const body = Object.fromEntries(op.bodyKeys.filter(key => args[key] !== undefined).map(key => [key, args[key]]));
  // The Workers runtime supports manual/follow; it rejects redirect="error".
  const init = { method: op.method, headers, redirect: 'manual', signal: AbortSignal.timeout(45000) };
  if (op.bodyKeys.length) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
  try {
    const response = await fetcher(url, init);
    if (response.status >= 300 && response.status < 400) return respond({ error: `Autumn returned an unexpected redirect (HTTP ${response.status}).` }, true);
    if (response.status === 204) return respond({ ok: true });
    const text = await response.text();
    let data;
    try { data = JSON.parse(text); } catch { return respond({ error: `Autumn returned an unexpected response (HTTP ${response.status}).` }, true); }
    // Never return the server credential even if an upstream error reflects it.
    const safe = JSON.parse(JSON.stringify(data).replaceAll(account.token, '[redacted]'));
    return respond(typeof safe === 'object' && safe !== null && !Array.isArray(safe) ? safe : { data: safe }, !response.ok);
  } catch (error) {
    const detail = String(error?.message ?? 'Unknown request failure').replaceAll(account.token, '[redacted]').replace(/https?:\/\/[^\s"'<>]+/g, value => { try { const address = new URL(value); return address.origin + address.pathname; } catch { return '[url]'; } }).slice(0, 500);
    return respond({ error: op.method === 'GET' ? 'Autumn could not be reached. Try again shortly.' : 'Autumn did not confirm the change. Check the current state before retrying; it may already have succeeded.', cause: { type: String(error?.name ?? 'Error'), message: detail } }, true);
  }
}
function makeHandler(env, fetcher) {
  return createMcpHandler(({ requestInfo }) => {
    const server = new McpServer({ name: 'Autumn', version: '1.0.0' }, {
      instructions: 'Autumn time tracking and project management for the owner across multiple accounts. Call list_accounts to discover account names and the default. Set account explicitly on every call when the user mentions an account or when comparing accounts; there is no shared mutable account switch. Always resolve project, session, context, tag and subproject IDs in the SAME account. Responses identify the selected account in _autumn_account. Use list_projects, subprojects, list_contexts and list_tags to resolve names to IDs. Responses follow Autumn API v2 with durations in minutes. Follow total and count with offset for complete results. Preserve explicit timezone offsets; local user timezone is Europe/Prague. Only mutate records when the user asks. Never retry an uncertain write automatically.',
    });
    server.registerTool('list_accounts', { description: 'List the owner\'s available Autumn accounts and the default. Use the returned names as account on every tool call when comparing kuda and Henry. Credentials are never returned.', inputSchema: fromJsonSchema({ type: 'object', properties: {}, additionalProperties: false }, validator), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } }, async () => {
      if (!authorized(requestInfo, env)) return result({ error: 'Only the connected Site owner can use Autumn tools.' }, true);
      try { return result({ default_account: env.AUTUMN_DEFAULT_ACCOUNT, accounts: Object.entries(accounts(env)).map(([name, entry]) => ({ name, username: entry.username, timezone: entry.timezone })) }); }
      catch (error) { return result({ error: error.message }, true); }
    });
    for (const op of operations) server.registerTool(op.name, { description: op.description, inputSchema: inputs.get(op.name), annotations: op.annotations }, async args => {
      if (!authorized(requestInfo, env)) return result({ error: 'Only the connected Site owner can use Autumn tools.' }, true);
      return callAutumn(op, args, env, fetcher);
    });
    return server;
  }, { maxRequestBodySize: 1024 * 1024 });
}
export function createWorker(fetcher = fetch) {
  return { async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/mcp') {
      if (request.method === 'POST') {
        if (Number(request.headers.get('content-length') ?? 0) > 1024 * 1024) return new Response('Request too large', { status: 413 });
        let body;
        try { body = await readMcpBody(request); } catch { return new Response('Invalid or oversized JSON', { status: 400 }); }
        // Discovery contains no private data. Every data-bearing call requires the owner.
        if (!authorized(request, env)) {
          if (!['initialize', 'notifications/initialized', 'server/discover', 'tools/list', 'ping'].includes(body.method)) return new Response('Sign in as the Site owner to use Autumn.', { status: 401 });
        }
        request = compatibleMcpRequest(request, body);
      }
      return makeHandler(env, fetcher).fetch(request);
    }
    if (url.pathname === '/' && request.method === 'GET') return new Response('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Autumn MCP</title><style>body{font:18px system-ui;background:#171e19;color:#f2eadd;max-width:620px;margin:12vh auto;padding:24px;line-height:1.6}h1{font-size:36px;color:#deb66f}a{color:#deb66f}</style><h1>Autumn</h1><p>Your time, projects, and commitments in ChatGPT.</p><p>Open <strong>Plugins → Personal → Created by you</strong> and connect <strong>Autumn MCP</strong>. Then ask Autumn to find a project, review your activity, or start a timer.</p><p>Connected to your private Autumn account. Only the owner can use these tools.</p></html>', { headers: { 'content-type': 'text/html;charset=utf-8', 'cache-control': 'no-store' } });
    return new Response('Not found', { status: 404 });
  } };
}
export default createWorker();
