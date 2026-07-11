# ============================================
# File: blog-equalle/social/pinterest_oauth.py
# Purpose: One-time (re-runnable) Pinterest user OAuth login for eQualle.
#   Produces the continuous refresh token that the RSS → Pinterest Pin
#   workflow uses for publishing. The token is never printed; it is stored
#   directly as the GitHub secret PINTEREST_REFRESH_TOKEN_EQUALLE via gh.
# Usage:
#   1) python blog-equalle/social/pinterest_oauth.py --print-url
#      Open the printed URL in a browser, approve the consent screen, then
#      copy the full URL of the page you land on
#      (https://post.equalle.com/pinterest/oauth/pinterest?code=...).
#   2) python blog-equalle/social/pinterest_oauth.py --exchange "<that full URL>"
# Env:
#   PINTEREST_CLIENT_ID_EQUALLE / PINTEREST_CLIENT_SECRET_EQUALLE
#   (falls back to PINTEREST_CLIENT_ID / PINTEREST_CLIENT_SECRET)
# ============================================

from __future__ import annotations

import argparse
import base64
import os
import secrets as _secrets
import subprocess
import sys
import tempfile
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
GITHUB_REPO = "VladChat/post.equalle.com"
_STATE_FILE = os.path.join(tempfile.gettempdir(), "pinterest_oauth_state_equalle")


def _client_credentials() -> tuple[str, str]:
    client_id = _env("PINTEREST_CLIENT_ID_EQUALLE") or _env("PINTEREST_CLIENT_ID")
    client_secret = _env("PINTEREST_CLIENT_SECRET_EQUALLE") or _env("PINTEREST_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise PinterestConfigError(
            "Set PINTEREST_CLIENT_ID_EQUALLE and PINTEREST_CLIENT_SECRET_EQUALLE first."
        )
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
    state = (query.get("state") or [""])[0]
    if expected_state and state and state != expected_state:
        raise PinterestConfigError("OAuth state mismatch; restart with --print-url.")
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
    args = parser.parse_args()

    if args.print_url:
        client_id, _ = _client_credentials()
        state = _secrets.token_urlsafe(24)
        with open(_STATE_FILE, "w", encoding="utf-8") as fh:
            fh.write(state)
        print("Open this URL, approve access, then copy the URL you land on:")
        print(build_authorization_url(client_id, state))
        return

    expected_state = ""
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, encoding="utf-8") as fh:
            expected_state = fh.read().strip()

    code = extract_code(args.exchange, expected_state)
    data = exchange_authorization_code(code)

    refresh_token = str(data.get("refresh_token") or "").strip()
    if not refresh_token:
        raise PinterestConfigError(
            "[pin][oauth] token response contained no refresh_token; "
            "response keys: " + ", ".join(sorted(data.keys()))
        )

    store_refresh_token_as_secret(refresh_token)
    if os.path.exists(_STATE_FILE):
        os.remove(_STATE_FILE)
    print(f"[pin][oauth] Stored refresh token as GitHub secret {SECRET_NAME}.")
    print(f"[pin][oauth] Granted scopes: {data.get('scope', '(not reported)')}")


if __name__ == "__main__":
    main()
