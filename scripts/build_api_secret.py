"""Build the `Api-Secret` header value for POST /oauth2/introspect.

    Api-Secret = base64( RSA-OAEP( security_salt, auth_plus_public_key ) )

The Force team provisions a row for your service in `api_service_access_control` and
gives you the `security_salt` plus the auth-plus RSA public key (PEM). Then:

    python scripts/build_api_secret.py --salt <security_salt> --public-key authplus_pub.pem

NOTE: the OAEP hash must match what auth-plus uses to decrypt. Default here is SHA-256;
if introspect rejects the secret, try --hash sha1. Confirm with the backend team.
"""

import argparse
import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_HASHES = {"sha1": hashes.SHA1, "sha256": hashes.SHA256}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--salt", required=True, help="security_salt from api_service_access_control")
    p.add_argument("--public-key", required=True, help="PEM file with the auth-plus public key")
    p.add_argument("--hash", choices=list(_HASHES), default="sha256")
    args = p.parse_args()

    with open(args.public_key, "rb") as f:
        pub = serialization.load_pem_public_key(f.read())

    algo = _HASHES[args.hash]()
    ciphertext = pub.encrypt(
        args.salt.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=algo), algorithm=algo, label=None),
    )
    print(base64.b64encode(ciphertext).decode())


if __name__ == "__main__":
    main()
