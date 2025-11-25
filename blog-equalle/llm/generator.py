# ============================================
# File: blog-equalle/llm/generator.py
# Purpose: GPT-5.1 generation for Facebook comments on blog posts
# ============================================

from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parent
PROMPT_FILE = ROOT / "fb_comment_prompt_v1.txt"


def generate_comment_from_llm(post) -> str:
    """Generate a short Facebook comment for a blog post using GPT-5.1.

    The `post` object is the same type used in text_builder/build_facebook_message:
    it has at least `title`, `description`, `summary`, and `link` attributes.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

    client = OpenAI(api_key=api_key)

    if not PROMPT_FILE.exists():
        raise RuntimeError(f"Comment prompt file not found: {PROMPT_FILE}")

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    title = (post.title or "").strip() if getattr(post, "title", None) else ""
    desc_source = getattr(post, "description", None) or getattr(post, "summary", None) or ""
    desc = str(desc_source).strip()

    user_prompt = f"""
    Article title: {title}
    Description: {desc}
    """

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
