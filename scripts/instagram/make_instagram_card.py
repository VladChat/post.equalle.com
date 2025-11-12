# ============================================================
# File: make_instagram_card.py
# Purpose: Generate branded IG card with centered glass-white title panel
# Notes:
#  - Supports up to 4 lines. Last line ellipsizes ("…") if overflow.
#  - Simulates "Bungee Spice" color look via gradient fill over text mask.
# Author: eQualle Automation
# ============================================================

from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .utils_instagram import parse_latest_from_cache, parse_latest_from_rss, shorten_title

# --- Resolve repo root robustly ---
ROOT = Path(__file__).resolve().parents[2]

# --- Inputs / Paths ---
CACHE_JSON = ROOT / "data" / "cache" / "latest_posts.json"
RSS_PATH   = ROOT / "data" / "cache" / "rss_feed.xml"   # optional fallback
TEMPLATE   = ROOT / "images" / "IG-1080-1350.jpg"
OUTPUT_DIR = ROOT / "images" / "ig"
# Your uploaded font:
FONT_PATH  = ROOT / "images" / "fonts" / "BungeeSpice-Regular.ttf"

# --- Visual config ---
PANEL_W_RATIO   = 0.85
PANEL_H_RATIO   = 0.35
PANEL_RADIUS    = 60
PANEL_FILL      = (255, 255, 255, 230)
PANEL_SHADOW    = (0, 0, 0, 45)
PANEL_SHADOW_BLUR = 18
TEXT_COLOR      = (46, 46, 46, 255)  # used if gradient disabled
TEXT_SHADOW     = (0, 0, 0, 60)
TEXT_SPACING    = 5
FONT_SIZE_RATIO = 0.065              # relative to canvas width
SAFE_PAD_X      = 60                 # inner left/right padding inside the panel
MAX_LINES       = 4
# Position text a bit above exact center of the panel:
VERTICAL_BIAS   = 2.6                # bigger -> higher

# Enable simulated "Spice" gradient fill for text
USE_GRADIENT_TEXT = True
# Gradient top->bottom colors (tweak to taste)
GRAD_TOP = (255, 140, 64)   # warm orange
GRAD_BOT = (245, 210, 180)  # light peach

def _load_latest():
    data = parse_latest_from_cache(CACHE_JSON)
    if data and data.get("title"):
        print("ℹ️ Source: latest_posts.json")
        return data
    if RSS_PATH.exists():
        print("ℹ️ Source: rss_feed.xml")
        return parse_latest_from_rss(RSS_PATH)
    raise FileNotFoundError("Neither latest_posts.json nor rss_feed.xml found. Run the feed step first.")

def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, spacing: int):
    try:
        bx0, by0, bx1, by1 = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        return bx1 - bx0, by1 - by0
    except AttributeError:
        # Fallback for older Pillow
        return draw.textsize(text, font=font)

def _text_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    try:
        b = font.getbbox(text)
        return b[2] - b[0]
    except AttributeError:
        # very old Pillow fallback
        d = ImageDraw.Draw(Image.new("RGBA", (10,10)))
        return d.textlength(text, font=font)

def _wrap_with_ellipsis(words, font, max_width, max_lines=4):
    """
    Greedy word-wrap into at most max_lines.
    If content exceeds max_lines, squeeze last line with trailing ellipsis.
    Returns list[str].
    """
    lines = []
    current = ""
    i = 0
    while i < len(words):
        w = words[i]
        candidate = (current + " " + w).strip()
        if _text_width(font, candidate) <= max_width:
            current = candidate
            i += 1
        else:
            # commit current line
            if current:
                lines.append(current)
                current = w  # start next line with the word that didn't fit
                i += 1
            else:
                # single very long word: hard cut with ellipsis
                cut = w
                while _text_width(font, cut + "…") > max_width and len(cut) > 1:
                    cut = cut[:-1]
                lines.append(cut + "…")
                i += 1
            if len(lines) == max_lines - 1:
                # next will be the last line; break loop to pack remainder into it
                break

    # put remaining words into last line (or start it)
    remainder = " ".join(([current] if current else []) + words[i:])
    if remainder:
        # fit remainder into last line with ellipsis if needed
        text = remainder.strip()
        if _text_width(font, text) <= max_width:
            lines.append(text)
        else:
            # shrink with ellipsis
            while text and _text_width(font, text + "…") > max_width:
                text = text[:-1].rstrip()
            lines.append((text + "…") if text else "…")
    # ensure we don't exceed max_lines
    return lines[:max_lines]

def _draw_gradient_text(dest_img, text, xy, font, spacing):
    """Render text as gradient by using text as a mask."""
    W, H = dest_img.size
    # 1) Make text mask
    mask_layer = Image.new("L", (W, H), 0)
    mdraw = ImageDraw.Draw(mask_layer)
    mdraw.multiline_text(xy, text, font=font, fill=255, spacing=spacing, align="center")

    # 2) Build vertical gradient image
    grad = Image.new("RGBA", (W, H), 0)
    gdraw = ImageDraw.Draw(grad)
    # Only draw gradient in the text area vertically to save time (optional)
    # Simple linear interpolation
    for y in range(H):
        t = y / max(H - 1, 1)
        r = int(GRAD_TOP[0] + (GRAD_BOT[0] - GRAD_TOP[0]) * t)
        g = int(GRAD_TOP[1] + (GRAD_BOT[1] - GRAD_TOP[1]) * t)
        b = int(GRAD_TOP[2] + (GRAD_BOT[2] - GRAD_TOP[2]) * t)
        gdraw.line([(0, y), (W, y)], fill=(r, g, b, 255))
    # 3) Composite gradient through mask onto destination
    dest_img.paste(grad, (0, 0), mask_layer)

def main():
    latest = _load_latest()
    title = shorten_title(latest["title"])
    print(f"📰 Title: {title}")
    print(f"🔗 Link: {latest.get('link','')}")

    base = Image.open(TEMPLATE).convert("RGBA")
    W, H = base.size

    # ===== White glass panel =====
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    odraw = ImageDraw.Draw(overlay)

    pw = int(W * PANEL_W_RATIO)
    ph = int(H * PANEL_H_RATIO)
    x0 = (W - pw) // 2
    y0 = (H - ph) // 2
    x1 = x0 + pw
    y1 = y0 + ph

    # soft shadow
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle([(x0 + 5, y0 + 8), (x1 + 5, y1 + 8)], radius=PANEL_RADIUS, fill=PANEL_SHADOW)
    shadow = shadow.filter(ImageFilter.GaussianBlur(PANEL_SHADOW_BLUR))
    overlay = Image.alpha_composite(shadow, overlay)

    # panel
    odraw.rounded_rectangle([(x0, y0), (x1, y1)], radius=PANEL_RADIUS, fill=PANEL_FILL)

    # glossy top highlight
    gloss = Image.new("RGBA", base.size, (255, 255, 255, 0))
    gdraw = ImageDraw.Draw(gloss)
    for y in range(y0, y0 + int(ph * 0.5)):
        alpha = int(70 * (1 - (y - y0) / max(ph * 0.5, 1)))
        gdraw.line([(x0, y), (x1, y)], fill=(255, 255, 255, alpha))
    overlay = Image.alpha_composite(overlay, gloss)

    # inner top glow line
    odraw.line([(x0 + 4, y0 + 4), (x1 - 4, y0 + 4)], fill=(255, 255, 255, 160), width=3)

    # ===== Text prep =====
    try:
        font = ImageFont.truetype(str(FONT_PATH), int(W * FONT_SIZE_RATIO))
    except Exception as e:
        print(f"⚠️ Font load failed: {e}")
        font = ImageFont.load_default()

    max_text_width = pw - SAFE_PAD_X * 2
    words = title.split()
    lines = _wrap_with_ellipsis(words, font, max_text_width, max_lines=MAX_LINES)
    text_block = "\n".join(lines)

    # Combine panel with base before drawing text
    composed = Image.alpha_composite(base, overlay)

    # Separate layer for text (so it's above the glass)
    text_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)

    # Measure final text block
    tw, th = _measure(tdraw, text_block, font, TEXT_SPACING)

    # Position: a bit above the exact vertical center of the panel
    tx = (W - tw) / 2
    ty = y0 + (ph - th) / VERTICAL_BIAS

    # Text shadow first
    tdraw.multiline_text((tx + 2, ty + 2), text_block, font=font, fill=TEXT_SHADOW, spacing=TEXT_SPACING, align="center")

    # Main text: gradient or solid color
    if USE_GRADIENT_TEXT:
        _draw_gradient_text(text_layer, text_block, (tx, ty), font, TEXT_SPACING)
    else:
        tdraw.multiline_text((tx, ty), text_block, font=font, fill=TEXT_COLOR, spacing=TEXT_SPACING, align="center")

    # Merge text over panel
    composed = Image.alpha_composite(composed, text_layer)

    # Global rounded corners + soft outer shadow
    radius = 40
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (W, H)], radius=radius, fill=255)
    rounded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded.paste(composed, mask=mask)

    outer_shadow = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    bg.paste(outer_shadow, (5, 5))
    bg.paste(rounded, (0, 0), rounded)

    # Save
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
