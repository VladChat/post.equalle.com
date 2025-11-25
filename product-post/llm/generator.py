# ============================================
# File: product-post/llm/generator.py
# Purpose: Handle GPT-5.1 generation for Facebook posts and comments
# ============================================

import os
from pathlib import Path
from typing import Dict, Any

from openai import OpenAI

# Directories
ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = ROOT / "prompts"


# ==========================
# PROMPT SELECTION FOR POSTS
# ==========================

def select_prompt(product: Dict[str, Any]) -> str:
    """
    Select style prompt based on product contexts.

    Priority:
      auto  → fb_prompt_auto_v1.txt
      wood  → fb_prompt_wood_v1.txt
      metal → fb_prompt_metal_v1.txt
      diy   → fb_prompt_diy_v1.txt
      else  → fb_prompt_common_v1.txt
    """
    contexts = product.get("contexts") or []
    contexts = [str(c).lower() for c in contexts]

    if "auto" in contexts:
        file = PROMPTS_DIR / "fb_prompt_auto_v1.txt"
    elif "wood" in contexts:
        file = PROMPTS_DIR / "fb_prompt_wood_v1.txt"
    elif "metal" in contexts:
        file = PROMPTS_DIR / "fb_prompt_metal_v1.txt"
    elif "diy" in contexts:
        file = PROMPTS_DIR / "fb_prompt_diy_v1.txt"
    else:
        file = PROMPTS_DIR / "fb_prompt_common_v1.txt"

    if not file.exists():
        raise RuntimeError(f"Prompt file not found: {file}")

    return file.read_text(encoding="utf-8")


# ==========================
# PRODUCT → USER PROMPT (COMMON)
# ==========================

def format_product_info(product: Dict[str, Any]) -> str:
    """
    Convert product metadata into a structured LLM user prompt.
    Works for both main posts and follow-up comments.
    """
    url = product.get("url", "")

    grit = product.get("grit")
    pack = product.get("pack")
    anchor = product.get("anchor") or ""
    desc = product.get("grit_description") or ""
    contexts = ", ".join(product.get("contexts") or [])

    title = product.get("title") or ""
    extra_desc = product.get("description") or ""

    text = f"""
    Product Information:

    URL: {url}

    {f"Grit: {grit}" if grit else ""}
    {f"Pack Size: {pack}" if pack else ""}

    Anchor: {anchor}
    Description: {desc}
    Contexts: {contexts}

    Extra Title: {title}
    Extra Description: {extra_desc}
    """

    return text.strip()


# ==========================
# GPT-5.1 CALL — MAIN POST
# ==========================

def generate_facebook_post(product: Dict[str, Any]) -> str:
    """
    Generate a Facebook post using GPT-5.1.
    Uses style prompt chosen by product context.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment variables.")

    client = OpenAI(api_key=api_key)

    system_prompt = select_prompt(product)
    user_prompt = format_product_info(product)

    response = client.chat.completions.create(
        model="gpt-5.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_completion_tokens=300,
    )

    return response.choices[0].message.content.strip()


# ==========================
# GPT-5.1 CALL — COMMENT
# ==========================

def generate_facebook_comment(product: Dict[str, Any]) -> str:
    """
    Generate a short follow-up comment for Facebook using a dedicated prompt.

    Rules are encoded in fb_comment_prompt_v1.txt:
      - 2–3 lines
      - no links
      - no emojis
      - no engagement bait
      - adds extra value, does NOT repeat the post
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment variables.")

    client = OpenAI(api_key=api_key)

    prompt_file = ROOT / "prompts" / "fb_comment_prompt_v1.txt"
    if not prompt_file.exists():
        raise RuntimeError(f"Comment prompt file not found: {prompt_file}")

    system_prompt = prompt_file.read_text(encoding="utf-8")
    user_prompt = format_product_info(product)

    response = client.chat.completions.create(
        model="gpt-5.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_completion_tokens=120,
    )

    return response.choices[0].message.content.strip()
