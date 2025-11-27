# ============================================
# File: blog-nailak/utils/text_builder.py
# Purpose: Build platform-specific text with HIGH VARIABILITY
# ============================================

import textwrap
import random


# -------------------------------------------------
# VARIATION POOLS (large, diverse, rewritten)
# -------------------------------------------------

FB_INTROS = [
    "Beautiful nails begin with simple daily care.",
    "Healthy nails grow when you give them a few minutes of attention every day.",
    "Your nails can look amazing with just a small routine.",
    "Strong, glossy nails are the result of gentle, consistent habits.",
    "Soft cuticles and healthy nails start with tiny daily steps."
]

FB_MIDDLES = [
    "Here’s how to make the process effortless.",
    "This guide explains a routine you can start right now.",
    "Just a few minutes a day can completely change how your nails feel.",
    "These steps work even if your schedule is packed.",
    "Try this method and you’ll notice healthier nails very soon."
]

FB_CTA = [
    "Full guide here:",
    "Read the full routine:",
    "Step-by-step instructions:",
    "Learn more in the full article:",
    "See the complete guide:"
]

FB_HASHTAGS = [
    "#nailcare #cuticlecare #nailhealth #NailakCare",
    "#nailcare #nailtips #healthyhands #NailakCare",
    "#nailhealth #beautyroutine #cuticlecare #NailakCare",
]

IG_INTROS = [
    "Strong, hydrated nails grow from tiny habits you repeat every day.",
    "Healthy nails start with mindful, consistent care.",
    "Soft cuticles and beautiful nails come from a simple daily ritual.",
    "Your hands deserve a moment of attention and gentle care.",
    "A small routine can help your nails stay strong, smooth, and beautiful."
]

IG_MIDDLES = [
    "This guide shows a gentle workflow that keeps your nails protected.",
    "You'll learn how to nourish your cuticles and prevent dryness and peeling.",
    "These steps fit into any lifestyle — even a busy one.",
    "This method helps reduce breakage and keeps your nails flexible.",
    "Perfect if you want healthier nails without complicated routines."
]

IG_CTA = [
    "Full routine on our blog (link in bio).",
    "Read the full step-by-step guide on the blog.",
    "More details in the full article — link in bio.",
    "Full instructions available on our blog.",
    "Complete breakdown on the blog — link in bio."
]

IG_HASHTAGS = [
    "#nailcare #cuticlecare #nailroutine #nailtips #nailhealth #NailakCare #selfcare #beautytips",
    "#nailcare #nailhealth #nailarttips #cuticlecare #NailakCare #selfcare",
    "#healthynails #cuticlecare #nailroutine #NailakCare #beautytips",
]

FB_COMMENTS = [
    "Thank you for reading! 💅✨ Let us know if this routine helped your nails.",
    "We’re glad you stopped by! 💛 Tell us if you try this routine.",
    "Your nails deserve daily care — thanks for checking out the guide! ✨",
    "If you try these steps, share your results — we’d love to hear! 💅",
    "Thanks for being here! More nail-care tips are always on our blog. 💛",
]

EMOJIS = ["💅", "✨", "🌿", "💛", "🌸", "🤍", "🌼"]


# -------------------------------------------------
# FACEBOOK MESSAGE
# -------------------------------------------------

def build_facebook_message(post):
    """Creates a highly varied Facebook-friendly message."""

    title = post.title.strip()
    url = post.link

    intro = random.choice(FB_INTROS)
    middle = random.choice(FB_MIDDLES)
    cta = random.choice(FB_CTA)
    hashtags = random.choice(FB_HASHTAGS)
    emoji = random.choice(EMOJIS)

    message = (
        f"{title}\n"
        f"{intro} {middle} {emoji}\n\n"
        f"{cta}\n{url}\n\n"
        f"{hashtags}"
    )

    return textwrap.dedent(message).strip()


# -------------------------------------------------
# INSTAGRAM CAPTION
# -------------------------------------------------

def build_instagram_caption(post):
    """Creates a more expressive, varied Instagram caption."""

    title = post.title.strip()
    url = post.link

    intro = random.choice(IG_INTROS)
    middle = random.choice(IG_MIDDLES)
    cta = random.choice(IG_CTA)
    hashtags = random.choice(IG_HASHTAGS)
    emoji = random.choice(EMOJIS)

    caption = (
        f"{title}\n\n"
        f"{intro} {middle} {emoji}\n\n"
        f"{cta}\n{url}\n\n"
        f"{hashtags}"
    )

    return textwrap.dedent(caption).strip()


# -------------------------------------------------
# PINTEREST PAYLOAD
# -------------------------------------------------

def build_pinterest_payload(post):
    """Pinterest description stays short, keyword-rich."""

    title = post.title.strip()

    description = (
        f"{title}. "
        "A simple, effective routine for healthy nails and nourished cuticles."
    )

    hashtags = "nail care, cuticle care, nail health, beauty routine"

    return {
        "title": title,
        "description": f"{description} {hashtags}",
    }


# -------------------------------------------------
# FACEBOOK COMMENT (fallback)
# -------------------------------------------------

def build_facebook_comment(post):
    """Highly varied fallback comment."""
    return random.choice(FB_COMMENTS)
