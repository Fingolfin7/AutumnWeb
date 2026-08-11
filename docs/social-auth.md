# Social authentication

Autumn supports Google and GitHub as optional sign-in methods alongside its
existing username/password login. Provider credentials are read from environment
variables and OAuth access tokens are not retained.

## Account policy

- Existing users connect a provider from **Profile > Connected accounts**.
- An anonymous provider login is never silently merged into a local account by
  matching email alone.
- When `ALLOW_REGISTRATION=FALSE`, an unknown social identity cannot create an
  Autumn account.
- A user cannot disconnect their final social identity unless they have a usable
  local password or another connected provider.

## Google

Create an OAuth 2.0 **Web application** in Google Cloud and configure the
appropriate authorized redirect URIs:

```text
http://127.0.0.1:8000/accounts/google/login/callback/
https://autumn-lg0b.onrender.com/accounts/google/login/callback/
```

Add a separate URI if Autumn moves to a custom domain. Set these environment
variables in the matching deployment:

```text
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
```

Autumn requests only OpenID identity, profile, and email scopes. It requests
online access and does not store Google tokens.

## GitHub

Create an OAuth App under **GitHub > Settings > Developer settings > OAuth
Apps**. Use the Autumn origin as the Homepage URL and one of these Authorization
callback URLs:

```text
http://127.0.0.1:8000/accounts/github/login/callback/
https://autumn-lg0b.onrender.com/accounts/github/login/callback/
```

GitHub OAuth Apps accept only one callback URL, so use separate OAuth Apps for
local development and production. Set the matching credentials:

```text
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
```

Autumn requests `user:email` so GitHub can return verified email addresses even
when the user's primary email is private. It requests no repository or
organization access and does not store GitHub tokens.

## Deploy

Install dependencies and create the django-allauth tables before enabling either
provider:

```text
pip install -r requirements.txt
python manage.py migrate
```

Restart the web service after adding or changing OAuth environment variables.
