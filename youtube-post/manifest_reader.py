# ============================================
# File: youtube-post/manifest_reader.py
# Purpose: Read youtube-post/manifests/*.json and yield items for posting
# Notes:
# - Supports both legacy format: { "items": [...] }
# - And current format (Pinterest-style): { "pins": [...] } with destination/alt/status
# ============================================

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


@dataclass(frozen=True)
class ManifestItem:
    manifest_name: str
    video_url: str
    filename: str
    title: str
    description: str
    destination_url: str = ""
    alt: str = ""
    status: str = ""


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_filename(video_url: str) -> str:
    return (
        video_url.split("?")[0]
        .split("#")[0]
        .rstrip("/")
        .split("/")[-1]
        or "video.mp4"
    )


def iter_manifest_items(manifest_path: Path) -> Iterator[ManifestItem]:
    data = _load_json(manifest_path)

    # Current format: { pins: [...] }
    pins = data.get("pins")
    if isinstance(pins, list):
        for raw in pins:
            if not isinstance(raw, dict):
                continue

            video_url = str(raw.get("video_url") or "").strip()
            if not video_url:
                continue

            filename = str(raw.get("filename") or "").strip() or _infer_filename(video_url)
            title = str(raw.get("title") or "").strip()
            description = str(raw.get("description") or "").strip()
            alt = str(raw.get("alt") or "").strip()
            status = str(raw.get("status") or "").strip()

            destination_url = ""
            dest = raw.get("destination")
            if isinstance(dest, dict):
                destination_url = str(dest.get("url") or "").strip()

            yield ManifestItem(
                manifest_name=manifest_path.name,
                video_url=video_url,
                filename=filename,
                title=title,
                description=description,
                destination_url=destination_url,
                alt=alt,
                status=status,
            )
        return

    # Legacy format: { items: [...] }
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError(f"[{manifest_path.name}] expected top-level 'pins' or 'items' as array")

    for raw in items:
        if not isinstance(raw, dict):
            continue

        video_url = str(raw.get("video_url") or "").strip()
        if not video_url:
            continue

        filename = str(raw.get("filename") or "").strip() or _infer_filename(video_url)
        title = str(raw.get("title") or "").strip()
        description = str(raw.get("description") or "").strip()

        yield ManifestItem(
            manifest_name=manifest_path.name,
            video_url=video_url,
            filename=filename,
            title=title,
            description=description,
        )


def read_all(manifest_dir: Path, *, order: Optional[List[str]] = None) -> List[ManifestItem]:
    if order:
        paths = [manifest_dir / n for n in order if (manifest_dir / n).exists()]
    else:
        paths = sorted(manifest_dir.glob("*.json"))

    out: List[ManifestItem] = []
    for p in paths:
        out.extend(list(iter_manifest_items(p)))
    return out
