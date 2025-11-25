# ============================================
# File: product-post/product_post_facebook.py
# Purpose:
#   - Rotate product links:
#       EXTRA (3 links) → AMAZON (all) → EXTRA (3 links) → EQUALLE (all) → repeat
#   - Each run posts EXACTLY ONE link to Facebook Page
#   - Facebook fetches preview image automatically
#   - Build a Facebook post using GPT-5.1 (LLM), fallback DISABLED
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

DEFAULT_FB_PAGE_ID = "325670187920349"


# ===== STATE HANDLING =====

def load_state() -> Dict[str, int]:
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
    context_map = meta.get("context_map", {}) or {}
    grit_contexts: Dict[str, List[str]] = {}
    for context, grits in context_map.items():
        for g in grits:
            key = str(g)
            grit_contexts.setdefault(key, []).append(context)
    return grit_contexts


def flatten_json_products(json_path: Path, source_name: str) -> List[Dict[str, Any]]:
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
        try:
            pack_size = int(str(pack_key).split("_")[0])
        except Exception:
            pack_size = None

        for grit_label, url in grit_map.items():
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

    flush_current()

    print(f"[LOAD] extra: {len(products)} products from {txt_path}")
    return products


def get_source_for_phase(phase_index: int) -> str:
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


# ===== FACEBOOK POSTING =====

def get_page_token() -> str:
    token = os.getenv("FB_PAGE_TOKEN") or os.getenv("PAGE_TOKEN")
    if not token:
        raise RuntimeError("FB_PAGE_TOKEN (or PAGE_TOKEN) is not set.")
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
        print(f"[FB][ERROR] {resp.status_code}: {data}")
        raise RuntimeError(f"Facebook API error: {resp.status_code}")
    else:
        print(f"[FB][OK] Created post: {data}")


# ===== MAIN =====

def main():
    state = load_state()
    phase_index = state["phase_index"]
    link_index = state["link_index"]

    source_name = get_source_for_phase(phase_index)
    print(f"[MAIN] phase_index={phase_index} → source={source_name}, link_index={link_index}")

    links = load_links_for_source(source_name)

    if not links:
        print(f"[MAIN][WARN] No links for source '{source_name}'. Advancing phase.")
        save_state(phase_index + 1, 0)
        return

    if link_index >= len(links):
        print(f"[MAIN] Completed source group. Advancing phase.")
        save_state(phase_index + 1, 0)
        return

    product = links[link_index]
    url = product.get("url")
    if not url:
        print(f"[MAIN][WARN] No URL in product; skipping.")
        save_state(phase_index, link_index + 1)
        return

    # ========== LLM ONLY (fallback disabled) ==========
    try:
        caption = generate_facebook_post(product)
        print("[MAIN][LLM] Generated caption via GPT-5.1")
    except Exception as e:
        print(f"[MAIN][LLM][ERROR] LLM failed: {e}")
        print("[MAIN] Aborting. Fallback is disabled — no post will be created.")
        return

    print("[MAIN] Caption:")
    print(caption)
    print("[MAIN] URL:")
    print(url)

    # Post to Facebook
    post_to_facebook(caption, url)

    # Advance link index
    link_index += 1
    if link_index >= len(links):
        print(f"[MAIN] Finished group; advancing to next phase.")
        save_state(phase_index + 1, 0)
    else:
        save_state(phase_index, link_index)


if __name__ == "__main__":
    main()
