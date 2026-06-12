# Browsercloud for Vercel

A Vercel Marketplace integration that connects a user's **TestMu AI / Browsercloud**
account to their Vercel project via OAuth, and injects their credentials
(`LT_USERNAME` / `LT_ACCESS_KEY`) as project environment variables.

It is an **OAuth "connect" integration** — the user authorizes with their existing
(or newly created) TestMu account; we do not provision accounts or bill through Vercel.

## How it works — two OAuth flows

```
 Flow A: Vercel  →  this service            Flow B: this service  →  auth-plus (TestMu)
 ─────────────────────────────             ──────────────────────────────────────────
 User installs from Vercel Marketplace      We redirect the user to accounts.lambdatest…
 → Vercel redirects with ?code              → user logs in / signs up → consent
 → we exchange code for a Vercel token       → redirect back with ?code
   (lets us write env vars)                  → we exchange code for auth-plus tokens
                                             → we fetch username + access_key
        └──────────────► we write LT_USERNAME / LT_ACCESS_KEY into the Vercel project ◄────┘
```

We inject the **durable `access_key`** (not the 1-hour OAuth token), because Vercel env
vars are static and don't refresh.

## Project layout

| Path | What it does |
|---|---|
| `app/config.py` | Settings + stage/prod auth-plus URLs |
| `app/pkce.py` | PKCE code verifier/challenge (S256) |
| `app/state.py` | Signed cookie that carries flow context across the redirects |
| `app/authplus.py` | auth-plus OAuth client — authorize / token / refresh / revoke (Flow B) |
| `app/credentials.py` | Swappable retrieval of `username` + `access_key` (introspect ↔ userinfo) |
| `app/vercel.py` | Vercel OAuth code exchange + env-var injection (Flow A) |
| `app/main.py` | FastAPI app wiring both flows together |
| `api/index.py` | Vercel Python runtime entrypoint |
| `scripts/register_client.py` | One-time DCR to register our web client with auth-plus |
| `scripts/build_api_secret.py` | Builds the RSA-OAEP `Api-Secret` for introspect |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the values

# 1) Register our client with auth-plus (one time), paste output into .env
python scripts/register_client.py --env stage --redirect-uri http://127.0.0.1:8000/api/auth/callback

# 2) Run locally
uvicorn app.main:app --reload --port 8000
```

Exercise Flow B alone at <http://127.0.0.1:8000/api/auth/login>.

## Deploy to Vercel

`vercel.json` rewrites all routes to the FastAPI app in `api/index.py`. Push and import
the repo in Vercel; set the same env vars in the Vercel project settings. Then register
the **production** redirect URI with auth-plus and create the Vercel Integration in the
[Integration Console](https://vercel.com/dashboard/integrations/console).

## Verified against stage (2026-06)

- ✅ **Flow B works end to end** — login → consent → authorize → code → token exchange →
  **introspect → real `username` + `access_key`**. The full TestMu side is proven.
- ✅ **Credential retrieval via `introspect`** — the Force team provided a pre-built
  service-to-service `Api-Secret` (base64 RSA-OAEP blob), set as
  `AUTHPLUS_INTROSPECT_API_SECRET`. We send it as the `Api-Secret` header; no client-side
  RSA encryption needed (so `scripts/build_api_secret.py` is unused in this path).
- ⚠️ **Web client + `http` loopback is rejected at the authorize step.** DCR registers a
  `web`/`confidential` client with an `http://127.0.0.1` redirect, but the authorize
  endpoint returns 400 on approval. **Local dev uses a `native`/`public` client**
  (loopback + PKCE, no secret); the deployed integration uses `web`/`confidential` + HTTPS.
- ⚠️ **The access token does NOT contain `username` or `access_key`.** Claims seen:
  `sub`, `user_id`/`id`, `client_id`, `iss`, `aud`, `exp` — which is why `introspect` is
  mandatory.

## Open items

1. **Vercel side (Flow A)** — create the integration in the Vercel Integration Console to
   get `VERCEL_CLIENT_ID/SECRET`, then test env-var injection into a real project.
2. **Signup-capable consent UI** + optional `login_hint` (email prefill) for new users.
3. **Production client** — register the `web`/`confidential` client with the deployed
   HTTPS callback once the host is known.
