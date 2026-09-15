"""Media stack definitions loaded from templates.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

_DEFAULT_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates.yaml")

WIDE = "wide"
JOINED = "joined"
LONG = "long"

TRUNCATE = "truncate"
WARN = "warn"


@dataclass(frozen=True)
class MediaStack:
    """One output layout -- e.g. 'Amazon flat file' or 'Shopify CSV'."""

    key: str
    label: str
    shape: str
    sku_header: str
    description: str = ""
    main_header: str | None = None
    other_header: str = "Other Image {n}"
    joined_header: str | None = None
    delimiter: str = ","
    url_header: str = "Image Src"
    position_header: str = "Image Position"
    position_start: int = 1
    max_images: int | None = None
    on_overflow: str = WARN
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def has_main_column(self) -> bool:
        return bool(self.main_header)

    def other_column_name(self, n: int) -> str:
        """Header for the n-th non-main image (n is 1-based)."""
        slot = n + 1 if self.has_main_column else n
        return self.other_header.format(n=n, slot=slot)

    def column_labels(self, count: int) -> list[str]:
        """Human-facing slot labels for `count` images, used by the preview grid."""
        labels: list[str] = []
        for i in range(count):
            if i == 0 and self.has_main_column:
                labels.append(self.main_header or "Main")
            elif self.shape == WIDE:
                labels.append(self.other_column_name(i if self.has_main_column else i + 1))
            elif self.shape == LONG:
                labels.append(f"{self.position_header} {i + self.position_start}")
            else:
                labels.append(f"{self.joined_header or 'Image'} #{i if self.has_main_column else i + 1}")
        return labels

    def effective_cap(self, override: int | None = None) -> int | None:
        """Image cap, with a UI override taking precedence over the template."""
        if override is not None and override > 0:
            if self.max_images is None:
                return override
            return min(override, self.max_images)
        return self.max_images


def _coerce(raw: dict[str, Any]) -> MediaStack:
    known = {f for f in MediaStack.__dataclass_fields__ if f != "extras"}
    kwargs = {k: v for k, v in raw.items() if k in known}
    extras = {k: v for k, v in raw.items() if k not in known}
    kwargs.setdefault("description", "")
    if kwargs.get("description"):
        kwargs["description"] = " ".join(str(kwargs["description"]).split())
    # yaml gives None for an explicitly-null scalar; keep dataclass defaults instead.
    for key in ("other_header", "delimiter", "url_header", "position_header", "position_start", "on_overflow"):
        if key in kwargs and kwargs[key] is None:
            kwargs.pop(key)
    return MediaStack(extras=extras, **kwargs)


@lru_cache(maxsize=8)
def load_stacks(path: str = _DEFAULT_TEMPLATES) -> tuple[MediaStack, ...]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("stacks") or []
    stacks = tuple(_coerce(entry) for entry in entries)
    if not stacks:
        raise ValueError(f"No media stacks defined in {path}")
    seen: set[str] = set()
    for stack in stacks:
        if stack.key in seen:
            raise ValueError(f"Duplicate media stack key: {stack.key}")
        seen.add(stack.key)
        if stack.shape not in (WIDE, JOINED, LONG):
            raise ValueError(f"{stack.key}: unknown shape {stack.shape!r}")
        if stack.shape == JOINED and not stack.joined_header:
            raise ValueError(f"{stack.key}: joined shape needs a joined_header")
    return stacks


def get_stack(key: str, path: str = _DEFAULT_TEMPLATES) -> MediaStack:
    for stack in load_stacks(path):
        if stack.key == key:
            return stack
    raise KeyError(f"Unknown media stack: {key}")
