# ============================================
# File: product-post/llm/generator.py
# Purpose: Handle GPT-5.1 generation for Facebook posts
# ============================================

import os
from pathlib import Path
from typing import Dict, Any

from openai import OpenAI

ROOT = Path(__file__).resolve().parent
PROMPT_FILE = ROOT / "fb_prompt.txt"


def load_prompt() -> str:
    """Load the system prompt from fb_prompt.txt."""
    if not PROMPT_FILE.exists():
        raise RuntimeError(f"Prompt file not found: {PROMPT_FILE}")
    return PROMPT_FILE.read_text(encoding="utf-8")


def format_product_info(product: Dict[str, Any]) -> str:
    """Convert product fields into a structured user prompt."""
    url = product.get("url", "")

    grit = product.get("grit")
    pack = product.get("pack")
    anchor = product.get("anchor") or ""
    desc = product.get("grit_description") or ""
    contexts = ", ".join(product.get("contexts") or [])

    title = product.get("title") or ""
    extra_desc = product.get("description") or ""

    text = f"""
Product Information (for copywriting context only):

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


def generate_facebook_post(product: Dict[str, Any]) -> str:
    """Generate Facebook post text using GPT-5.1.

    Raises RuntimeError if OPENAI_API_KEY is missing.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment variables.")

    client = OpenAI(api_key=api_key)

    system_prompt = load_prompt()
    user_prompt = format_product_info(product)

    response = client.chat.completions.create(
        model="gpt-5.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=300,
    )

    return response.choices[0].message.content.strip()
