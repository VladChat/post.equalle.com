# ============================================================
# File: x_autopost/post_to_x.py
# Path: /x_autopost/post_to_x.py
# Description:
#   Script for automated posting to X (Twitter) via Playwright.
#   Cycles through three product sources (equalle, amazon, extra),
#   generates tweet text, posts via /intent/tweet, updates state.json.
#   Uses a single GitHub secret: X_CREDENTIALS (format "username:password").
#
# Notes:
#   - State file: x_autopost/state/state.json
#   - Auth persistence: x_autopost/state/auth_state.json
#   - This script is executed from GitHub Actions workflow:
#       .github/workflows/products-to-x.yml
# ============================================================

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple, Optional, List
from urllib.parse import quote

from playwright.async_api import (
    async_playwright,
    Page,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
)


# Пути к файлам
BASE_DIR = Path(__file__).resolve().parent
EQUALLE_JSON = BASE_DIR / "equalle_products.json"
AMAZON_JSON = BASE_DIR / "amazon_products.json"
EXTRA_TXT = BASE_DIR / "extra_products.txt"

STATE_DIR = BASE_DIR / "state"
STATE_FILE = STATE_DIR / "state.json"
AUTH_STATE_FILE = STATE_DIR / "auth_state.json"


@dataclass
class PosterState:
    """
    state.json структура:
    {
      "source_index": 0,
      "link_indices": {
        "equalle": 0,
        "amazon": 0,
        "extra": 0
      }
    }
    """
    source_index: int = 0
    link_indices: Dict[str, int] = field(default_factory=dict)


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_extra_products(path: Path) -> List[Dict[str, str]]:
    """
    Разбираем extra_products.txt формата:

    https://url
    Title:"..."
    Description:"..."

    (пустая строка между блоками)
    """
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        raw = f.read()

    blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
    items: List[Dict[str, str]] = []

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue

        url = lines[0]
        title = ""
        desc = ""

        for ln in lines[1:]:
            if ln.startswith("Title:"):
                # Берём всё после Title: и убираем кавычки, если есть
                val = ln[len("Title:"):].strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                title = val
            elif ln.startswith("Description:"):
                val = ln[len("Description:"):].strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                desc = val

        items.append(
            {
                "source": "extra",
                "url": url,
                "title": title,
                "desc": desc,
            }
        )

    return items


def load_state() -> PosterState:
    if not STATE_FILE.exists():
        # инициализация link_indices по умолчанию
        return PosterState(
            source_index=0,
            link_indices={"equalle": 0, "amazon": 0, "extra": 0},
        )
    with STATE_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    link_indices = data.get("link_indices") or {}
    # гарантируем наличие ключей
    for key in ("equalle", "amazon", "extra"):
        link_indices.setdefault(key, 0)
    return PosterState(
        source_index=data.get("source_index", 0),
        link_indices=link_indices,
    )


def save_state(state: PosterState) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_index": state.source_index,
        "link_indices": state.link_indices,
    }
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def parse_grit_num(grit_key: str) -> int:
    """
    "Grit 220" -> 220
    """
    parts = grit_key.strip().split()
    for p in parts:
        if p.isdigit():
            return int(p)
    raise ValueError(f"Cannot parse grit from key: {grit_key}")


def build_flat_products(data: Dict[str, Any], source_name: str) -> List[Dict[str, Any]]:
    """
    Превращаем структуру products + meta в плоский список продуктов.
    Каждый элемент:
    {
      "source": "equalle" | "amazon",
      "pack_size": 25,
      "grit_value": 220,
      "anchor": "...",
      "desc": "...",
      "url": "https://..."
    }
    """
    products = data["products"]
    meta = data["meta"]
    packs_order = meta.get("packs_order") or []

    items: List[Dict[str, Any]] = []

    for pack_size in packs_order:
        pack_key = f"{pack_size}_pack"
        if pack_key not in products:
            continue
        grit_keys = list(products[pack_key].keys())
        grits_numeric = sorted(parse_grit_num(k) for k in grit_keys)

        for grit_value in grits_numeric:
            grit_key = f"Grit {grit_value}"
            url = products[pack_key].get(grit_key)
            if not url:
                continue

            grit_meta = meta.get("grit_copy", {}).get(str(grit_value), {})
            anchor = grit_meta.get("anchor", f"{grit_value} Grit")
            desc = grit_meta.get("desc", "")

            items.append(
                {
                    "source": source_name,
                    "pack_size": pack_size,
                    "grit_value": grit_value,
                    "anchor": anchor,
                    "desc": desc,
                    "url": url,
                }
            )

    return items


def select_next_item(
    eq_items: List[Dict[str, Any]],
    amz_items: List[Dict[str, Any]],
    extra_items: List[Dict[str, Any]],
    state: PosterState,
) -> Tuple[Dict[str, Any], PosterState]:
    """
    Выбираем следующий элемент по кругу:
    - источники: ["equalle", "amazon", "extra"] по очереди;
    - внутри каждого источника свои индексы (link_indices[source]).
    """

    sources = ["equalle", "amazon", "extra"]
    items_by_source = {
        "equalle": eq_items,
        "amazon": amz_items,
        "extra": extra_items,
    }

    # гарантируем корректность индекса источника
    source_index = state.source_index % len(sources)
    link_indices = dict(state.link_indices)

    # максимум пару кругов по источникам, чтобы найти тот, где есть элементы
    for _ in range(len(sources) * 2):
        source = sources[source_index]
        items = items_by_source[source]

        if items:
            current_idx = link_indices.get(source, 0)
            # берём по модулю, чтобы крутилось по кругу
            real_idx = current_idx % len(items)
            product = items[real_idx]

            # следующий стейт:
            next_source_index = (source_index + 1) % len(sources)
            link_indices[source] = current_idx + 1

            next_state = PosterState(
                source_index=next_source_index,
                link_indices=link_indices,
            )
            return product, next_state

        # если у источника нет элементов — идём к следующему
        source_index = (source_index + 1) % len(sources)

    raise RuntimeError("No products available in any source")


def build_tweet_text(product: Dict[str, Any]) -> str:
    """
    Формируем нормальный человеческий твит.
    Варианты:
    - для equalle/amazon продуктов с grit/pack;
    - для extra-продуктов с title/description.
    """

    source = product.get("source")

    # Гритовые продукты (equalle / amazon)
    if "anchor" in product and "pack_size" in product:
        anchor = product["anchor"]
        pack_size = product["pack_size"]
        desc: str = product.get("desc") or ""
        url: str = product["url"]

        if source == "amazon":
            line1 = f"{anchor} – {pack_size}-Sheet Pack, Wet/Dry Sandpaper."
        else:
            # equalle
            line1 = f"{anchor} – {pack_size} Sheets, 9x11 in, Wet/Dry Silicon Carbide."

        # Короткая фраза-объяснение
        line2 = ""
        if desc:
            sentence = desc.split(".")[0].strip()
            if len(sentence) > 90:
                sentence = sentence[:87].rsplit(" ", 1)[0] + "…"
            line2 = sentence

        if source == "amazon":
            link_line = f"Amazon: {url}"
        else:
            link_line = url

        parts = [line1]
        if line2:
            parts.append(line2)
        parts.append(link_line)

    else:
        # extra-продукты
        title = product.get("title", "").strip()
        desc = product.get("desc", "").strip()
        url = product["url"]

        if title and len(title) > 120:
            title = title[:117].rsplit(" ", 1)[0] + "…"

        line1 = title if title else "New product pick:"
        line2 = ""
        if desc:
            sentence = desc.split(".")[0].strip()
            if len(sentence) > 90:
                sentence = sentence[:87].rsplit(" ", 1)[0] + "…"
            line2 = sentence

        parts = [line1]
        if line2:
            parts.append(line2)
        parts.append(url)

    tweet = "\n".join(parts)

    # Если слишком длинный — постепенно упрощаем
    if len(tweet) <= 280:
        return tweet

    # Упрощение: оставляем первую строку + ссылку
    simple = "\n".join([parts[0], parts[-1]])
    if len(simple) <= 280:
        return simple

    # В крайнем случае жёстко режем
    return simple[:280]


async def ensure_login(page: Page, username: str, password: str) -> None:
    """
    Логинимся в X, если нас перекинуло на /login или /i/flow/login.
    Предполагаем английский интерфейс.
    """
    url = page.url
    if "login" not in url and "flow" not in url:
        # Скорее всего, уже залогинены.
        return

    await page.wait_for_load_state("networkidle")

    # Шаг 1: username
    await page.fill("input[autocomplete='username']", username)
    await page.get_by_role("button", name="Next").click()
    await page.wait_for_timeout(2000)

    # Иногда X просит ещё раз подтвердить username/phone
    try:
        identity_input = page.locator("input[name='text']")
        if await identity_input.count():
            await identity_input.fill(username)
            await page.get_by_role("button", name="Next").click()
            await page.wait_for_timeout(2000)
    except Exception:
        pass

    # Шаг 2: пароль
    await page.fill("input[name='password']", password)
    await page.get_by_role("button", name="Log in").click()
    await page.wait_for_timeout(5000)


async def post_to_x(tweet_text: str) -> None:
    """
    Открываем /intent/tweet с нашим текстом, при необходимости логинимся,
    жмём Post.
    """

    # Читаем один секрет X_CREDENTIALS в формате "username:password"
    raw = os.getenv("X_CREDENTIALS", "")
    if ":" not in raw:
        raise RuntimeError("X_CREDENTIALS must be in 'username:password' format")

    username, password = raw.split(":", 1)

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ],
        )

        context_kwargs = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 720},
        }

        # Если есть сохранённое состояние авторизации — используем его.
        if AUTH_STATE_FILE.exists():
            context: BrowserContext = await browser.new_context(
                storage_state=str(AUTH_STATE_FILE),
                **context_kwargs,
            )
        else:
            context = await browser.new_context(**context_kwargs)

        page = await context.new_page()

        encoded_text = quote(tweet_text)
        compose_url = f"https://x.com/intent/tweet?text={encoded_text}"

        try:
            await page.goto(
                compose_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except PlaywrightTimeoutError:
            # Если по таймауту, но что-то загрузилось — продолжаем,
            # иначе пробрасываем ошибку.
            if not page.url.startswith("https://x.com"):
                await browser.close()
                raise

        # Если нас кинуло на логин — логинимся и снова открываем compose
        if "login" in page.url or "flow" in page.url:
            await ensure_login(page, username, password)
            try:
                await page.goto(
                    compose_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            except PlaywrightTimeoutError:
                if not page.url.startswith("https://x.com"):
                    await browser.close()
                    raise

        # Нажимаем кнопку Post
        try:
            post_btn = page.get_by_role("button", name="Post")
            await post_btn.click()
        except Exception:
            fallback_btn = page.locator("div[data-testid='tweetButtonInline']")
            await fallback_btn.click()

        await page.wait_for_timeout(5000)

        # Сохраняем auth-state, чтобы в следующий раз не логиниться заново
        await context.storage_state(path=str(AUTH_STATE_FILE))

        await browser.close()


async def main() -> None:
    # Загружаем данные из файлов
    equalle_data = load_json(EQUALLE_JSON)
    amazon_data = load_json(AMAZON_JSON)
    extra_items = load_extra_products(EXTRA_TXT)

    # Строим плоские списки продуктов
    eq_items = build_flat_products(equalle_data, "equalle")
    amz_items = build_flat_products(amazon_data, "amazon")

    state = load_state()

    # Выбираем следующий продукт/линк и следующий стейт
    product, next_state = select_next_item(eq_items, amz_items, extra_items, state)

    # Строим твит
    tweet_text = build_tweet_text(product)

    print("=== Tweet to send ===")
    print(tweet_text)
    print("=====================")

    # Отправляем в X
    await post_to_x(tweet_text)

    # Обновляем стейт (какой продукт/линк был опубликован)
    save_state(next_state)


if __name__ == "__main__":
    asyncio.run(main())
