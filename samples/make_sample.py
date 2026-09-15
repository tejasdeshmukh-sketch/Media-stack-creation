"""Regenerate samples/sample_input.xlsx.

Deliberately messy: out-of-order sequences, a blank SKU, a blank link, a text
sequence, a duplicate URL, a duplicate sequence and two dead links -- so every
branch of the app has something to show.

    python samples/make_sample.py
"""

from __future__ import annotations

import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sample_input.xlsx")


def img(seed: str, size: int = 800) -> str:
    return f"https://picsum.photos/seed/{seed}/{size}/{size}"


ROWS = [
    # SKU,        Brand,     Title,                  Sequence, Image Link
    ("MMF-1001", "Northrig", "Trail Runner - Slate",   3, img("mmf1001c")),
    ("MMF-1001", "Northrig", "Trail Runner - Slate",   1, img("mmf1001a")),
    ("MMF-1001", "Northrig", "Trail Runner - Slate",   2, img("mmf1001b")),
    ("MMF-1001", "Northrig", "Trail Runner - Slate",   4, img("mmf1001d")),

    ("MMF-1002", "Northrig", "Trail Runner - Clay",    2, img("mmf1002b")),
    ("MMF-1002", "Northrig", "Trail Runner - Clay",    1, img("mmf1002a")),
    ("MMF-1002", "Northrig", "Trail Runner - Clay",    3, "https://example.invalid/missing-1.jpg"),

    # eleven images -- more than Amazon's nine, to exercise the cap
    *[("MMF-1003", "Caldera", "Cast Iron Skillet 12in", n, img(f"mmf1003-{n}")) for n in range(1, 12)],

    ("MMF-1004", "Caldera", "Cast Iron Skillet 10in",  1, img("mmf1004a")),
    ("MMF-1004", "Caldera", "Cast Iron Skillet 10in",  2, img("mmf1004a")),   # duplicate URL
    ("MMF-1004", "Caldera", "Cast Iron Skillet 10in",  2, img("mmf1004b")),   # duplicate sequence
    ("MMF-1004", "Caldera", "Cast Iron Skillet 10in",  3, "https://example.invalid/missing-2.jpg"),

    ("MMF-1005", "Lumen",   "Desk Lamp - Brass",       1, img("mmf1005a", 400)),  # under 1600px
    ("MMF-1005", "Lumen",   "Desk Lamp - Brass",       2, img("mmf1005b")),

    # rows the macro silently discards
    ("",         "Lumen",   "Desk Lamp - Chrome",      1, img("orphan")),          # no SKU
    ("MMF-1006", "Lumen",   "Desk Lamp - Chrome",      1, ""),                     # no link
    ("MMF-1006", "Lumen",   "Desk Lamp - Chrome", "main", img("mmf1006a")),        # text sequence
    ("MMF-1006", "Lumen",   "Desk Lamp - Chrome",      2, img("mmf1006b")),
]


def main() -> None:
    frame = pd.DataFrame(ROWS, columns=["SKU", "Brand", "Title", "Sequence", "Image Link"])
    frame.to_excel(OUT, index=False, sheet_name="media_feed")
    print(f"wrote {OUT} ({len(frame)} rows)")


if __name__ == "__main__":
    main()
