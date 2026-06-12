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

## Open items pending from the backend team

1. **Confirm `web`/`confidential` DCR is accepted** on auth-plus (vs the native reference).
2. **`access_key` retrieval method** — provision us for `introspect`, or expose a
   `/userinfo` returning `username`+`access_key`. (`access_key` is not in the planned
   JWT claims.) Controlled by `CREDENTIAL_METHOD`.
3. **OAEP hash** for the introspect `Api-Secret` (SHA-256 vs SHA-1).
4. **Signup-capable consent UI** + optional `login_hint` (email prefill) for new users.
