import json

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import authplus as ap
from . import vercel as vc
from .config import get_settings
from .credentials import get_testmu_credentials
from .pkce import generate_pkce, generate_state
from .state import dump_state, load_state

app = FastAPI(title="Browsercloud × Vercel Integration")

FLOW_COOKIE = "bc_flow"
_COOKIE_KW = dict(httponly=True, secure=True, samesite="lax", max_age=600, path="/")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (
        "<h1>Browsercloud for Vercel</h1>"
        "<p>Install from the Vercel Marketplace to connect "
        "your TestMu AI / Browsercloud credentials and use the platform from inside Vercel.</p>"
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/api/integrations/vercel/callback")
async def vercel_callback(request: Request):
    """Flow A entrypoint: Vercel redirects here post-install.

    Query: code, configurationId, teamId, next, (projectId for project-scoped installs).
    We exchange the code, stash the Vercel context, then kick off Flow B (auth-plus login).
    """
    params = request.query_params
    code = params.get("code")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)

    token = await vc.exchange_code(code)

    verifier, challenge = generate_pkce()
    state = generate_state()
    flow = {
        "vercel_access_token": token.get("access_token"),
        "team_id": token.get("team_id") or params.get("teamId"),
        "configuration_id": params.get("configurationId"),
        "project_id": params.get("projectId") or token.get("project_id"),
        "next": params.get("next"),
        "code_verifier": verifier,
        "state": state,
    }

    resp = RedirectResponse(ap.AuthPlusClient().authorize_url(state, challenge))
    resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
    return resp


@app.get("/api/auth/login")
async def manual_login():
    """Standalone auth-plus login, for exercising Flow B without a Vercel install."""
    verifier, challenge = generate_pkce()
    state = generate_state()
    flow = {"code_verifier": verifier, "state": state}
    resp = RedirectResponse(ap.AuthPlusClient().authorize_url(state, challenge))
    resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
    return resp


@app.get("/api/auth/callback")
async def auth_callback(request: Request):
    """Flow B callback: auth-plus redirects here with code & state.

    We verify state, exchange the code for tokens, fetch username+access_key, and
    inject them as env vars into the user's Vercel project, then return them to Vercel.
    """
    params = request.query_params
    cookie = request.cookies.get(FLOW_COOKIE)
    flow = load_state(cookie) if cookie else None
    if not flow:
        return JSONResponse({"error": "missing or expired flow state"}, status_code=400)
    if params.get("state") != flow.get("state"):
        return JSONResponse({"error": "state mismatch"}, status_code=400)
    code = params.get("code")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)

    tokens = await ap.AuthPlusClient().exchange_code(code, flow["code_verifier"])

    s = get_settings()
    # Dev aid: until we're provisioned for credential retrieval, don't crash — show what
    # auth-plus returned (decoded, unverified) so we can confirm the flow works end to end.
    if s.credential_method == "introspect" and not s.authplus_introspect_api_secret:
        import jwt

        claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        resp = HTMLResponse(
            "<h1>Token exchange OK ✓</h1>"
            "<p>auth-plus returned tokens, but introspect isn't configured yet, so no "
            "credentials were fetched or injected.</p>"
            f"<h3>Access-token claims</h3><pre>{json.dumps(claims, indent=2)}</pre>"
        )
        resp.delete_cookie(FLOW_COOKIE, path="/")
        return resp

    creds = await get_testmu_credentials(tokens)

    project_id = flow.get("project_id")
    vercel_token = flow.get("vercel_access_token")
    injected = False
    if project_id and vercel_token:
        await vc.upsert_env_var(
            vercel_token, project_id, s.inject_username_key, creds["username"],
            team_id=flow.get("team_id"),
        )
        await vc.upsert_env_var(
            vercel_token, project_id, s.inject_access_key_key, creds["access_key"],
            team_id=flow.get("team_id"),
        )
        injected = True

    nxt = flow.get("next")
    if nxt:
        resp = RedirectResponse(nxt)
        resp.delete_cookie(FLOW_COOKIE, path="/")
        return resp

    if injected:
        body = "<p>Browsercloud credentials injected into your project.</p>"
    else:
        # Dev aid: no Vercel project in this flow, so show what introspect returned
        # (access_key masked) to confirm credential retrieval works.
        ak = creds["access_key"]
        masked = f"{ak[:4]}…{ak[-4:]}" if len(ak) > 8 else "…"
        body = (
            "<p>Authenticated — no target Vercel project, so showing the fetched "
            "credentials to confirm introspect works:</p>"
            f"<pre>username:   {creds['username']}\naccess_key: {masked}</pre>"
        )
    resp = HTMLResponse(f"<h1>Connected ✓</h1>{body}")
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp
