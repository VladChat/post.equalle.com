import os
import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.cache_manager import next_unpublished, mark_published
from scripts.utils.post_formatter import format_facebook
from scripts.utils.social_api import FacebookAPI, preview

PLATFORM = "facebook"

def main() -> None:
    mode = os.getenv("MODE", "dev").lower().strip()
    is_prod = mode == "prod"

    post = next_unpublished(PLATFORM)
    if not post:
        print("ℹ️ No unpublished posts found in cache.")
        return

    caption = format_facebook(post)

    if not is_prod:
        preview(PLATFORM, caption)
        return

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
