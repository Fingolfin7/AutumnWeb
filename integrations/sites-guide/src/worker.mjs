const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Autumn MCP connection</title><style>body{margin:0;background:#101214;color:#ece9e2;font:17px/1.6 system-ui,sans-serif}main{max-width:660px;padding:56px 24px;margin:auto}h1{font-size:36px;line-height:1.2}a{color:#efab65}code{overflow-wrap:anywhere;background:#24272a;padding:4px 8px;border-radius:5px}.label{color:#efab65;text-transform:uppercase;letter-spacing:.12em;font-size:13px}.button{display:inline-block;background:#efab65;color:#101214;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600}li{margin:12px 0}</style></head><body><main><p class="label">Autumn MCP</p><h1>One connection for ChatGPT and Claude.</h1><p>The Autumn MCP server now lives in Autumn itself. This Site is a connection guide; the original Sites MCP has been retired.</p><p>Server URL:</p><p><code>https://autumn-lg0b.onrender.com/mcp</code></p><ol><li>Add a custom MCP connection in ChatGPT or Claude using this URL and OAuth sign-in.</li><li>Sign in to Autumn and select the accounts to share. Sign in to any additional account before selecting it.</li><li>Choose read-only access or allow changes. Manage and revoke access from your Autumn profile.</li></ol><p><a class="button" href="https://autumn-lg0b.onrender.com/mcp/connections/">Manage your accounts and connections</a></p><p><a href="https://github.com/Fingolfin7/AutumnWeb/blob/master/docs/mcp-clients.md">Full setup instructions</a></p></main></body></html>`;

export default {
  fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === '/mcp' || path === '/mcp/') {
      return Response.json({error:'The Sites MCP has been retired. Connect using OAuth at https://autumn-lg0b.onrender.com/mcp.'}, {status:410,headers:{'Cache-Control':'no-store'}});
    }
    if (path !== '/') return new Response('Not found',{status:404});
    return new Response(html,{headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}});
  }
};
