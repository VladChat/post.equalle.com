# ============================================================
# File: make_instagram_card.py
# Purpose: Render IG card using ready-made template with built-in panel
# Author: eQualle Automation
# ============================================================

from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import json
import xml.etree.ElementTree as ET

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
HISTORY_FILE       = STATE_DIR / "instagram_card_history.json"
LAST_CARD_MARKER   = STATE_DIR / "instagram_last_card.txt"

HISTORY_LIMIT   = 5   # store last 5 slugs
FALLBACK_LIMIT  = 5   # look at last 5 RSS items


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
# Helpers: history
# ============================================================

def _load_history():
    """Load list of previously posted slugs for IG cards."""
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(s) for s in data]
        return []
    except Exception:
        return []


def _save_history(history):
    """Persist history list to JSON."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def _add_to_history(slug: str):
    """Append slug to history, keeping only the most recent HISTORY_LIMIT items."""
    history = _load_history()
    # remove if already present, then append to treat as most recent
    history = [s for s in history if s != slug]
    history.append(slug)
    history = history[-HISTORY_LIMIT:]
    _save_history(history)
    return history


# ============================================================
# Helpers: content loading
# ============================================================

def _load_recent_items(max_items: int = FALLBACK_LIMIT):
    """Load up to max_items recent RSS entries.

    Preference:
      1) rss_feed.xml (raw RSS, parse <item> nodes)
      2) latest_posts.json via parse_latest_from_cache (fallback)
    """
    items = []

    # 1) Try RSS XML first for proper list of items
    if RSS_PATH.exists():
        print("ℹ️ Source: rss_feed.xml")
        try:
            tree = ET.parse(RSS_PATH)
            root = tree.getroot()
            for item_el in root.findall(".//item"):
                title = (item_el.findtext("title") or "").strip()
                link = (item_el.findtext("link") or "").strip()
                description = (item_el.findtext("description") or "").strip()
                pub_date = (item_el.findtext("pubDate") or "").strip()
                if not title and not link:
                    continue
                items.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "pubDate": pub_date,
                })
                if len(items) >= max_items:
                    break
        except Exception as e:
            print(f"⚠️ Failed to parse RSS XML: {e}")

    # 2) Fallback: latest_posts.json via existing util
    if not items:
        data = parse_latest_from_cache(CACHE_JSON)
        if isinstance(data, list):
            items = data[:max_items]
        elif isinstance(data, dict) and data.get("title"):
            items = [data]
        if items:
            print("ℹ️ Source: latest_posts.json")

    if not items:
        raise FileNotFoundError("Neither latest_posts.json nor rss_feed.xml provided usable items.")

    print(f"🧾 Loaded {len(items)} recent RSS items (limit={max_items})")
    return items


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


def _get_slug(entry: dict) -> str | None:
    """Derive a stable slug for RSS/cache entry: prefer link path, fallback to title."""
    link = (entry.get("link") or "").strip()
    title = (entry.get("title") or "").strip()

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
    # --- Ensure state dir exists and clear previous marker ---
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LAST_CARD_MARKER.unlink()
    except FileNotFoundError:
        pass

    # --- Load recent RSS items and existing history ---
    items = _load_recent_items(max_items=FALLBACK_LIMIT)
    history = _load_history()
    if history:
        print(f"🧠 IG history (last {len(history)}): {history}")
    else:
        print("🧠 IG history is empty (first run or history reset).")

    # --- Fallback selection: first recent slug NOT in history ---
    chosen = None
    chosen_slug = None
    for idx, entry in enumerate(items):
        slug = _get_slug(entry)
        if not slug:
            print(f"⚠️ Item #{idx} has no usable slug, skipping.")
            continue
        if slug in history:
            print(f"⏭️ Slug already in history, skipping: {slug}")
            continue
        chosen = entry
        chosen_slug = slug
        break

    if not chosen or not chosen_slug:
        print("⏭️ No suitable RSS item found (all recent slugs are already in IG history) — skipping generation.")
        return

    title = (chosen.get("title") or "").strip() or "(untitled)"
    link = (chosen.get("link") or "").strip()
    print("🆕 Selected RSS item for IG card:")
    print(f"   • Slug:  {chosen_slug}")
    print(f"   • Title: {title}")
    if link:
        print(f"   • Link:  {link}")

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

    # shadow
    tdraw.multiline_text(
        (tx + 2, ty + 2),
        text_block,
        font=font,
        fill=TEXT_SHADOW,
        spacing=TEXT_SPACING,
        align="center",
    )

    # main text (gradient or flat)
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

    # rounded mask + soft drop shadow
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (W, H)], radius=40, fill=255)
    rounded = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded.paste(combined, mask=mask)

    shadow2 = rounded.filter(ImageFilter.GaussianBlur(12))
    bg = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    bg.paste(shadow2, (5, 5))
    bg.paste(rounded, (0, 0), rounded)

    # --- Save result ---
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

    # --- Update history and marker ---
    new_history = _add_to_history(chosen_slug)
    print(f"💾 Updated IG history ({len(new_history)} items): {new_history}")

    LAST_CARD_MARKER.write_text(str(out_path))
    print("🏷  Marker file created: instagram_last_card.txt")


if __name__ == "__main__":
    main()
