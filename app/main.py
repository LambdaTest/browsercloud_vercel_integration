from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import authplus as ap
from . import vercel as vc
from .config import get_settings
from .credentials import get_testmu_credentials
from .pkce import generate_pkce, generate_state
from .state import dump_state, load_state

app = FastAPI(title="Browser Cloud for Vercel")

FLOW_COOKIE = "bc_flow"
_COOKIE_KW = dict(httponly=True, secure=True, samesite="lax", max_age=600, path="/")


LOGO_URL = "https://www.testmuai.com/logo.png"


def _page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    """A sleek, branded page for user-facing success/error states."""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
background:radial-gradient(1200px 600px at 50% -10%,#ede9fe 0%,#eef2ff 35%,#f8fafc 100%);
color:#0f172a;padding:1.5rem}}
.card{{background:#fff;max-width:30rem;width:100%;padding:2.75rem 2.5rem;border-radius:20px;
box-shadow:0 20px 60px rgba(76,29,149,.12);border:1px solid rgba(15,23,42,.06);text-align:center}}
.logo{{height:38px;width:auto;margin-bottom:1.75rem}}
h1{{font-size:1.4rem;margin:0 0 .6rem;letter-spacing:-.02em;font-weight:700}}
p{{color:#475569;line-height:1.6;margin:0;font-size:.975rem}}
.foot{{margin-top:1.75rem;font-size:.78rem;color:#94a3b8}}
</style></head>
<body><div class="card">
<img class="logo" src="{LOGO_URL}" alt="TestMu AI">
<h1>{title}</h1>
<p>{message}</p>
<div class="foot">Browser Cloud · TestMu AI</div>
</div></body></html>"""
    return HTMLResponse(html, status_code=status_code)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return _page(
        "Browser Cloud for Vercel",
        "Install from the Vercel Marketplace to connect your TestMu AI / Browser Cloud "
        "credentials to your projects.",
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
    except Exception:  # don't leak internals; show a clean message
        return _page(
            "Something went wrong",
            "We couldn't read your integration configuration from Vercel. "
            "Please try installing again, or contact support.",
            status_code=502,
        )

    # The configuration lists granted project IDs for a "specific projects" install;
    # for "All Projects" it returns None, and the token can't enumerate them.
    granted = config.get("projects")
    project_ids = [g["id"] if isinstance(g, dict) else g for g in (granted or [])]

    if not project_ids:
        return _page(
            "Select specific projects",
            "Browser Cloud adds your TestMu AI credentials to the projects you choose. "
            "Please remove the integration and re-install it, selecting specific "
            "project(s) instead of “All Projects.”",
        )

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
    try:
        creds = await get_testmu_credentials(tokens)
    except Exception:
        return _page(
            "Couldn't connect",
            "We signed you in to TestMu AI but couldn't retrieve your credentials. "
            "Please try again, or contact support if this keeps happening.",
            status_code=502,
        )

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
        except Exception:
            results[pid] = "error"

    ok_count = sum(1 for v in results.values() if v == "ok")
    injected = bool(results) and ok_count == len(results)

    nxt = flow.get("next")
    if injected and nxt:
        # Success → hand control back to Vercel (closes the install window).
        resp = RedirectResponse(nxt)
        resp.delete_cookie(FLOW_COOKIE, path="/")
        return resp

    if injected:
        return _page(
            "Connected ✓",
            f"Browser Cloud credentials were added to {ok_count} project(s). "
            "You can close this window.",
        )
    if results:
        return _page(
            "Couldn't finish",
            f"Added credentials to {ok_count} of {len(results)} project(s), but the rest "
            "failed. Please try again, or contact support.",
            status_code=502,
        )
    return _page(
        "Signed in ✓",
        "Authenticated with TestMu AI, but there were no projects to update.",
    )
