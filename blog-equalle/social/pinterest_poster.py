# ============================================
# File: blog-equalle/social/pinterest_poster.py
# Purpose: Publish pin to Pinterest via v5 API
# ============================================

from __future__ import annotations

import base64
import os
from typing import Any, Dict

import requests

PINTEREST_API_BASE = "https://api.pinterest.com/v5"
PINTEREST_OAUTH_TOKEN_URL = f"{PINTEREST_API_BASE}/oauth/token"
PINTEREST_OAUTH_SCOPES = "boards:read,boards:write,pins:read,pins:write"


class PinterestConfigError(Exception):
    """Raised when Pinterest configuration (env) is invalid."""

    pass


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _handoff_rotated_refresh_token(rotated_token: str) -> None:
    """
    Pinterest continuous refresh rotates the refresh token: each refresh
    response carries a new refresh_token, and the stored secret must be
    replaced with it or it will eventually expire (the cause of the original
    401 code 28 failure).

    The new value is written to the file named by
    PINTEREST_ROTATED_REFRESH_TOKEN_FILE so the workflow can persist it as the
    PINTEREST_REFRESH_TOKEN_EQUALLE secret. The token itself is never printed.
    """

    path = _env("PINTEREST_ROTATED_REFRESH_TOKEN_FILE")
    if not path:
        print(
            "[pin][auth][WARN] Pinterest issued a rotated refresh token but "
            "PINTEREST_ROTATED_REFRESH_TOKEN_FILE is not set; update the "
            "PINTEREST_REFRESH_TOKEN_EQUALLE secret before the stored token expires. "
            "(Token value not logged.)"
        )
        return

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(rotated_token)
    print("[pin][auth] Rotated refresh token handed off for secret update.")


def _refresh_access_token() -> str:
    """
    Get a fresh access token via the user OAuth refresh_token flow.

    Expected env (GitHub Secrets) for eQualle:
      - PINTEREST_CLIENT_ID_EQUALLE
      - PINTEREST_CLIENT_SECRET_EQUALLE
      - PINTEREST_REFRESH_TOKEN_EQUALLE

    Backward-compatible fallbacks:
      - PINTEREST_CLIENT_ID
      - PINTEREST_CLIENT_SECRET
      - PINTEREST_REFRESH_TOKEN
    """

    client_id = _env("PINTEREST_CLIENT_ID_EQUALLE") or _env("PINTEREST_CLIENT_ID")
    client_secret = _env("PINTEREST_CLIENT_SECRET_EQUALLE") or _env("PINTEREST_CLIENT_SECRET")
    refresh_token = _env("PINTEREST_REFRESH_TOKEN_EQUALLE") or _env("PINTEREST_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        return ""

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    resp = requests.post(
        PINTEREST_OAUTH_TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )

    if resp.status_code != 200:
        raise PinterestConfigError(f"[pin][auth] refresh failed: {resp.status_code} {resp.text}")

    data = resp.json()
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise PinterestConfigError("[pin][auth] refresh response missing access_token")

    rotated = str(data.get("refresh_token") or "").strip()
    if rotated and rotated != refresh_token:
        _handoff_rotated_refresh_token(rotated)

    return token


def _get_access_token() -> str:
    """
    Publishing requires a user OAuth access token obtained via the
    refresh-token flow (scopes: boards:read,boards:write,pins:read,pins:write).

    Static access tokens generated in the Pinterest developer dashboard are
    read-only under Standard access and cannot create Pins, so they are
    intentionally NOT accepted as a publishing credential. client_credentials
    tokens are likewise rejected by the Pins API and are not used.
    """

    token = _refresh_access_token()
    if token:
        return token

    raise PinterestConfigError(
        "Pinterest publishing credentials missing. Set PINTEREST_CLIENT_ID_EQUALLE, "
        "PINTEREST_CLIENT_SECRET_EQUALLE and PINTEREST_REFRESH_TOKEN_EQUALLE (user OAuth "
        "refresh token from blog-equalle/social/pinterest_oauth.py). Dashboard-generated "
        "static access tokens are read-only and cannot create Pins."
    )


def publish_pinterest_pin(payload: Dict[str, Any], board_id: str) -> str:
    """
    Creates a pin using prepared payload and explicit board_id.

    Expected payload structure (from utils.text_builder.build_pinterest_payload):
      {
        "title": "...",
        "description": "...",
        "link": "https://blog.equalle.com/....",
        "media_source": {
          "source_type": "image_url",
          "url": "https://blog.equalle.com/..."
        }
      }

    We add:
      - board_id
    """

    if not board_id:
        raise ValueError("publish_pinterest_pin() requires non-empty board_id")

    access_token = _get_access_token()

    # Не мутируем исходный dict на всякий случай
    body: Dict[str, Any] = dict(payload)
    body["board_id"] = board_id

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"{PINTEREST_API_BASE}/pins"
    print(f"[pin][poster] POST {url}")
    print(f"[pin][poster] Payload keys: {list(body.keys())}")

    response = requests.post(url, json=body, headers=headers, timeout=30)

    if not response.ok:
        raise RuntimeError(f"[pin][poster] Pinterest API error: {response.status_code} {response.text}")

    data = response.json()
    pin_id = str(data.get("id") or "")
    print(f"[pin][poster] Response: {data}")
    return pin_id
