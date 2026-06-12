from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import get_settings

_COOKIE_SALT = "browsercloud-vercel-flow"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_COOKIE_SALT)


def dump_state(data: dict) -> str:
    """Sign the flow context (Vercel token + PKCE verifier) into an opaque cookie value."""
    return _serializer().dumps(data)


def load_state(token: str, max_age: int = 600) -> dict | None:
    try:
        return _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
