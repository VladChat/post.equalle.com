# =========================================
# post_to_facebook.py
# Purpose:
#   - Pick the next unpublished cached post
#   - Build Facebook caption
#   - Either preview (MODE=dev) or publish (MODE=prod)
# Env:
#   - MODE: dev|prod (default dev = safe preview)
#   - FB_PAGE_ID, FB_PAGE_TOKEN (required in prod)
# =========================================
import os
from scripts.utils.cache_manager import next_unpublished, mark_published
from scripts.utils.post_formatter import format_facebook
from scripts.utils.social_api import FacebookAPI, preview

PLATFORM = "facebook"

def main() -> None:
    mode = os.getenv("MODE", "dev").lower().strip()
    is_prod = mode == "prod"

    # 1) Load the next item not yet posted to this platform
    post = next_unpublished(PLATFORM)
    if not post:
        print("ℹ️ No unpublished posts found in cache.")
        return

    # 2) Build caption for Facebook
    caption = format_facebook(post)

    if not is_prod:
        # Safe preview: prints caption to logs (no API call)
        preview(PLATFORM, caption)
        return

    # 3) Real publish (prod)
    api = FacebookAPI()
    ok, resp = api.publish(message=caption, link=post.get("link"))
    if ok:
        mark_published(PLATFORM, post.get("link", ""))
        print("✅ Published to Facebook.")
    else:
        print("❌ Failed to publish to Facebook:")
        print(resp)

if __name__ == "__main__":
    main()
