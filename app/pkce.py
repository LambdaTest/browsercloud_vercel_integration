import base64
import hashlib
import secrets


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256.

    Mirrors the auth-plus reference: 96 random bytes -> base64url (128 chars) verifier,
    challenge = base64url(sha256(verifier)).
    """
    raw = secrets.token_bytes(96)
    verifier = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)
