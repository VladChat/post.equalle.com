# =========================================
# post_to_youtube.py (stub / preview)
# =========================================
from scripts.utils.cache_manager import next_unpublished
from scripts.utils.post_formatter import format_youtube
from scripts.utils.social_api import preview

PLATFORM = "youtube"

def main() -> None:
    post = next_unpublished(PLATFORM)
    if not post:
        print("ℹ️ No unpublished posts found (youtube).")
        return
    caption = format_youtube(post)
    preview(PLATFORM, caption)

if __name__ == "__main__":
    main()
