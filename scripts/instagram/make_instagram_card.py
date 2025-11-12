# ============================================================
# File: make_instagram_card.py
# Purpose: Generate branded IG card with full RSS title and glass-white panel
# Notes:
#  - Takes full post title from RSS (no shortening)
#  - Supports up to 4 lines; trims only if overflow
#  - Keeps white glass panel visible with gradient "Spice" text
# Author: eQualle Automation
# ============================================================

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .utils_instagram import parse_latest_from_cache, parse_latest_from_rss

# --- Resolve repo root robustly ---
ROOT = Path(__file__).resolve().parents[2]

# --- Inputs / Paths ---
CACHE_JSON = ROOT / "data" / "cache" / "latest_posts.json"
RSS_PATH   = ROOT / "data" / "cache" / "rss_feed.xml"   # optional fallback
TEMPLATE   = ROOT / "images" / "IG-1080-1350.jpg"
OUTPUT_DIR = ROOT / "images" / "ig"
FONT_PATH  = ROOT / "images" / "fonts" / "BungeeSpice-Regular.ttf"

# --- Visual configuration ---
PANEL_W_RATIO   = 0.85
PANEL_H_RATIO   = 0.35
PANEL_RADIUS    = 60
PANEL_FILL      = (255, 255, 255, 230)
PANEL_SHADOW    = (0, 0, 0, 45)
PANEL_SHADOW_BLUR = 18
TEXT_SPACING    = 5
FONT_SIZE_RATIO = 0.065
SAFE_PAD_X      = 60
MAX_LINES       = 4
VERTICAL_BIAS   = 2.6  # controls vertical offset (2.6 = slightly above center)

USE_GRADIENT_TEXT = True
GRAD_TOP = (255, 140, 64)   # orange
GRAD_BOT = (245, 210, 180)  # peach
TEXT_COLOR = (46, 46, 46, 255)
TEXT_SHADOW = (0, 0, 0, 60)

# ============================================================
# Helpers
# ============================================================

def _load_latest():
    """Load last post info from cache or RSS."""
    data = parse_latest_from_cache(CACHE_JSON)
    if data and data.get("title"):
        print("ℹ️ Source: latest_posts.json")
        return data
    if RSS_PATH.exists():
        print("ℹ️ Source: rss_feed.xml")
        return parse_latest_from_rss(RSS_PATH)
    raise FileNotFoundError("Neither latest_posts.json nor rss_feed.xml found. Run feed sync first.")

def _measure(draw, text, font, spacing):
    """Return width/height of multiline text."""
    try:
        box = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        return box[2] - box[0], box[3] - box[1]
    except AttributeError:
        return draw.textsize(text, font=font)

def _text_width(font, text):
    try:
        b = font.getbbox(text)
        return b[2] - b[0]
    except AttributeError:
        d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        return d.textlength(text, font=font)

def _wrap_text(words, font, max_width, max_lines):
    """Word wrap into max_lines, truncating last line with ellipsis if needed."""
    lines, current = [], ""
    i = 0
    while i < len(words):
        w = words[i]
        candidate = (current + " " + w).strip()
        if _text_width(font, candidate) <= max_width:
            current = candidate
            i += 1
        else:
            if current:
                lines.append(current)
                current = w
                i += 1
            else:
                cut = w
                while _text_width(font, cut + "…") > max_width and len(cut) > 1:
                    cut = cut[:-1]
                lines.append(cut + "…")
                i += 1
            if len(lines) == max_lines - 1:
                break
    remainder = " ".join(([current] if current else []) + words[i:])
    if remainder:
        if _text_width(font, remainder) <= max_width:
            lines.append(remainder)
        else:
            text = remainder
            while text and _text_width(font, text + "…") > max_width:
                text = text[:-1].rstrip()
            lines.append((text + "…") if text else "…")
    return lines[:max_lines]

def _draw_gradient_text(dest_img, text, xy, font, spacing):
    """Render gradient text using mask."""
    W, H = dest_img.size
    mask_layer = Image.new("L", (W, H), 0)
    mdraw = ImageDraw.Draw(mask_layer)
    mdraw.multiline_text(xy, text, font=font, fill=255, spacing=spacing, align="center")

    gradient = Image.new("RGBA", (W, H), 0)
    gdraw = ImageDraw.Draw(gradient)
    for y in range(H):
        t = y / max(H - 1, 1)
        r = int(GRAD_TOP[0] + (GRAD_BOT[0] - GRAD_TOP[0]) * t)
        g = int(GRAD_TOP[1] + (GRAD_BOT[1] - GRAD_TOP[1]) * t)
        b = int(GRAD_TOP[2] + (GRAD_BOT[2] - GRAD_TOP[2]) * t)
        gdraw.line([(0, y), (W, y)], fill=(r, g, b, 255))
    dest_img.paste(gradient, (0, 0), mask_layer)

# ============================================================
# Main
# ============================================================

def main():
    latest = _load_latest()
    title = latest["title"]  # 🔹 Use full title, not shortened
    print(f"📰 Title: {title}")
    print(f"🔗 Link: {latest.get('link','')}")

    base = Image.open(TEMPLATE).convert("RGBA")
    W, H = base.size

    # --- White glass panel ---
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    odraw = ImageDraw.Draw(overlay)

    pw, ph = int(W * PANEL_W_RATIO), int(H * PANEL_H_RATIO)
    x0, y0 = (W - pw) // 2, (H - ph) // 2
    x1, y1 = x0 + pw, y0 + ph

    # Shadow
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle([(x0 + 5, y0 + 8), (x1 + 5, y1 + 8)], radius=PANEL_RADIUS, fill=PANEL_SHADOW)
    shadow = shadow.filter(ImageFilter.GaussianBlur(PANEL_SHADOW_BLUR))
    overlay = Image.alpha_composite(shadow, overlay)

    # Panel body
    odraw.rounded_rectangle([(x0, y0), (x1, y1)], radius=PANEL_RADIUS, fill=PANEL_FILL)

    # Gloss
    gloss = Image.new("RGBA", base.size, (255, 255, 255, 0))
    gdraw = ImageDraw.Draw(gloss)
    for y in range(y0, y0 + int(ph * 0.5)):
        alpha = int(70 * (1 - (y - y0) / max(ph * 0.5, 1)))
        gdraw.line([(x0, y), (x1, y)], fill=(255, 255, 255, alpha))
    overlay = Image.alpha_composite(overlay, gloss)

    # Inner glow
    odraw.line([(x0 + 4, y0 + 4), (x1 - 4, y0 + 4)], fill=(255, 255, 255, 160), width=3)

    # --- Text ---
    try:
        font = ImageFont.truetype(str(FONT_PATH), int(W * FONT_SIZE_RATIO))
    except Exception as e:
        print(f"⚠️ Font load failed: {e}")
        font = ImageFont.load_default()

    max_text_width = pw - SAFE_PAD_X * 2
    words = title.split()
    lines = _wrap_text(words, font, max_text_width, MAX_LINES)
    text_block = "\n".join(lines)

    combined = Image.alpha_composite(base, overlay)

    # Text layer
    text_layer = Image.new("RGBA", combined.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)
    tw, th = _measure(tdraw, text_block, font, TEXT_SPACING)

    tx = (W - tw) / 2
    ty = y0 + (ph - th) / VERTICAL_BIAS

    # Shadow
    tdraw.multiline_text((tx + 2, ty + 2), text_block, font=font, fill=TEXT_SHADOW, spacing=TEXT_SPACING, align="center")

    # Main text
    if USE_GRADIENT_TEXT:
        _draw_gradient_text(text_layer, text_block, (tx, ty), font, TEXT_SPACING)
    else:
        tdraw.multiline_text((tx, ty), text_block, font=font, fill=TEXT_COLOR, spacing=TEXT_SPACING, align="center")

    combined = Image.alpha_composite(combined, text_layer)

    # Rounded corners + shadow
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (W, H)], radius=40, fill=255)
    rounded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded.paste(combined, mask=mask)

    shadow2 = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    bg.paste(shadow2, (5, 5))
    bg.paste(rounded, (0, 0), rounded)

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    safe_title = "-".join(title.lower().split())
    out_name = f"{date_tag}-{safe_title}.jpg"
    out_path = OUTPUT_DIR / out_name
    bg.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)

    print(f"✅ Saved: {out_path}")
    print(f"🌐 Public URL: https://post.equalle.com/images/ig/{out_name}")

if __name__ == "__main__":
    main()
