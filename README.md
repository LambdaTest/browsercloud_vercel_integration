# Browser Cloud for Vercel

A Vercel Marketplace integration that connects a user's **TestMu AI / Browser Cloud**
account to their Vercel projects and injects their credentials
(`LT_USERNAME` / `LT_ACCESS_KEY`) as project environment variables.

It is an **OAuth "connect" integration** — the user authorizes with their existing
(or newly created) TestMu AI account; we do **not** provision accounts or bill through
Vercel.

**Live:** https://browsercloud-vercel-integration.vercel.app

## How it works — two OAuth flows

```
 Flow A: Vercel → this service              Flow B: this service → auth-plus (TestMu)
 ─────────────────────────────             ──────────────────────────────────────────
 User clicks "Connect Account"              We redirect to accounts.lambdatest…
 → Vercel redirects with ?code,             → user logs in / signs up → consent
   configurationId, teamId, next            → redirect back with ?code
 → we exchange code for a Vercel token      → we exchange code for auth-plus tokens
 → we read which projects were granted      → introspect → fetch username + access_key
        └────────► we write LT_USERNAME / LT_ACCESS_KEY into each selected project ◄────────┘
                          → redirect to `next` (closes the install window)
```

We inject the **durable `access_key`** (not the 1-hour OAuth token), because Vercel env
vars are static and don't refresh.

## Project targeting (important)

The marketplace install is **account-level** and does not hand us a project id. We read
the install's **configuration** (`GET /v1/integrations/configuration/{id}`) to learn which
projects were granted, then inject into **all of them**:

- **Specific project(s)** → configuration lists the project ids → inject into each. ✅
- **All Projects** → configuration returns `projects: null` and the integration token
  **cannot enumerate** projects (`/v9/projects` returns empty for a credential-only
  integration). We show a page asking the user to re-install scoping to **specific
  projects**. True "All Projects" support requires the native/resource Marketplace model
  (see _Future work_).

**Uninstall cleanup is automatic** — the injected vars are *integration-owned*, so Vercel
removes them from every project when the integration is uninstalled. No webhook needed.

## Project layout

| Path | What it does |
|---|---|
| `app/config.py` | Settings + stage/prod auth-plus URLs |
| `app/pkce.py` | PKCE code verifier/challenge (S256) |
| `app/state.py` | Signed cookie that carries flow context across the redirects |
| `app/authplus.py` | auth-plus OAuth client — authorize / token / refresh / revoke (Flow B) |
| `app/credentials.py` | Retrieval of `username` + `access_key` via `introspect` (swappable) |
| `app/vercel.py` | Vercel code exchange, configuration lookup, env-var injection (Flow A) |
| `app/main.py` | FastAPI app wiring both flows + branded success/error pages |
| `app/logo.py` | TestMu AI wordmark embedded as a base64 data URI (ships with the function) |
| `app/static/logo.png` | Canonical trimmed wordmark asset (source for `logo.py`) |
| `api/index.py` | Vercel Python runtime entrypoint |
| `scripts/register_client.py` | One-time DCR to register an auth-plus client |
| `scripts/build_api_secret.py` | RSA-OAEP `Api-Secret` builder — **unused** (Force team gave us a pre-built one) |

## Client types (auth-plus)

The `web`/`confidential` client type does **not** work in the stage consent UI today
(`web` + loopback → 400; `web` + HTTPS → the consent SPA 404s mid-flow). So we use a
**`native`/`public` client + PKCE** (no secret), which clears consent for both local
(loopback) and deployed (HTTPS) callbacks. PKCE protects the code exchange, so this is
safe for our server-side flow. See _Future work_ to switch to `web` once the backend
supports it.

> Note: the access token does **not** contain `username`/`access_key` (claims are `sub`,
> `user_id`, `client_id`, `iss`, `aud`, `exp`), which is why `introspect` is mandatory.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 1) Register a native client for local loopback (one time); paste output into .env
python scripts/register_client.py \
  --env stage \
  --redirect-uri http://127.0.0.1:8000/api/auth/callback \
  --client-type public --application-type native

# 2) Run it
uvicorn app.main:app --reload --port 8000
```

Exercise Flow B alone at <http://127.0.0.1:8000/api/auth/login>.

## Deploy

`vercel.json` rewrites all routes to the FastAPI app in `api/index.py`. The repo is
connected to Vercel, so pushing to `main` auto-deploys. Then:

1. Register a `native`/`public` client for the **deployed** HTTPS callback and set the
   `AUTHPLUS_*` env vars in the Vercel project.
2. Create the integration in the
   [Integration Console](https://vercel.com/dashboard/integrations/console) with:
   - **Redirect URL:** `https://<host>/api/integrations/vercel/callback`
   - **Scopes:** Projects → Read, Project Environment Variables → Read & Write
3. Set `VERCEL_CLIENT_ID` / `VERCEL_CLIENT_SECRET` from the console and redeploy.

## Environment variables

See `.env.example`. Key ones:

| Var | Purpose |
|---|---|
| `AUTHPLUS_ENV` | `stage` or `prod` (selects auth-plus URLs) |
| `AUTHPLUS_CLIENT_ID` / `AUTHPLUS_CLIENT_SECRET` | auth-plus client (secret blank for native) |
| `AUTHPLUS_REDIRECT_URI` | must exactly match the registered callback |
| `CREDENTIAL_METHOD` | `introspect` (default) or `userinfo` |
| `AUTHPLUS_INTROSPECT_API_SECRET` | pre-built S2S `Api-Secret` for `introspect` |
| `VERCEL_CLIENT_ID` / `VERCEL_CLIENT_SECRET` | from the Vercel Integration Console |
| `VERCEL_REDIRECT_URI` | must match the integration's Redirect URL |
| `INJECT_USERNAME_KEY` / `INJECT_ACCESS_KEY_KEY` | injected var names (`LT_USERNAME` / `LT_ACCESS_KEY`) |
| `SESSION_SECRET` | signs the flow cookie |

## Status

- ✅ Specific-project install → injects into all selected projects (verified on prod).
- ✅ `introspect` → real `username` + `access_key` via the pre-built S2S `Api-Secret`.
- ✅ Branded success/error pages; uninstall auto-removes the vars.
- ⬜ Listing polish (logo, copy, EULA) + submit for review.

## Future work

1. **True "All Projects"** — needs the native/resource Marketplace model (Vercel manages
   linking env vars to all current + future projects). Bigger effort: Vercel partner
   onboarding, Partner API, SSO, and a billing decision.
2. **Switch to a `web`/`confidential` client** once auth-plus supports confidential
   clients in the consent UI.
3. **`/userinfo` endpoint** on auth-plus returning `username`+`access_key`, to drop the
   `introspect` `Api-Secret` dependency (`CREDENTIAL_METHOD=userinfo`).
