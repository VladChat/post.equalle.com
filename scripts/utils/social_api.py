import os
import requests

class FacebookAPI:
    def __init__(self) -> None:
        self.page_id = os.getenv("FB_PAGE_ID", "").strip()
        self.token = os.getenv("FB_PAGE_TOKEN", "").strip()
        if not self.page_id or not self.token:
            raise RuntimeError("FB_PAGE_ID/FB_PAGE_TOKEN not set in environment.")

    def publish(self, message: str, link: str | None = None):
        url = f"https://graph.facebook.com/{self.page_id}/feed"
        data = {"message": message, "access_token": self.token}
        if link:
            data["link"] = link
        resp = requests.post(url, data=data, timeout=30)
        return resp.ok, resp.text

def preview(platform: str, message: str) -> None:
    bar = "=" * 60
    print(f"[PREVIEW: {platform.upper()}]")
    print(bar)
    print(message)
    print(bar)
