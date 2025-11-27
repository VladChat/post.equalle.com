# ============================================
# File: blog-equalle/utils/http.py
# Purpose: Thin wrappers for HTTP requests (reserved for future use)
# ============================================

from __future__ import annotations

from typing import Any, Dict, Optional

import requests


def post_form(url: str, data: Dict[str, Any], timeout: int = 30) -> requests.Response:
    print(f"[http] POST(form) {url}")
    return requests.post(url, data=data, timeout=timeout)


def post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> requests.Response:
    print(f"[http] POST(json) {url}")
    return requests.post(url, json=payload, headers=headers, timeout=timeout)
