import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.utils.cache_manager import next_unpublished
from scripts.utils.post_formatter import format_pinterest
from scripts.utils.social_api import preview

PLATFORM = "pinterest"

def main() -> None:
    post = next_unpublished(PLATFORM)
    if not post:
        print("ℹ️ No unpublished posts found (pinterest).")
        return
    caption = format_pinterest(post)
    preview(PLATFORM, caption)

if __name__ == "__main__":
    main()
