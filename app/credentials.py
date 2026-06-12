import httpx

from .config import get_settings


async def get_testmu_credentials(tokens: dict) -> dict:
    """Return {"username": ..., "access_key": ...} for a set of auth-plus tokens.

    Retrieval is swappable via CREDENTIAL_METHOD because access_key is NOT in the
    planned JWT claims:
      - "introspect": POST /oauth2/introspect (needs the RSA-OAEP Api-Secret) — source of truth today.
      - "userinfo":   GET  /oauth2/userinfo (Bearer) — preferred, IF auth-plus exposes it.

    Whichever the backend team settles on, only this module changes.
    """
    method = get_settings().credential_method
    if method == "introspect":
        return await _via_introspect(tokens["access_token"])
    if method == "userinfo":
        return await _via_userinfo(tokens["access_token"])
    raise ValueError(f"Unknown CREDENTIAL_METHOD: {method!r}")


async def _via_introspect(access_token: str) -> dict:
    s = get_settings()
    headers = {
        "Api-Secret": s.authplus_introspect_api_secret,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{s.authplus_auth_base}/oauth2/introspect",
            headers=headers,
            json={"token": access_token},
        )
        r.raise_for_status()
        data = r.json()
    if not data.get("active"):
        raise RuntimeError("auth-plus introspect reports token inactive")
    return {"username": data["username"], "access_key": data["access_key"]}


async def _via_userinfo(access_token: str) -> dict:
    s = get_settings()
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{s.authplus_auth_base}/oauth2/userinfo", headers=headers)
        r.raise_for_status()
        data = r.json()
    return {"username": data["username"], "access_key": data["access_key"]}
