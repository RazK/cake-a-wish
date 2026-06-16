from __future__ import annotations
from pathlib import Path
from typing import Dict

from ._base import FrameTemplate, AssetFrameTemplate
from .clean import CleanFrame
from .bold import BoldFrame
from .retro import RetroFrame

_PROGRAMMATIC: list[FrameTemplate] = [CleanFrame(), BoldFrame(), RetroFrame()]

_FRAMES_DIR = Path(__file__).parent


def _load_asset_templates() -> list[FrameTemplate]:
    templates: list[FrameTemplate] = []
    for folder in sorted(_FRAMES_DIR.iterdir()):
        if folder.is_dir() and (folder / "config.json").exists():
            try:
                templates.append(AssetFrameTemplate(folder))
            except Exception:
                pass
    return templates


def get_registry() -> Dict[str, FrameTemplate]:
    registry: Dict[str, FrameTemplate] = {}
    for t in _PROGRAMMATIC + _load_asset_templates():
        registry[t.id] = t
    return registry


REGISTRY: Dict[str, FrameTemplate] = get_registry()


def get_frame(frame_id: str) -> FrameTemplate | None:
    return REGISTRY.get(frame_id)


__all__ = ["REGISTRY", "get_frame", "FrameTemplate", "AssetFrameTemplate"]
