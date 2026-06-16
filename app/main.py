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


def _start_authplus(flow: dict) -> RedirectResponse:
    """Attach PKCE + state to the flow and redirect into the TestMu (auth-plus) login."""
    verifier, challenge = generate_pkce()
    flow["code_verifier"] = verifier
    flow["state"] = generate_state()
    resp = RedirectResponse(ap.AuthPlusClient().authorize_url(flow["state"], challenge))
    resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
    return resp


@app.get("/api/integrations/vercel/callback")
async def vercel_callback(request: Request):
    """Flow A entrypoint: Vercel redirects here after the user connects the integration.

    The marketplace install is account-level — it gives us configurationId/teamId/next
    but no project. So we list the projects our (scoped) token can reach:
      - exactly one  -> inject straight into it,
      - more than one -> show a picker,
      - none          -> explain.
    """
    params = request.query_params
    code = params.get("code")
    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)

    token = await vc.exchange_code(code)
    flow = {
        "vercel_access_token": token.get("access_token"),
        "team_id": token.get("team_id") or params.get("teamId"),
        "configuration_id": params.get("configurationId"),
        "next": params.get("next"),
    }

    projects = await vc.list_projects(flow["vercel_access_token"], flow["team_id"])

    if len(projects) == 1:
        # Scoped to a single project → no need to ask; go straight to login.
        flow["project_id"] = projects[0]["id"]
        return _start_authplus(flow)

    if not projects:
        resp = HTMLResponse(
            "<h1>No accessible projects</h1>"
            "<p>This integration can't see any projects to add credentials to. "
            "Re-install and grant access to at least one project.</p>"
        )
        resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
        return resp

    # Multiple projects ("All Projects" install) → let the user choose.
    items = "".join(
        f'<li><a href="/api/integrations/vercel/select?project_id={p["id"]}">{p["name"]}</a></li>'
        for p in projects
    )
    resp = HTMLResponse(
        "<h1>Connect Browser Cloud</h1>"
        "<p>Choose a project to add your TestMu AI credentials to:</p>"
        f"<ul>{items}</ul>"
    )
    resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
    return resp


@app.get("/api/integrations/vercel/select")
async def vercel_select(request: Request):
    """Picker target: remember the chosen project, then start the TestMu login."""
    project_id = request.query_params.get("project_id")
    cookie = request.cookies.get(FLOW_COOKIE)
    flow = load_state(cookie) if cookie else None
    if not flow or not project_id:
        return JSONResponse({"error": "missing flow or project_id"}, status_code=400)
    flow["project_id"] = project_id
    return _start_authplus(flow)


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
    inject_error = None
    if project_id and vercel_token:
        try:
            await vc.upsert_env_var(
                vercel_token, project_id, s.inject_username_key, creds["username"],
                team_id=flow.get("team_id"),
            )
            await vc.upsert_env_var(
                vercel_token, project_id, s.inject_access_key_key, creds["access_key"],
                team_id=flow.get("team_id"),
            )
            injected = True
        except Exception as e:  # surface instead of 500 while wiring up Flow A
            inject_error = repr(e)

    nxt = flow.get("next")
    if injected and nxt:
        resp = RedirectResponse(nxt)
        resp.delete_cookie(FLOW_COOKIE, path="/")
        return resp

    # Diagnostics page (shown until injection succeeds) — reveals exactly what Vercel sent,
    # so we can see why no project was targeted.
    ak = creds["access_key"]
    masked = f"{ak[:4]}…{ak[-4:]}" if len(ak) > 8 else "…"
    diag = {
        "injected": injected,
        "inject_error": inject_error,
        "project_id": project_id,
        "next": nxt,
        "team_id": flow.get("team_id"),
        "configuration_id": flow.get("configuration_id"),
        "vercel_params_received": flow.get("dbg_params"),
        "vercel_token_keys": flow.get("dbg_token_keys"),
    }
    body = (
        f"<pre>username:   {creds['username']}\naccess_key: {masked}\n\n"
        f"{json.dumps(diag, indent=2)}</pre>"
    )
    resp = HTMLResponse(f"<h1>Install diagnostics</h1>{body}")
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp
