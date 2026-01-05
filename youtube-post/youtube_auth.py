# ============================================
# File: youtube-post/youtube_auth.py
# Purpose: OAuth2 access token helper for YouTube Data API (refresh token)
# Notes:
# - Uploading videos and posting comments require OAuth 2.0 user credentials.
# - API keys (YOUTUBE_API_KEY) do NOT have permission to upload/comment.
# ============================================

from __future__ import annotations

import os
from typing import Dict

import requests

DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_access_token() -> str:
    """Exchange refresh token for a short-lived access token."""
    client_id = (os.getenv("YOUTUBE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip()
    refresh_token = (os.getenv("YOUTUBE_REFRESH_TOKEN") or "").strip()
    token_uri = (os.getenv("YOUTUBE_TOKEN_URI") or DEFAULT_TOKEN_URI).strip()

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Missing OAuth credentials. Upload/comment require OAuth (refresh token). "
            "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN. "
            "Note: YOUTUBE_API_KEY alone cannot upload/comment."
        )

    data: Dict[str, str] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    resp = requests.post(token_uri, data=data, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    token = (payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError(f"OAuth token response missing access_token: {payload}")
    return token
