# =========================================
# post_to_twitter.py (stub / preview)
# =========================================
from scripts.utils.cache_manager import next_unpublished
from scripts.utils.post_formatter import format_twitter
from scripts.utils.social_api import preview

PLATFORM = "twitter"

def main() -> None:
    post = next_unpublished(PLATFORM)
    if not post:
        print("ℹ️ No unpublished posts found (twitter).")
        return
    caption = format_twitter(post)
    preview(PLATFORM, caption)

if __name__ == "__main__":
    main()
