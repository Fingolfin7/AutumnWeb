import { readFile, writeFile } from 'node:fs/promises';
import { parse } from 'yaml';

const spec = parse(await readFile(new URL('../../../openapi-v2.yaml', import.meta.url), 'utf8'));
function schema(value) {
  if (Array.isArray(value)) return value.map(schema);
  if (!value || typeof value !== 'object') return value;
  if (value.$ref) {
    const target = value.$ref.split('/').slice(1).reduce((node, key) => node[key], spec);
    return schema({ ...target, ...Object.fromEntries(Object.entries(value).filter(([key]) => key !== '$ref')) });
  }
  const result = Object.fromEntries(Object.entries(value).filter(([key]) => !['nullable', 'readOnly', 'writeOnly', 'example'].includes(key)).map(([key, item]) => [key, schema(item)]));
  if (['double', 'float', 'int32', 'int64', 'binary'].includes(result.format)) delete result.format;
  if (result.type === 'object') result.additionalProperties ??= false;
  if (value.nullable) return { anyOf: [result, { type: 'null' }] };
  return result;
}
const overrides = { me_retrieve: 'me', timers_retrieve: 'status', timers_create: 'start', timers_stop_create: 'stop', timers_restart_create: 'restart', timers_partial_update: 'update_timer', timers_destroy: 'delete_timer', sessions_create: 'track', project_subprojects_list: 'subprojects', project_subprojects_create: 'create_subproject', export_retrieve: 'export_data', import_create: 'import_data', reports_timeline_retrieve: 'get_timeline', reports_weekly_review_retrieve: 'weekly_review', recommendations_timers_retrieve: 'timer_suggestions', recommendations_luna_retrieve: 'luna_recommendations', notifications_schedules_list: 'list_reminder_schedules', notifications_schedules_create: 'create_reminder_schedule' };
const descriptions = {
  me: 'Get the authenticated Autumn account and API version.',
  start: 'Start a live timer now. Resolve the project ID with list_projects first. stop_after_minutes sets an optional automatic stop. Use track for past work.',
  stop: 'Stop a live timer by session_id. Use status to find active timer IDs.',
  status: 'List active timers with elapsed minutes and their session IDs.',
  restart: 'Restart a timer by session_id.',
  track: 'Record a completed past session with project_id, start and end. Always supply an explicit timezone offset. Resolve project and subproject IDs first.',
  list_projects: 'List or search projects. Use search to resolve names to numeric IDs; add related=true to also find projects that match the search by meaning, and similarity (0.25 loose to 0.60 strict; default: the account setting) to say how close they must be. Responses include count and total; advance the offset using the returned count until the total is covered.',
  list_sessions: 'Search completed or active sessions by IDs, dates, search (project, subproject and note text) or note_snippet. Search needs every word (any order); quote a phrase to match it exactly. Add related=true with search to also include sessions that match it by meaning (similarity, 0.25 loose to 0.60 strict, sets how close; default: the account setting): the match field of each result says direct (the text contains the search) or related, and the default relevance ordering lists direct matches newest first, then related ones best first, as the Sessions page does; ordering=newest sorts all by date. Set include="note" when notes are needed. Responses include count and total; advance the offset using the returned count until the total is covered. Do not assume one page is the complete history.',
  import_data: 'Import Autumn data. This writes records; inspect the import options and preview before committing an import.',
  get_dashboard: 'Get the Autumn home dashboard in one read: activity streak, active timers, quick starts, recent sessions with rendered notes, commitments, and today timeline.',
  get_timeline: 'Get timeline lanes and session segments for a local date range, optionally scoped to one context.',
  timer_suggestions: 'Get fast deterministic timer suggestions from recent work, habits, and commitments, optionally scoped to one context.',
  luna_recommendations: 'Get Luna timer recommendations. A 202 response means generation is still in progress and should be retried after the supplied delay.',
  weekly_review: 'Summarize a local Monday-to-Sunday Autumn week: tracked time, project totals, session count, and closed commitment results. Pass any date inside the desired week.',
  list_reminder_schedules: 'List the account\'s active planned reminder schedules, including targets, cadence, next fire time, and reminders due within seven days.',
  create_reminder_schedule: 'Create a planned reminder schedule for one owned project, context, or tag at a profile-local date and time, optionally repeating daily or weekly.',
};
const operations = [];
for (const [path, item] of Object.entries(spec.paths)) for (const [method, operation] of Object.entries(item)) {
  if (!operation.operationId) continue;
  const mcpExposure = operation['x-autumn-mcp'];
  if (!['include', 'exclude'].includes(mcpExposure)) throw new Error(`Missing x-autumn-mcp on ${method.toUpperCase()} ${path} (${operation.operationId})`);
  if (mcpExposure === 'exclude') continue;
  const [resource, ...actionParts] = operation.operationId.split('_');
  const action = actionParts.join('_');
  const prefix = { list: 'list', retrieve: 'get', create: 'create', partial_update: 'update', destroy: 'delete', merge: 'merge', restart: 'restart' }[action];
  const singular = { commitments: 'commitment', contexts: 'context', projects: 'project', sessions: 'session', subprojects: 'subproject', tags: 'tag' }[resource] ?? resource;
  const name = overrides[operation.operationId] ?? (prefix ? `${prefix}_${['retrieve', 'create', 'partial_update', 'destroy'].includes(action) ? singular : resource}` : operation.operationId);
  const input = { type: 'object', properties: {}, required: [], additionalProperties: false };
  const parameters = (operation.parameters ?? []).map(param => ({ ...param, argument: param.in === 'header' && param.name === 'If-Match' ? 'expected_version' : param.name }));
  for (const param of parameters) {
    input.properties[param.argument] = { ...schema(param.schema), ...(param.description ? { description: param.description } : {}) };
    if (param.name.endsWith('_ids') && param.in === 'query') input.properties[param.argument].description = 'Comma-separated numeric IDs, resolved with the corresponding list tool.';
    if (param.required) input.required.push(param.argument);
  }
  const body = operation.requestBody?.content?.['application/json']?.schema;
  if (body) {
    const resolved = schema(body);
    Object.assign(input.properties, resolved.properties);
    input.required.push(...(resolved.required ?? []));
  }
  input.properties.account = { type: 'string', minLength: 1, maxLength: 128, description: 'Authorized Autumn account name from list_accounts. Omit to use your selected default. Set explicitly when comparing accounts.' };
  const readOnly = method === 'get';
  operations.push({ name, method: method.toUpperCase(), path, parameters, bodyKeys: body ? Object.keys(schema(body).properties ?? {}) : [], inputSchema: input,
    description: (descriptions[name] ?? `${name.replaceAll('_', ' ')} in Autumn API v2. Use numeric IDs from list tools. Durations are in minutes. Dates use ISO 8601; timestamps should include a timezone offset.${parameters.some(p => p.name === 'If-Match') ? ' Supply expected_version from the current resource to prevent overwriting concurrent edits.' : ''}`) + ' Set account explicitly for another Autumn account; resolve IDs in that same account.',
    annotations: { readOnlyHint: readOnly, destructiveHint: !readOnly && (method === 'delete' || method === 'patch' || /merge|import|stop|restart|adjustment/.test(operation.operationId)), idempotentHint: readOnly || method === 'delete', openWorldHint: true } });
}
if (new Set(operations.map(o => o.name)).size !== operations.length) throw new Error('Duplicate MCP tool names');
await writeFile(new URL('../src/operations.json', import.meta.url), JSON.stringify(operations, null, 2) + '\n');
console.log(`Generated ${operations.length} API v2 tools for the shared Django MCP.`);
