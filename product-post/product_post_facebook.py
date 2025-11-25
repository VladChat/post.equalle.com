# ============================================
# File: product-post/product_post_facebook.py
# Purpose:
#   - Rotate product links in this order:
#       EXTRA (3 links) → AMAZON (all) → EXTRA (3 links) → EQUALLE (all) → repeat
#   - Each run: post EXACTLY ONE link to Facebook Page
#   - Facebook auto-fetches preview image from the link
#   - Build a Facebook post using GPT-5.1 (LLM), with fallback to local generator
# ============================================

import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests

from llm.generator import generate_facebook_post


# ===== PATHS =====

ROOT = Path(__file__).resolve().parent

STATE_FILE = ROOT / "product_state.json"
AMAZON_FILE = ROOT / "amazon_products.json"
EQUALLE_FILE = ROOT / "equalle_products.json"
EXTRA_FILE = ROOT / "extra_products.txt"

# Default Page ID from your Meta config (Abrasive Sanding Paper)
DEFAULT_FB_PAGE_ID = "325670187920349"


# ===== STATE HANDLING =====


def load_state() -> Dict[str, int]:
    """Load phase_index and link_index from product_state.json.
    If file is missing or broken, start from zero.
    """
    if not STATE_FILE.exists():
        return {"phase_index": 0, "link_index": 0}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        phase_index = int(data.get("phase_index", 0))
        link_index = int(data.get("link_index", 0))
        return {"phase_index": phase_index, "link_index": link_index}
    except Exception as e:
        print(f"[STATE] Failed to read state file, resetting. Error: {e}")
        return {"phase_index": 0, "link_index": 0}


def save_state(phase_index: int, link_index: int) -> None:
    data = {
        "phase_index": phase_index,
        "link_index": link_index,
    }
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[STATE] Saved state: phase_index={phase_index}, link_index={link_index}")


# ===== PRODUCT SOURCES =====


def build_grit_context_map(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    """Invert context_map so we can get list of contexts for each grit."""
    context_map = meta.get("context_map", {}) or {}
    grit_contexts: Dict[str, List[str]] = {}
    for context, grits in context_map.items():
        for g in grits:
            key = str(g)
            grit_contexts.setdefault(key, []).append(context)
    return grit_contexts


def flatten_json_products(json_path: Path, source_name: str) -> List[Dict[str, Any]]:
    """Load Amazon/Equalle JSON and flatten to a list of product dicts."""
    if not json_path.exists():
        print(f"[WARN] JSON file not found: {json_path}")
        return []

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    products = data.get("products", {})
    meta = data.get("meta", {})
    grit_copy = meta.get("grit_copy", {}) or {}
    grit_contexts = build_grit_context_map(meta)

    flat: List[Dict[str, Any]] = []

    for pack_key, grit_map in products.items():
        # pack_key like "10_pack" / "25_pack"
        try:
            pack_size = int(str(pack_key).split("_")[0])
        except Exception:
            pack_size = None

        for grit_label, url in grit_map.items():
            # grit_label like "Grit 400"
            grit_num: Optional[int] = None
            parts = str(grit_label).strip().split()
            if parts and parts[-1].isdigit():
                grit_num = int(parts[-1])

            grit_str = str(grit_num) if grit_num is not None else None
            gc = grit_copy.get(grit_str, {}) if grit_str else {}
            anchor = gc.get("anchor")
            desc = gc.get("desc")
            contexts = grit_contexts.get(grit_str, []) if grit_str else []

            flat.append(
                {
                    "source": source_name,
                    "url": url,
                    "grit": grit_num,
                    "pack": pack_size,
                    "anchor": anchor,
                    "grit_description": desc,
                    "contexts": contexts,
                }
            )

    print(f"[LOAD] {source_name}: {len(flat)} links from {json_path}")
    return flat


def load_extra_products(txt_path: Path) -> List[Dict[str, Any]]:
    """Parse extra_products.txt with 3 products.

    Supported simple format:

    https://www.amazon.com/dp/B0D6X7GWVD
    Title:"..."
    Description:"..."

    (blank line)

    Link:"https://www.amazon.com/dp/B0D71V6YP4"
    Title:"..."
    Description:"..."
    """
    if not txt_path.exists():
        print(f"[WARN] Extra file not found: {txt_path}")
        return []

    products: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    def flush_current():
        nonlocal current, products
        if current.get("url"):
            current.setdefault("source", "extra")
            products.append(current)
        current = {}

    with txt_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                # empty line = separator
                flush_current()
                continue

            lower = line.lower()

            if line.startswith("http"):
                current["url"] = line.strip()
            elif lower.startswith("link:"):
                value = line.split(":", 1)[1].strip().strip('"')
                current["url"] = value
            elif lower.startswith("title:"):
                value = line.split(":", 1)[1].strip().strip('"')
                current["title"] = value
            elif lower.startswith("description:"):
                value = line.split(":", 1)[1].strip().strip('"')
                current["description"] = value

    # last block
    flush_current()

    print(f"[LOAD] extra: {len(products)} products from {txt_path}")
    return products


def get_source_for_phase(phase_index: int) -> str:
    """Map phase_index to source name according to pattern:
       0 → extra (before amazon)
       1 → amazon
       2 → extra (before equalle)
       3 → equalle
       then repeat (phase_index % 4)
    """
    phase = phase_index % 4
    if phase in (0, 2):
        return "extra"
    elif phase == 1:
        return "amazon"
    else:
        return "equalle"


def load_links_for_source(source_name: str) -> List[Dict[str, Any]]:
    if source_name == "amazon":
        return flatten_json_products(AMAZON_FILE, "amazon")
    elif source_name == "equalle":
        return flatten_json_products(EQUALLE_FILE, "equalle")
    elif source_name == "extra":
        return load_extra_products(EXTRA_FILE)
    else:
        print(f"[WARN] Unknown source: {source_name}")
        return []


# ===== LOCAL FALLBACK CAPTION BUILDER =====


def humanize_contexts(contexts: List[str]) -> str:
    """Turn context keys into human text."""
    if not contexts:
        return ""

    mapping = {
        "wood": "wood projects",
        "metal": "metal parts",
        "auto": "auto paint & clear coat",
        "drywall": "drywall surfaces",
        "finishing": "fine finishing steps",
        "polishing": "high-gloss polishing",
    }

    words = [mapping.get(c, c) for c in contexts]
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def build_caption_for_sandpaper(prod: Dict[str, Any]) -> str:
    grit = prod.get("grit")
    pack = prod.get("pack")
    anchor = prod.get("anchor")
    grit_desc = prod.get("grit_description")
    contexts = prod.get("contexts") or []

    line1_parts = []
    if grit:
        line1_parts.append(f"{grit}-grit sandpaper sheets")
    if pack:
        line1_parts.append(f"{pack}-sheet pack")
    line1 = " – ".join(line1_parts) if line1_parts else "Sandpaper sheets for precise control"

    detail_lines = []
    if anchor:
        detail_lines.append(anchor)
    if grit_desc:
        detail_lines.append(grit_desc)

    ctx_text = humanize_contexts(contexts)
    if ctx_text:
        detail_lines.append(f"Great for {ctx_text}.")

    detail_lines.append("Wet or dry use for consistent, predictable results.")

    caption = line1 + "\n\n" + " ".join(detail_lines)
    return caption.strip()


def build_caption_for_extra(prod: Dict[str, Any]) -> str:
    title = prod.get("title") or ""
    desc = prod.get("description") or ""

    lines = []
    if title:
        lines.append(title)
    if desc:
        lines.append(desc)

    if not lines:
        lines.append("Practical sanding and polishing gear to make your surface prep easier.")

    caption = "\n\n".join(lines)
    return caption.strip()


def build_facebook_caption_fallback(prod: Dict[str, Any]) -> str:
    """Local non-LLM fallback generator."""
    if prod.get("source") in ("amazon", "equalle"):
        return build_caption_for_sandpaper(prod)
    else:
        return build_caption_for_extra(prod)


# ===== FACEBOOK POSTER =====


def get_page_token() -> str:
    token = os.getenv("FB_PAGE_TOKEN") or os.getenv("PAGE_TOKEN")
    if not token:
        raise RuntimeError("FB_PAGE_TOKEN (or PAGE_TOKEN) is not set in environment.")
    return token


def get_page_id() -> str:
    return os.getenv("FB_PAGE_ID", DEFAULT_FB_PAGE_ID)


def post_to_facebook(message: str, link: str) -> None:
    page_token = get_page_token()
    page_id = get_page_id()

    url = f"https://graph.facebook.com/v21.0/{page_id}/feed"
    payload = {
        "message": message,
        "link": link,
        "access_token": page_token,
    }

    print(f"[FB] POST → {url}")
    resp = requests.post(url, data=payload, timeout=30)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        print(f"[FB][ERROR] Status {resp.status_code}: {data}")
        raise RuntimeError(f"Facebook API error: {resp.status_code}")
    else:
        print(f"[FB][OK] Created post: {data}")


# ===== MAIN LOGIC =====


def main():
    # 1) Load state
    state = load_state()
    phase_index = state["phase_index"]
    link_index = state["link_index"]

    source_name = get_source_for_phase(phase_index)
    print(f"[MAIN] Current phase_index={phase_index} → source={source_name}, link_index={link_index}")

    # 2) Load links for current source
    links = load_links_for_source(source_name)

    if not links:
        print(f"[MAIN][WARN] No links for source '{source_name}'. Advancing phase.")
        phase_index += 1
        link_index = 0
        save_state(phase_index, link_index)
        return

    if link_index >= len(links):
        print(f"[MAIN] link_index={link_index} >= len(links)={len(links)} → reset index & advance phase")
        phase_index += 1
        link_index = 0
        save_state(phase_index, link_index)
        return

    product = links[link_index]
    url = product.get("url")
    if not url:
        print(f"[MAIN][WARN] Product at index {link_index} has no URL, skipping.")
        link_index += 1
        save_state(phase_index, link_index)
        return

    # 3) Build caption via GPT-5.1 with fallback
    try:
        caption = generate_facebook_post(product)
        print("[MAIN][LLM] Generated caption via GPT-5.1")
    except Exception as e:
        print(f"[MAIN][LLM][WARN] LLM generation failed: {e}. Using local fallback.")
        caption = build_facebook_caption_fallback(product)

    print("[MAIN] === Caption preview ===")
    print(caption)
    print("[MAIN] === URL ===")
    print(url)

    # 4) Post to Facebook
    post_to_facebook(caption, url)

    # 5) Advance index inside current phase
    link_index += 1
    if link_index >= len(links):
        phase_index += 1
        link_index = 0
        print(f"[MAIN] Completed phase for source={source_name}, moving to next phase_index={phase_index}")

    # 6) Save state
    save_state(phase_index, link_index)


if __name__ == "__main__":
    main()
