# ============================================================
# File: make_instagram_card.py
# Purpose: Generate branded Instagram card with centered glass-white title panel
# Author: eQualle Automation
# ============================================================

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

from .utils_instagram import parse_latest_from_cache, parse_latest_from_rss, shorten_title

# --- Resolve repo root robustly ---
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

    # --- Open base image ---
    im = Image.open(TEMPLATE).convert("RGBA")
    W, H = im.size

    # === Create overlay for the white glass panel ===
    overlay = Image.new("RGBA", im.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    panel_width = int(W * 0.85)
    panel_height = int(H * 0.35)
    panel_x0 = (W - panel_width) // 2
    panel_y0 = (H - panel_height) // 2
    panel_x1 = panel_x0 + panel_width
    panel_y1 = panel_y0 + panel_height

    # White base with transparency
    draw.rounded_rectangle(
        [(panel_x0, panel_y0), (panel_x1, panel_y1)],
        radius=60,
        fill=(255, 255, 255, 230)
    )

    # Soft drop shadow below panel
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        [(panel_x0 + 5, panel_y0 + 8), (panel_x1 + 5, panel_y1 + 8)],
        radius=60,
        fill=(0, 0, 0, 45)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    overlay = Image.alpha_composite(shadow, overlay)

    # Glossy highlight (top half gradient)
    gloss = Image.new("RGBA", im.size, (255, 255, 255, 0))
    gdraw = ImageDraw.Draw(gloss)
    for y in range(panel_y0, panel_y0 + int(panel_height * 0.5)):
        alpha = int(70 * (1 - (y - panel_y0) / (panel_height * 0.5)))
        gdraw.line([(panel_x0, y), (panel_x1, y)], fill=(255, 255, 255, alpha))
    overlay = Image.alpha_composite(overlay, gloss)

    # Inner top glow line
    draw.line([(panel_x0 + 4, panel_y0 + 4), (panel_x1 - 4, panel_y0 + 4)], fill=(255,255,255,160), width=3)

    # === Text settings ===
    try:
        font_size = int(W * 0.07)
        font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception:
        font = ImageFont.load_default()

    text_color = (27, 53, 94, 255)  # brand navy
    shadow_color = (0, 0, 0, 80)

    # Text wrapping into max 3 lines
    words = title.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        try:
            bbox = font.getbbox(test_line)
            w = bbox[2] - bbox[0]
        except AttributeError:
            w, _ = font.getsize(test_line)
        if w < panel_width - 200:  # 100px padding each side
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
        if len(lines) >= 3:
            break
    if current_line and len(lines) < 3:
        lines.append(current_line)

    text_block = "\n".join(lines)

    # === Combine panel overlay with base image first ===
    combined = Image.alpha_composite(im, overlay)

    # === Create separate text layer (so text is drawn above the glass) ===
    text_layer = Image.new("RGBA", combined.size, (255, 255, 255, 0))
    tdraw = ImageDraw.Draw(text_layer)

    # Compute text size (modern API)
    try:
        bbox = tdraw.multiline_textbbox((0, 0), text_block, font=font, spacing=8)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = tdraw.textsize(text_block, font=font)

    text_x = (W - tw) / 2
    text_y = (H - th) / 2  # centered vertically (inside white panel)

    # Draw text shadow
    tdraw.multiline_text(
        (text_x + 2, text_y + 2), text_block,
        font=font, fill=shadow_color, align="center", spacing=8
    )

    # Draw main text (on top of panel)
    tdraw.multiline_text(
        (text_x, text_y), text_block,
        font=font, fill=text_color, align="center", spacing=8
    )

    # Merge text layer on top of glass panel
    combined = Image.alpha_composite(combined, text_layer)

    # === Rounded corners for entire image + soft global shadow ===
    radius = 40
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (W, H)], radius=radius, fill=255)
    rounded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded.paste(combined, mask=mask)

    soft_shadow = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    bg.paste(soft_shadow, (5, 5))
    bg.paste(rounded, (0, 0), rounded)

    # === Save result ===
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    safe_title = "-".join(title.lower().split())
    out_name = f"{date_tag}-{safe_title}.jpg"
    out_path = OUTPUT_DIR / out_name
    bg.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)

    public_url = f"https://post.equalle.com/images/ig/{out_name}"
    print(f"✅ Saved: {out_path}")
    print(f"🌐 Public URL: {public_url}")

if __name__ == "__main__":
    main()
