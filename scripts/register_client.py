"""One-time Dynamic Client Registration (DCR) for the auth-plus web client.

The reference doc registers a public/native client (loopback redirect). For the Vercel
integration we register a *confidential/web* client with a hosted HTTPS redirect URI.
`POST /oauth2/register` needs no auth.

Usage:
    python scripts/register_client.py \
        --env stage \
        --redirect-uri https://your-host/api/auth/callback

Save the printed client_id / client_secret / registration_access_token into .env.
"""

import argparse
import json
import sys

import httpx

AUTH_BASE = {
    "stage": "https://stage-auth.lambdatestinternal.com",
    "prod": "https://auth.lambdatest.com",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env", choices=["stage", "prod"], default="stage")
    p.add_argument(
        "--redirect-uri",
        required=True,
        action="append",
        dest="redirect_uris",
        help="HTTPS callback (repeatable). Must EXACTLY match AUTHPLUS_REDIRECT_URI.",
    )
    p.add_argument("--name", default="Browsercloud for Vercel")
    args = p.parse_args()

    body = {
        "client_name": args.name,
        "redirect_uris": args.redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_type": "confidential",
        "application_type": "web",
    }
    url = f"{AUTH_BASE[args.env]}/oauth2/register"
    r = httpx.post(url, json=body, timeout=20)
    print(f"POST {url} -> {r.status_code}", file=sys.stderr)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()
