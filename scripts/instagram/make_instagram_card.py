# ============================================================
# File: make_instagram_card.py
# Purpose: Generate branded Instagram card with title overlay
# Author: eQualle Automation
# ============================================================

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .utils_instagram import parse_latest_from_cache, parse_latest_from_rss, shorten_title

# --- Resolve repo root robustly ---
# scripts/instagram/make_instagram_card.py -> parents[2] == repo root
ROOT = Path(__file__).resolve().parents[2]

# --- Inputs ---
CACHE_JSON = ROOT / "data" / "cache" / "latest_posts.json"
RSS_PATH   = ROOT / "data" / "cache" / "rss_feed.xml"   # optional fallback
TEMPLATE   = ROOT / "images" / "IG-1080-1350.jpg"
OUTPUT_DIR = ROOT / "images" / "ig"
FONT_PATH  = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def _load_latest():
    data = parse_latest_from_cache(CACHE_JSON)
    if data and data.get("title"):
        print(f"ℹ️ Source: latest_posts.json")
        return data
    if RSS_PATH.exists():
        print(f"ℹ️ Source: rss_feed.xml")
        return parse_latest_from_rss(RSS_PATH)
    raise FileNotFoundError("Neither data/cache/latest_posts.json nor data/cache/rss_feed.xml found. Ensure RSS Sync runs first.")

def main():
    latest = _load_latest()
    title = shorten_title(latest["title"])
    print(f"📰 Title: {title}")
    print(f"🔗 Link: {latest.get('link','')}")

    im = Image.open(TEMPLATE).convert("RGBA")
    W, H = im.size

    # ===== Glassy bottom panel with gradient =====
    overlay = Image.new("RGBA", im.size, (255,255,255,0))
    draw = ImageDraw.Draw(overlay)
    panel_height = int(H * 0.22)
    panel_y0 = H - panel_height
    for y in range(panel_height):
        # fade from transparent (top of panel) to 78% white at bottom
        alpha = int(200 * (y / max(panel_height,1)))
        draw.line([(0, panel_y0 + y), (W, panel_y0 + y)], fill=(255,255,255,alpha))

    # ===== Title text =====
    try:
        font_size = int(H * 0.05)
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception:
        font = ImageFont.load_default()
    text_color = (27, 53, 94, 255)   # #1B355E
    shadow_color = (0, 0, 0, 64)

    lines = title.split("\n")
    text_block = "\n".join(lines)

    # --- FIX: use modern method for Pillow >=11 ---
    try:
        bbox = draw.multiline_textbbox((0, 0), text_block, font=font, spacing=6)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        # fallback for older Pillow versions
        try:
            tw, th = draw.multiline_textsize(text_block, font=font, spacing=6)
        except Exception:
            tw, th = draw.textsize(text_block, font=font)

    text_x = (W - tw) / 2
    text_y = H - panel_height + (panel_height - th) / 2

    # --- Draw shadow and text ---
    draw.multiline_text((text_x+2, text_y+2), text_block, font=font, fill=shadow_color, align="center", spacing=6)
    draw.multiline_text((text_x, text_y), text_block, font=font, fill=text_color, align="center", spacing=6)

    combined = Image.alpha_composite(im, overlay)

    # ===== Rounded corners + soft drop shadow =====
    radius = 40
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0,0),(W,H)], radius=radius, fill=255)
    rounded = Image.new("RGBA", (W, H), (0,0,0,0))
    rounded.paste(combined, mask=mask)

    shadow = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W+10, H+10), (0,0,0,0))
    bg.paste(shadow, (5,5))
    bg.paste(rounded, (0,0), rounded)

    # ===== Save =====
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    safe_title = "-".join(title.lower().split())
    out_name = f"{date_tag}-{safe_title}.jpg"
    out_path = OUTPUT_DIR / out_name
    bg.convert("RGB").save(out_path, "JPEG", quality=90, optimize=True)

    public_url = f"https://post.equalle.com/images/ig/{out_name}"
    print(f"✅ Saved: {out_path}")
    print(f"🌐 Public URL: {public_url}")

if __name__ == "__main__":
    main()
