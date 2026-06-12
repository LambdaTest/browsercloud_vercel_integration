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
