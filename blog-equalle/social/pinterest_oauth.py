# ============================================
# File: blog-equalle/social/pinterest_oauth.py
# Purpose: One-time (re-runnable) Pinterest user OAuth login for eQualle.
#   Produces the continuous refresh token that the RSS → Pinterest Pin
#   workflow uses for publishing. The token is never printed; it is stored
#   directly as the GitHub secret PINTEREST_REFRESH_TOKEN_EQUALLE via gh.
#
# Usage (normally via .github/workflows/pinterest-oauth-bootstrap.yml):
#   1) python blog-equalle/social/pinterest_oauth.py --print-url
#      Needs ONLY PINTEREST_CLIENT_ID_EQUALLE (never the client secret).
#      Prints the consent URL plus the generated `state` value.
#   2) python blog-equalle/social/pinterest_oauth.py \
#          --exchange "<full redirect URL>" [--expected-state <state>]
#      Needs PINTEREST_CLIENT_ID_EQUALLE and PINTEREST_CLIENT_SECRET_EQUALLE.
#
# State handling (cross-run CSRF check, operator-mediated): --print-url
# generates a random state and prints it; the consent redirect echoes it in
# the URL. Passing that value back via --expected-state makes the exchange
# fail on mismatch. If --expected-state is omitted, NO state validation
# happens — there is no hidden persistence between the two invocations.
# ============================================

from __future__ import annotations

import argparse
import base64
import os
import secrets as _secrets
import subprocess
import sys
from typing import Dict
from urllib.parse import parse_qs, urlencode, urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social.pinterest_poster import (  # noqa: E402
    PINTEREST_OAUTH_SCOPES,
    PINTEREST_OAUTH_TOKEN_URL,
    PinterestConfigError,
    _env,
)

PINTEREST_AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
REDIRECT_URI = "https://post.equalle.com/pinterest/oauth/pinterest"
SECRET_NAME = "PINTEREST_REFRESH_TOKEN_EQUALLE"
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY") or "VladChat/post.equalle.com"


def _client_id() -> str:
    client_id = _env("PINTEREST_CLIENT_ID_EQUALLE") or _env("PINTEREST_CLIENT_ID")
    if not client_id:
        raise PinterestConfigError("Set PINTEREST_CLIENT_ID_EQUALLE first.")
    return client_id


def _client_credentials() -> tuple[str, str]:
    client_id = _client_id()
    client_secret = _env("PINTEREST_CLIENT_SECRET_EQUALLE") or _env("PINTEREST_CLIENT_SECRET")
    if not client_secret:
        raise PinterestConfigError("Set PINTEREST_CLIENT_SECRET_EQUALLE first.")
    return client_id, client_secret


def build_authorization_url(client_id: str, state: str) -> str:
    return PINTEREST_AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": PINTEREST_OAUTH_SCOPES,
            "state": state,
        }
    )


def extract_code(redirect_url_or_code: str, expected_state: str = "") -> str:
    """Accepts either the raw authorization code or the full redirect URL."""
    value = redirect_url_or_code.strip()
    if "://" not in value:
        return value
    query = parse_qs(urlparse(value).query)
    if expected_state:
        state = (query.get("state") or [""])[0]
        if state != expected_state:
            raise PinterestConfigError(
                "OAuth state mismatch: the redirect URL does not belong to the "
                "authorize run that produced the expected state. Restart the flow."
            )
    code = (query.get("code") or [""])[0]
    if not code:
        raise PinterestConfigError("No ?code= parameter found in the provided URL.")
    return code


def exchange_authorization_code(code: str) -> Dict[str, str]:
    client_id, client_secret = _client_credentials()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    resp = requests.post(
        PINTEREST_OAUTH_TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "continuous_refresh": "true",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise PinterestConfigError(
            f"[pin][oauth] code exchange failed: {resp.status_code} {resp.text}"
        )
    return resp.json()


def store_refresh_token_as_secret(refresh_token: str) -> None:
    """Pipes the token to `gh secret set`; the value is never printed."""
    result = subprocess.run(
        ["gh", "secret", "set", SECRET_NAME, "--repo", GITHUB_REPO],
        input=refresh_token.encode("utf-8"),
        capture_output=True,
    )
    if result.returncode != 0:
        raise PinterestConfigError(
            "gh secret set failed (token NOT stored, NOT printed): "
            + result.stderr.decode("utf-8", "replace").strip()
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--print-url", action="store_true", help="Print the consent URL.")
    action.add_argument("--exchange", metavar="URL_OR_CODE", help="Redirect URL or code.")
    parser.add_argument(
        "--expected-state",
        default="",
        help="State value printed by --print-url; enables cross-run state validation.",
    )
    args = parser.parse_args()

    if args.print_url:
        state = _secrets.token_urlsafe(24)
        print("Open this URL, approve access, then copy the URL you land on:")
        print(build_authorization_url(_client_id(), state))
        print(f"State (pass back via --expected-state to validate): {state}")
        return

    code = extract_code(args.exchange, args.expected_state)
    if not args.expected_state:
        print("[pin][oauth][WARN] No --expected-state provided; state NOT validated.")
    data = exchange_authorization_code(code)

    refresh_token = str(data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise PinterestConfigError(
            "[pin][oauth] token response contained no refresh_token; "
            "response keys: " + ", ".join(sorted(data.keys()))
        )

    store_refresh_token_as_secret(refresh_token)
    print(f"[pin][oauth] Stored refresh token as GitHub secret {SECRET_NAME}.")
    print(f"[pin][oauth] Granted scopes: {data.get('scope', '(not reported)')}")


if __name__ == "__main__":
    main()
