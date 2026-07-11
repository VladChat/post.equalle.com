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
PINTEREST_CLIENT_CREDENTIALS_SCOPES = "boards:read,boards:write,pins:read,pins:write"


class PinterestConfigError(Exception):
    """Raised when Pinterest configuration (env) is invalid."""

    pass


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _refresh_access_token() -> str:
    """
    Preferred: get a fresh access token via refresh_token flow.

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

    return token


def _client_credentials_access_token() -> str:
    """
    Unattended app-owner flow: get an access token via client_credentials.

    Pinterest supports client_credentials for apps creating Pins on the
    app owner's own account, which fits this scheduled job (no rotated
    refresh token to persist between runs).

    Expected env (GitHub Secrets) for eQualle:
      - PINTEREST_CLIENT_ID_EQUALLE
      - PINTEREST_CLIENT_SECRET_EQUALLE

    Backward-compatible fallbacks:
      - PINTEREST_CLIENT_ID
      - PINTEREST_CLIENT_SECRET
    """

    client_id = _env("PINTEREST_CLIENT_ID_EQUALLE") or _env("PINTEREST_CLIENT_ID")
    client_secret = _env("PINTEREST_CLIENT_SECRET_EQUALLE") or _env("PINTEREST_CLIENT_SECRET")

    if not (client_id and client_secret):
        return ""

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    resp = requests.post(
        PINTEREST_OAUTH_TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": PINTEREST_CLIENT_CREDENTIALS_SCOPES,
        },
        timeout=30,
    )

    if resp.status_code != 200:
        raise PinterestConfigError(
            f"[pin][auth] client_credentials failed: {resp.status_code} {resp.text}"
        )

    data = resp.json()
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise PinterestConfigError("[pin][auth] client_credentials response missing access_token")

    return token


def _get_access_token() -> str:
    """
    Access token resolution order:

    1) Refresh-token flow, only when a refresh token is explicitly configured:
       - PINTEREST_CLIENT_ID_EQUALLE / PINTEREST_CLIENT_ID
       - PINTEREST_CLIENT_SECRET_EQUALLE / PINTEREST_CLIENT_SECRET
       - PINTEREST_REFRESH_TOKEN_EQUALLE / PINTEREST_REFRESH_TOKEN

    2) client_credentials flow (unattended app-owner publishing):
       - PINTEREST_CLIENT_ID_EQUALLE / PINTEREST_CLIENT_ID
       - PINTEREST_CLIENT_SECRET_EQUALLE / PINTEREST_CLIENT_SECRET

    3) Static tokens (legacy fallback):
       - PINTEREST_ACCESS_TOKEN_EQUALLE
       - PINTEREST_ACCESS_TOKEN
       - PINTEREST_TOKEN
    """

    oauth_errors = []

    try:
        token = _refresh_access_token()
        if token:
            return token
    except PinterestConfigError as exc:
        oauth_errors.append(str(exc))

    try:
        token = _client_credentials_access_token()
        if token:
            return token
    except PinterestConfigError as exc:
        oauth_errors.append(str(exc))

    token = _env("PINTEREST_ACCESS_TOKEN_EQUALLE")
    if not token:
        token = _env("PINTEREST_ACCESS_TOKEN")
    if not token:
        token = _env("PINTEREST_TOKEN")

    if not token:
        raise PinterestConfigError(
            "Pinterest token not found. "
            "Set client secrets (PINTEREST_CLIENT_ID_EQUALLE, PINTEREST_CLIENT_SECRET_EQUALLE) for "
            "client_credentials, optionally PINTEREST_REFRESH_TOKEN_EQUALLE for the refresh flow, "
            "or set PINTEREST_ACCESS_TOKEN_EQUALLE/PINTEREST_ACCESS_TOKEN."
            + (" OAuth errors: " + " | ".join(oauth_errors) if oauth_errors else "")
        )

    return token


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
