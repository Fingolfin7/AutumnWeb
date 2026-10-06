// Exercise the official SDK's authorization scope selection with captured public
// discovery documents. No tokens, registration, redirects or network requests.
import { readFileSync } from 'node:fs';
import { auth, extractWWWAuthenticateParams } from '@modelcontextprotocol/sdk/client/auth.js';

const input = JSON.parse(readFileSync(0, 'utf8'));
const challenge = extractWWWAuthenticateParams(new Response(null, {
  status: 401, headers: { 'WWW-Authenticate': input.challenge }
}));
const issuer = input.resourceMetadata.authorization_servers[0];
let requestedScope;
const provider = {
  redirectUrl: 'https://client.example/callback',
  clientMetadata: { redirect_uris: ['https://client.example/callback'], token_endpoint_auth_method: 'none' },
  discoveryState: () => ({
    authorizationServerUrl: issuer,
    resourceMetadata: input.resourceMetadata,
    authorizationServerMetadata: input.authorizationMetadata
  }),
  clientInformation: () => ({ client_id: 'scope-discovery-fixture', issuer }),
  tokens: () => undefined,
  saveCodeVerifier: () => {},
  redirectToAuthorization: url => { requestedScope = url.searchParams.get('scope'); }
};
const result = await auth(provider, {
  serverUrl: input.resourceMetadata.resource,
  scope: challenge.scope,
  fetchFn: () => { throw new Error('Scope discovery verification must not access the network.'); }
});
if (result !== 'REDIRECT' || !requestedScope) throw new Error('No authorization scope selected.');
console.log(JSON.stringify({ scope: requestedScope }));
