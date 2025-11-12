# ============================================================
# File: make_instagram_card.py
# Purpose: Generate branded Instagram card with title overlay
# Author: eQualle Automation
# ============================================================

import os
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .utils_instagram import parse_latest_from_rss, shorten_title

ROOT = Path(__file__).resolve().parents[2]
RSS_PATH = ROOT / "data" / "cache" / "rss_feed.xml"
TEMPLATE = ROOT / "images" / "IG-1080-1350.jpg"
OUTPUT_DIR = ROOT / "images" / "ig"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def main():
    data = parse_latest_from_rss(RSS_PATH)
    title = shorten_title(data["title"])
    print(f"📰 Title: {title}")
    print(f"🔗 Source: {data['link']}")

    im = Image.open(TEMPLATE).convert("RGBA")
    W, H = im.size

    overlay = Image.new("RGBA", im.size, (255,255,255,0))
    draw = ImageDraw.Draw(overlay)
    panel_height = int(H * 0.22)
    panel_y0 = H - panel_height
    for y in range(panel_height):
        alpha = int(200 * (y / panel_height))
        draw.line([(0, panel_y0 + y), (W, panel_y0 + y)], fill=(255,255,255,alpha))

    font_size = int(H * 0.05)
    font = ImageFont.truetype(FONT_PATH, font_size)
    text_color = (27, 53, 94, 255)
    shadow_color = (0, 0, 0, 64)

    lines = title.split("\n")
    text_block = "\n".join(lines)
    tw, th = draw.multiline_textsize(text_block, font=font, spacing=6)
    text_x = (W - tw) / 2
    text_y = H - panel_height + (panel_height - th) / 2

    draw.multiline_text((text_x+2, text_y+2), text_block, font=font, fill=shadow_color, align="center", spacing=6)
    draw.multiline_text((text_x, text_y), text_block, font=font, fill=text_color, align="center", spacing=6)

    combined = Image.alpha_composite(im, overlay)

    radius = 40
    mask = Image.new("L", (W, H), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([(0,0),(W,H)], radius=radius, fill=255)
    rounded = Image.new("RGBA", (W, H), (0,0,0,0))
    rounded.paste(combined, mask=mask)

    shadow = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W+10, H+10), (0,0,0,0))
    bg.paste(shadow, (5,5))
    bg.paste(rounded, (0,0), rounded)

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
