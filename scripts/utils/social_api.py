import os
import requests
from typing import Tuple

# ==========================================================
# social_api.py
# Platform adapters. Facebook is fully implemented.
# Others use preview mode (print to logs).
# ==========================================================

class FacebookAPI:
    """Minimal adapter for Facebook Page publishing via Graph API."""
    def __init__(self) -> None:
        self.page_id = os.getenv("FB_PAGE_ID", "").strip()
        self.token = os.getenv("FB_PAGE_TOKEN", "").strip()
        if not self.page_id or not self.token:
            raise RuntimeError("FB_PAGE_ID/FB_PAGE_TOKEN not set in environment.")

    def publish(self, message: str, link: str | None = None) -> Tuple[bool, str]:
        """Publish a text post (optionally with link preview)."""
        url = f"https://graph.facebook.com/{self.page_id}/feed"
        data = {"message": message, "access_token": self.token}
        if link:
            data["link"] = link
        resp = requests.post(url, data=data, timeout=30)
        return resp.ok, resp.text

def preview(platform: str, message: str) -> None:
    """Console preview used by non-prod mode or unimplemented platforms."""
    bar = "=" * 60
    print(f"🧩 [PREVIEW: {platform.upper()}]")
    print(bar)
    print(message)
    print(bar)
