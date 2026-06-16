import httpx

from .config import get_settings

VERCEL_API = "https://api.vercel.com"


async def exchange_code(code: str) -> dict:
    """Exchange the Vercel install `code` for an access token (Flow A).

    Vercel's token endpoint expects form-encoded params and returns, among others,
    access_token, team_id, and (for project-scoped installs) installation/project info.
    """
    s = get_settings()
    data = {
        "client_id": s.vercel_client_id,
        "client_secret": s.vercel_client_secret,
        "code": code,
        "redirect_uri": s.vercel_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{VERCEL_API}/v2/oauth/access_token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        return r.json()


async def upsert_env_var(
    access_token: str,
    project_id: str,
    key: str,
    value: str,
    team_id: str | None = None,
    targets: list[str] | None = None,
) -> dict:
    """Create/update an encrypted env var on a Vercel project (upsert=true)."""
    s = get_settings()
    targets = targets or ["production", "preview", "development"]
    params = {"upsert": "true"}
    if team_id:
        params["teamId"] = team_id
    payload = {"key": key, "value": value, "type": "encrypted", "target": targets}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{VERCEL_API}/v10/projects/{project_id}/env",
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json()


async def get_configuration(access_token: str, configuration_id: str, team_id: str | None = None) -> dict:
    """Fetch this integration install's configuration.

    For a project-scoped install, the returned object carries the granted project IDs
    (`projects`) and `projectSelection` ("selected" or "all") — the authoritative answer
    to "which projects did the user grant?", which the bare /v9/projects list does not give.
    """
    params = {}
    if team_id:
        params["teamId"] = team_id
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{VERCEL_API}/v1/integrations/configuration/{configuration_id}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json()


async def list_projects(access_token: str, team_id: str | None = None, limit: int = 100) -> list[dict]:
    """List the team's projects (needs the Projects: Read scope).

    Account-level installs don't tell us which project to target, so we list them
    and let the user pick.
    """
    params = {"limit": str(limit)}
    if team_id:
        params["teamId"] = team_id
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"{VERCEL_API}/v9/projects",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json().get("projects", [])
