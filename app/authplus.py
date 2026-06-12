from urllib.parse import urlencode

import httpx

from .config import get_settings


class AuthPlusClient:
    """Client for the auth-plus OAuth 2.1 server (Flow B).

    Same endpoints as the LambdaTest Terminal reference, but configured as a
    web/confidential client with a hosted HTTPS redirect URI.
    """

    def __init__(self) -> None:
        self.s = get_settings()

    def authorize_url(self, state: str, code_challenge: str) -> str:
        s = self.s
        params = {
            "response_type": "code",
            "client_id": s.authplus_client_id,
            "redirect_uri": s.authplus_redirect_uri,
            "scope": s.authplus_scope,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{s.authplus_consent_base}/oauth2?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        s = self.s
        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": s.authplus_redirect_uri,
            "client_id": s.authplus_client_id,
            "code_verifier": code_verifier,
        }
        # Confidential web client also sends its secret (native reference client omitted this).
        if s.authplus_client_secret:
            body["client_secret"] = s.authplus_client_secret
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{s.authplus_auth_base}/oauth2/token", json=body)
            r.raise_for_status()
            return r.json()

    async def refresh(self, refresh_token: str) -> dict:
        s = self.s
        body = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": s.authplus_client_id,
        }
        if s.authplus_client_secret:
            body["client_secret"] = s.authplus_client_secret
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{s.authplus_auth_base}/oauth2/token", json=body)
            r.raise_for_status()
            return r.json()

    async def revoke(self, token: str, token_type_hint: str = "access_token") -> None:
        s = self.s
        body = {
            "token": token,
            "token_type_hint": token_type_hint,
            "client_id": s.authplus_client_id,
        }
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(f"{s.authplus_auth_base}/oauth2/revoke", json=body)
