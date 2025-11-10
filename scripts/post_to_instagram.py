# =========================================
# post_to_instagram.py (stub / preview)
# Purpose:
#   - Demonstrate how a poster would read from shared cache
#   - Build an Instagram caption (preview only)
# =========================================
from scripts.utils.cache_manager import next_unpublished
from scripts.utils.post_formatter import format_instagram
from scripts.utils.social_api import preview

PLATFORM = "instagram"

def main() -> None:
    post = next_unpublished(PLATFORM)
    if not post:
        print("ℹ️ No unpublished posts found (instagram).")
        return
    caption = format_instagram(post)
    preview(PLATFORM, caption)

if __name__ == "__main__":
    main()
