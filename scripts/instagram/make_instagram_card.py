# ============================================================
# File: make_instagram_card.py
# Purpose: Render IG card using ready-made template with built-in panel
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
TEMPLATE   = ROOT / "images" / "IG-p-1080-1350.jpg"     # шаблон с плашкой
OUTPUT_DIR = ROOT / "images" / "ig"
FONT_PATH  = ROOT / "images" / "fonts" / "BungeeSpice-Regular.ttf"

# --- Panel geometry (точные координаты белой плашки) ---
# Шаблон 1080×1350. Белая панель:
#   x0=79, y0=440, x1=1011, y1=807  → width=932, height=367
PANEL_BOX = (79, 440, 1011, 807)

# --- Поля внутри самой плашки (отступ от белого края) ---
MARGIN_X = 36
MARGIN_Y = 22

# --- Text layout ---
MAX_LINES        = 4
TEXT_SPACING     = 5
FONT_SIZE_RATIO  = 0.072   # стартовый размер шрифта от ширины изображения
MIN_FONT_SIZE    = 26      # нижняя граница авто-уменьшения

# --- Visual style ---
USE_GRADIENT_TEXT = True
GRAD_TOP   = (220, 90, 20)     # тёмный оранжевый (верх)
GRAD_BOT   = (160, 60, 15)     # коричневато-оранжевый (низ)
TEXT_COLOR = (70, 40, 25, 255) # fallback, если градиент выключен

# Тень текста (чисто визуально, на расчёт центра не влияет)
TEXT_SHADOW = (0, 0, 0, 80)
SHADOW_DX, SHADOW_DY = 2, 2

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
    """Render vertical gradient text using a mask."""
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
    """Pick the largest font size so text fits in (box_w x box_h)."""
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

# ============================================================
# Main
# ============================================================

def main():
    latest = _load_latest()
    title = latest["title"]
    print(f"📰 Title: {title}")
    print(f"🔗 Link: {latest.get('link','')}")

    base = Image.open(TEMPLATE).convert("RGBA")
    W, H = base.size
    assert (W, H) == (1080, 1350), f"Unexpected template size: {(W, H)}"

    # --- Panel geometry & exact inner box from panel edges ---
    x0, y0, x1, y1 = PANEL_BOX
    pw, ph = (x1 - x0), (y1 - y0)

    # Рабочая зона равна панели минус симметричные поля.
    wx0 = x0 + MARGIN_X
    wy0 = y0 + MARGIN_Y
    wx1 = x1 - MARGIN_X
    wy1 = y1 - MARGIN_Y
    w_w = max(1, wx1 - wx0)
    w_h = max(1, wy1 - wy0)

    # --- Fit text into the working zone ---
    start_font_size = int(W * FONT_SIZE_RATIO)
    text_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)

    font, text_block, tw, th, used_size = _fit_text_to_box(
        tdraw, title, FONT_PATH, start_font_size, MIN_FONT_SIZE,
        MAX_LINES, TEXT_SPACING, w_w, w_h
    )

    # Геометрическое центрирование внутри плашки (равные отступы сверху/снизу)
    tx = wx0 + (w_w - tw) / 2
    ty = wy0 + (w_h - th) / 2

    # Рисуем тень (не влияет на вычисление ty)
    tdraw.multiline_text((tx + SHADOW_DX, ty + SHADOW_DY), text_block, font=font,
                         fill=TEXT_SHADOW, spacing=TEXT_SPACING, align="center")

    # Основной текст/градиент
    if USE_GRADIENT_TEXT:
        _draw_gradient_text(text_layer, text_block, (tx, ty), font, TEXT_SPACING)
    else:
        tdraw.multiline_text((tx, ty), text_block, font=font,
                             fill=TEXT_COLOR, spacing=TEXT_SPACING, align="center")

    combined = Image.alpha_composite(base, text_layer)

    # Сохранение с тем же оформлением (скругление и лёгкая внешняя тень)
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
    print(f"📐 Panel box: {PANEL_BOX}, working box: {(wx0, wy0, wx1, wy1)}, font: {used_size}px")

if __name__ == "__main__":
    main()
