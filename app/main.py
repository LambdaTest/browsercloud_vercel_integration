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

    # Ask the install which projects it was granted (authoritative for scoped installs).
    try:
        config = await vc.get_configuration(
            flow["vercel_access_token"], flow["configuration_id"], flow["team_id"]
        )
    except Exception as e:  # surface instead of a blind 500 while wiring up
        resp = HTMLResponse(f"<h1>Config fetch failed</h1><pre>{e!r}</pre>")
        resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
        return resp

    # The configuration lists granted project IDs for a "specific projects" install;
    # for "All Projects" it returns None, and the token can't enumerate them.
    granted = config.get("projects")
    project_ids = [g["id"] if isinstance(g, dict) else g for g in (granted or [])]

    if not project_ids:
        resp = HTMLResponse(
            "<h1>Select specific projects</h1>"
            "<p>Browser Cloud adds your TestMu AI credentials to the projects you choose. "
            "Please remove the integration and re-install it, selecting "
            "<b>specific project(s)</b> instead of “All Projects.”</p>"
        )
        resp.set_cookie(FLOW_COOKIE, dump_state(flow), **_COOKIE_KW)
        return resp

    # Inject into every selected project. Carry the list through the TestMu login.
    flow["project_ids"] = project_ids
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

    # Inject the credentials into every selected project (back-compat with single project_id).
    project_ids = flow.get("project_ids") or (
        [flow["project_id"]] if flow.get("project_id") else []
    )
    vercel_token = flow.get("vercel_access_token")
    results: dict[str, str] = {}
    for pid in project_ids if vercel_token else []:
        try:
            await vc.upsert_env_var(
                vercel_token, pid, s.inject_username_key, creds["username"],
                team_id=flow.get("team_id"),
            )
            await vc.upsert_env_var(
                vercel_token, pid, s.inject_access_key_key, creds["access_key"],
                team_id=flow.get("team_id"),
            )
            results[pid] = "ok"
        except Exception as e:  # surface instead of 500 while wiring up Flow A
            results[pid] = f"error: {e!r}"

    injected = bool(results) and all(v == "ok" for v in results.values())

    nxt = flow.get("next")
    if injected and nxt:
        resp = RedirectResponse(nxt)
        resp.delete_cookie(FLOW_COOKIE, path="/")
        return resp

    # Shown only if injection didn't fully succeed (or there's no Vercel context).
    ak = creds["access_key"]
    masked = f"{ak[:4]}…{ak[-4:]}" if len(ak) > 8 else "…"
    diag = {
        "injected": injected,
        "results_per_project": results,
        "project_ids": project_ids,
        "next": nxt,
        "team_id": flow.get("team_id"),
        "configuration_id": flow.get("configuration_id"),
    }
    body = (
        f"<pre>username:   {creds['username']}\naccess_key: {masked}\n\n"
        f"{json.dumps(diag, indent=2)}</pre>"
    )
    resp = HTMLResponse(f"<h1>Install diagnostics</h1>{body}")
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp
