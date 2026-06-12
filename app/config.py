from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# auth-plus environment URLs. The reference doc used the native/CLI client; we run a
# web/confidential client but hit the same endpoints.
AUTHPLUS_URLS = {
    "stage": {
        "auth_base": "https://stage-auth.lambdatestinternal.com",
        "consent_base": "https://stage-accounts.lambdatestinternal.com",
    },
    "prod": {
        "auth_base": "https://auth.lambdatest.com",
        "consent_base": "https://accounts.lambdatest.com",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # auth-plus (Flow B)
    authplus_env: str = "stage"
    authplus_client_id: str = ""
    authplus_client_secret: str = ""
    authplus_redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback"
    authplus_scope: str = "*"

    # credential retrieval: introspect | userinfo
    credential_method: str = "introspect"
    authplus_introspect_api_secret: str = ""

    # Vercel (Flow A)
    vercel_client_id: str = ""
    vercel_client_secret: str = ""
    vercel_redirect_uri: str = "http://127.0.0.1:8000/api/integrations/vercel/callback"

    # injected env var names
    inject_username_key: str = "LT_USERNAME"
    inject_access_key_key: str = "LT_ACCESS_KEY"

    # cookie signing
    session_secret: str = "change-me"

    @property
    def authplus_auth_base(self) -> str:
        return AUTHPLUS_URLS[self.authplus_env]["auth_base"]

    @property
    def authplus_consent_base(self) -> str:
        return AUTHPLUS_URLS[self.authplus_env]["consent_base"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
