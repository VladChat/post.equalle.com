# ============================================================
# File: make_instagram_card.py
# Purpose: Render IG card using ready-made template with built-in panel
# Author: eQualle Automation
# ============================================================

from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .utils_instagram import parse_latest_from_cache, parse_latest_from_rss

# --- Resolve repo root robustly ---
ROOT = Path(__file__).resolve().parents[2]

# --- Inputs / Paths ---
CACHE_JSON = ROOT / "data" / "cache" / "latest_posts.json"
RSS_PATH   = ROOT / "data" / "cache" / "rss_feed.xml"   # optional fallback
OUTPUT_DIR = ROOT / "images" / "ig"
FONT_PATH  = ROOT / "images" / "fonts" / "BungeeSpice-Regular.ttf"

# --- State & rotation paths ---
STATE_DIR          = ROOT / "data" / "state"
TEMPLATES_DIR      = ROOT / "images" / "ig" / "templates"
TEMPLATE_INDEXFILE = STATE_DIR / "ig_template_index.txt"
LAST_SLUG_FILE     = STATE_DIR / "instagram_last_slug.txt"
LAST_CARD_MARKER   = STATE_DIR / "instagram_last_card.txt"

def get_next_template():
    """Return next template path in rotation, cycling through all IG-p templates."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    tpl_files = sorted(TEMPLATES_DIR.glob("IG-p-1080-1350-*.jpg"))
    if not tpl_files:
        raise FileNotFoundError("❌ No IG templates found in images/ig/templates/")

    # load last index
    if TEMPLATE_INDEXFILE.exists():
        try:
            idx = int(TEMPLATE_INDEXFILE.read_text().strip())
        except Exception:
            idx = 0
    else:
        idx = 0

    # next index (rotate)
    idx = (idx + 1) % len(tpl_files)

    # save
    TEMPLATE_INDEXFILE.write_text(str(idx))

    return tpl_files[idx]

# --- Panel geometry inside the template (точные координаты) ---
# Размер шаблона: 1080 × 1350
PANEL_BOX = (79, 440, 1011, 807)

INSET        = 24

# --- Text layout ---
MAX_LINES        = 4
SAFE_PAD_X       = 28
SAFE_PAD_Y       = 18
TEXT_SPACING     = 5
FONT_SIZE_RATIO  = 0.072
MIN_FONT_SIZE    = 26

# --- Visual style ---
USE_GRADIENT_TEXT = True
GRAD_TOP   = (220, 90, 20)
GRAD_BOT   = (160, 60, 15)
TEXT_COLOR = (70, 40, 25, 255)
TEXT_SHADOW = (0, 0, 0, 80)

# ============================================================
# Helpers
# ============================================================

def _load_latest():
    data = parse_latest_from_cache(CACHE_JSON)
    if data and data.get("title"):
        print("ℹ️ Source: latest_posts.json")
        return data
    if RSS_PATH.exists():
        print("ℹ️ Source: rss_feed.xml")
        return parse_latest_from_rss(RSS_PATH)
    raise FileNotFoundError("Neither latest_posts.json nor rss_feed.xml found.")

def _measure(draw, text, font, spacing):
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

def _fit_text_to_box(draw, title, font_path, start_size, min_size,
                     max_lines, spacing, box_w, box_h):
    words = title.split()
    size = int(start_size)
    last = None
    while size >= min_size:
        try:
            font = ImageFont.truetype(str(font_path), size)
        except Exception:
            font = ImageFont.load_default()
        lines = _wrap_text(words, font, box_w, max_lines)
        block = "\n".join(lines)
        tw, th = _measure(draw, block, font, spacing)
        if tw <= box_w and th <= box_h:
            return font, block, tw, th, size
        last = (font, block, tw, th, size)
        size -= 2
    return last if last else (ImageFont.load_default(), title, box_w, box_h, min_size)

def _get_slug(latest: dict) -> str | None:
    """Derive a stable slug for RSS entry: prefer link path, fallback to title."""
    link = (latest.get("link") or "").strip()
    title = (latest.get("title") or "").strip()

    # 1) Try to extract from URL path
    if link:
        try:
            path = urlparse(link).path
            parts = [p for p in path.split("/") if p]
            if parts:
                return parts[-1].lower()
        except Exception:
            pass

    # 2) Fallback: from title
    if title:
        return "-".join(title.lower().split())

    return None

# ============================================================
# Main
# ============================================================

def main():
    latest = _load_latest()
    title = latest["title"]
    print(f"📰 Title: {title}")
    print(f"🔗 Link: {latest.get('link','')}")

    # --- Ensure state dir exists and clear previous marker ---
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LAST_CARD_MARKER.unlink()
    except FileNotFoundError:
        pass

    # --- NEW: RSS-based de-duplication via slug ---
    slug = _get_slug(latest)
    if slug:
        if LAST_SLUG_FILE.exists():
            prev_slug = LAST_SLUG_FILE.read_text().strip()
        else:
            prev_slug = None

        if prev_slug == slug:
            print(f"⏭️ Skipping card generation: RSS slug '{slug}' already used.")
            return
        else:
            print(f"🆕 New RSS post detected: {slug}")
    else:
        print("⚠️ Could not derive slug, generating card without de-duplication.")

    # 👉 rotating template
    template_path = get_next_template()
    print(f"🖼 Using template: {template_path.name}")

    base = Image.open(template_path).convert("RGBA")
    W, H = base.size
    assert (W, H) == (1080, 1350), f"Unexpected template size: {(W, H)}"

    # --- Panel geometry & working area ---
    x0, y0, x1, y1 = PANEL_BOX
    pw, ph = (x1 - x0), (y1 - y0)

    wx0 = x0 + INSET + SAFE_PAD_X
    wy0 = y0 + INSET + SAFE_PAD_Y
    wx1 = x1 - INSET - SAFE_PAD_X
    wy1 = y1 - INSET - SAFE_PAD_Y
    w_w = max(1, wx1 - wx0)
    w_h = max(1, wy1 - wy0)

    # --- Fit text into box ---
    start_font_size = int(W * FONT_SIZE_RATIO)
    text_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)

    font, text_block, tw, th, used_size = _fit_text_to_box(
        tdraw, title, FONT_PATH, start_font_size, MIN_FONT_SIZE,
        MAX_LINES, TEXT_SPACING, w_w, w_h
    )

    ascent, descent = font.getmetrics()
    line_h = ascent + descent + TEXT_SPACING
    block_h = line_h * len(text_block.split("\n")) - TEXT_SPACING

    ty = wy0 + (w_h - block_h) / 2
    ty -= (ascent - descent) * 0.15

    tx = wx0 + (w_w - tw) / 2

    tdraw.multiline_text(
        (tx + 2, ty + 2),
        text_block,
        font=font,
        fill=TEXT_SHADOW,
        spacing=TEXT_SPACING,
        align="center",
    )

    if USE_GRADIENT_TEXT:
        _draw_gradient_text(text_layer, text_block, (tx, ty), font, TEXT_SPACING)
    else:
        tdraw.multiline_text(
            (tx, ty),
            text_block,
            font=font,
            fill=TEXT_COLOR,
            spacing=TEXT_SPACING,
            align="center",
        )

    combined = Image.alpha_composite(base, text_layer)

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (W, H)], radius=40, fill=255)
    rounded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded.paste(combined, mask=mask)

    shadow2 = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    bg.paste(shadow2, (5, 5))
    bg.paste(rounded, (0, 0), rounded)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    safe_title = "-".join(title.lower().split())
    out_name = f"{date_tag}-{safe_title}.jpg"
    out_path = OUTPUT_DIR / out_name

    bg.convert("RGB").save(
        out_path,
        "JPEG",
        quality=92,
        optimize=True,
        comment=f"Build {datetime.now()}".encode(),
    )

    print(f"✅ Saved: {out_path}")
    print(f"🌐 Public URL: https://post.equalle.com/images/ig/{out_name}")
    print(
        f"📐 Panel box: {PANEL_BOX}, working box: {(wx0, wy0, wx1, wy1)}, "
        f"font: {used_size}px"
    )

    # --- NEW: mark that card was generated for this slug ---
    if slug:
        LAST_SLUG_FILE.write_text(slug)
        LAST_CARD_MARKER.write_text(str(out_path))
        print(f"💾 Saved new last slug: {slug}")
        print("🏷  Marker file created: instagram_last_card.txt")

if __name__ == "__main__":
    main()
