# ============================================================
# File: scripts/media/screenshot.py
# Purpose: Capture screenshots of web pages for preview or posting
# ============================================================

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from pathlib import Path
import time
from PIL import Image

def capture_screenshot(
    url: str,
    out_path: str = "data/screens/screenshot.webp",
    width: int = 1920,
    height: int = 1080,
    crop_area: tuple | None = None,
    full_page: bool = False
) -> str:
    """
    Capture a screenshot of a webpage using headless Chrome.

    Args:
        url (str): Webpage URL.
        out_path (str): Path to save screenshot (PNG or WEBP).
        width (int): Browser window width.
        height (int): Browser window height.
        crop_area (tuple|None): (left, top, right, bottom) crop box.
        full_page (bool): If True, resize height to full scrollHeight.
    Returns:
        str: Absolute path to saved WEBP screenshot.
    """
    # === Headless Chrome setup ===
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument(f"--window-size={width},{height}")

    driver = webdriver.Chrome(options=chrome_options)
    driver.get(url)
    time.sleep(2.5)  # wait for render

    png_path = Path(out_path).with_suffix(".png")

    # === Full-page mode ===
    if full_page:
        scroll_height = driver.execute_script("return document.body.scrollHeight")
        driver.set_window_size(width, scroll_height)
        time.sleep(0.8)

    driver.save_screenshot(str(png_path))
    driver.quit()

    # === Crop if requested ===
    img = Image.open(png_path)
    if crop_area:
        img = img.crop(crop_area)

    # === Save as WEBP ===
    final_path = Path(out_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(final_path, "WEBP", quality=90)

    print(f"✅ Screenshot saved: {final_path.resolve()}")
    return str(final_path.resolve())
