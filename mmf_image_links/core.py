"""Python port of MMF_ImageLinks_By_SKU_Sequence.

Reads SKU / Sequence / Image Link from fixed columns (A / D / E by default,
matching the original macro), sorts by SKU then sequence, groups by SKU and
pivots into whichever media stack layout was chosen.

Everything in here is pure -- no Streamlit, no I/O side effects -- so the same
functions back the UI, the CLI and the tests.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import pandas as pd
from openpyxl.utils import column_index_from_string

from .stacks import JOINED, LONG, TRUNCATE, WIDE, MediaStack

# Defaults mirror the VBA: A = SKU, D = Sequence, E = Image Link, header on row 1.
DEFAULT_SKU_COL = "A"
DEFAULT_SEQ_COL = "D"
DEFAULT_URL_COL = "E"
DEFAULT_HEADER_ROW = 1


@dataclass(frozen=True)
class ImageRow:
    sku: str
    sequence: float
    url: str
    source_row: int


@dataclass(frozen=True)
class SkippedRow:
    source_row: int
    sku: Any
    sequence: Any
    url: Any
    reason: str


@dataclass
class ParseResult:
    rows: list[ImageRow] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    total_data_rows: int = 0
    sheet_name: str | None = None

    @property
    def sku_count(self) -> int:
        return len({r.sku for r in self.rows})

    def skipped_frame(self) -> pd.DataFrame:
        return rows_to_frame(self.skipped)


@dataclass
class BuildResult:
    frame: pd.DataFrame
    grouped: dict[str, list[ImageRow]]
    warnings: list[str] = field(default_factory=list)
    dropped: list[SkippedRow] = field(default_factory=list)
    max_images: int = 0


def _text(value: Any) -> str:
    """Stringify for display -- keeps mixed-type audit columns Arrow-friendly."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def rows_to_frame(skipped: Sequence["SkippedRow"]) -> pd.DataFrame:
    """Audit table for rows the tool refused or dropped."""
    return pd.DataFrame(
        [
            {
                "Row": s.source_row,
                "SKU": _text(s.sku),
                "Sequence": _text(s.sequence),
                "Image Link": _text(s.url),
                "Reason": s.reason,
            }
            for s in skipped
        ],
        columns=["Row", "SKU", "Sequence", "Image Link", "Reason"],
    )


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def _as_number(value: Any) -> float | None:
    """VBA's IsNumeric, close enough: accepts numbers and numeric-looking text.

    Rejects nan/inf, which float() happily parses but IsNumeric does not -- the
    literal text "nan" turns up in CSVs exported from pandas, and a NaN sequence
    poisons the sort (every comparison against it is False).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "")
        # float() accepts PEP 515 underscores ("1_0" -> 10.0); IsNumeric does not.
        if not text or "_" in text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


_NUMERIC_SKU = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def _sku_sort_key(sku: str) -> tuple[int, float, str]:
    """Excel's sort order: numbers ascending first, then text case-insensitively.

    The macro wrote SKUs back into cells, so Excel coerced numeric-looking ones
    to numbers and sorted 9 before 10. This reproduces that ordering without
    coercing the value itself, so "007" still exports as "007".
    """
    text = sku.strip()
    if _NUMERIC_SKU.match(text):
        try:
            return (0, float(text), "")
        except ValueError:  # pragma: no cover -- regex already guarantees this
            pass
    return (1, 0.0, text.casefold())


def read_table(
    source: str | bytes | io.BytesIO,
    *,
    sheet_name: str | int | None = 0,
    header_row: int = DEFAULT_HEADER_ROW,
    filename: str | None = None,
) -> pd.DataFrame:
    """Load a sheet as a raw, header-less frame so columns stay positional."""
    name = (filename or (source if isinstance(source, str) else "")).lower()
    skip = max(header_row, 0)
    if name.endswith((".csv", ".txt", ".tsv")):
        sep = "\t" if name.endswith(".tsv") else None
        buf = io.BytesIO(source) if isinstance(source, bytes) else source
        return pd.read_csv(
            buf, header=None, skiprows=skip, dtype=object,
            sep=sep, engine="python", keep_default_na=False, na_values=[""],
        )
    if sheet_name is None:
        raise ValueError("sheet_name=None would read every sheet; pass a name or an index.")
    buf = io.BytesIO(source) if isinstance(source, bytes) else source
    return pd.read_excel(buf, sheet_name=sheet_name, header=None, skiprows=skip, dtype=object)


def sheet_names(source: str | bytes | io.BytesIO, filename: str | None = None) -> list[str]:
    name = (filename or (source if isinstance(source, str) else "")).lower()
    if name.endswith((".csv", ".txt", ".tsv")):
        return []
    buf = io.BytesIO(source) if isinstance(source, bytes) else source
    with pd.ExcelFile(buf) as xls:
        return list(xls.sheet_names)


def parse_rows(
    frame: pd.DataFrame,
    *,
    sku_col: str = DEFAULT_SKU_COL,
    seq_col: str = DEFAULT_SEQ_COL,
    url_col: str = DEFAULT_URL_COL,
    header_row: int = DEFAULT_HEADER_ROW,
    sheet_name: str | None = None,
) -> ParseResult:
    """Apply the macro's row filter, recording *why* each rejected row was dropped."""
    result = ParseResult(sheet_name=sheet_name)
    idx = {
        "sku": column_index_from_string(sku_col.strip().upper()) - 1,
        "seq": column_index_from_string(seq_col.strip().upper()) - 1,
        "url": column_index_from_string(url_col.strip().upper()) - 1,
    }
    width = frame.shape[1]
    missing = [letter for letter, i in zip((sku_col, seq_col, url_col), idx.values()) if i >= width]
    if missing:
        raise ValueError(
            f"Column(s) {', '.join(m.upper() for m in missing)} are past the end of the sheet "
            f"(it only has {width} column{'s' if width != 1 else ''})."
        )

    for offset, (_, record) in enumerate(frame.iterrows()):
        source_row = header_row + offset + 1
        raw_sku = record.iloc[idx["sku"]]
        raw_seq = record.iloc[idx["seq"]]
        raw_url = record.iloc[idx["url"]]

        if _blank(raw_sku) and _blank(raw_seq) and _blank(raw_url):
            continue  # entirely empty row -- not worth reporting
        result.total_data_rows += 1

        sku = "" if _blank(raw_sku) else str(raw_sku).strip()
        url = "" if _blank(raw_url) else str(raw_url).strip()
        seq = _as_number(raw_seq)

        reasons = []
        if not sku:
            reasons.append("blank SKU")
        if not url:
            reasons.append("blank image link")
        if seq is None:
            reasons.append("sequence is not numeric")

        if reasons:
            result.skipped.append(
                SkippedRow(source_row, raw_sku, raw_seq, raw_url, " + ".join(reasons))
            )
            continue

        result.rows.append(ImageRow(sku=sku, sequence=seq, url=url, source_row=source_row))

    return result


def sort_rows(rows: Iterable[ImageRow]) -> list[ImageRow]:
    """SKU ascending then sequence ascending, the way the macro's two-key sort does.

    SKUs order the way Excel would (numeric ones first and numerically, text
    case-insensitively). Ties on (sku, sequence) keep their original file order.
    """
    return sorted(rows, key=lambda r: (_sku_sort_key(r.sku), r.sequence, r.source_row))


def group_by_sku(rows: Iterable[ImageRow]) -> dict[str, list[ImageRow]]:
    grouped: dict[str, list[ImageRow]] = {}
    for row in sort_rows(rows):
        grouped.setdefault(row.sku, []).append(row)
    return grouped


def _dedupe(images: Sequence[ImageRow]) -> tuple[list[ImageRow], list[ImageRow]]:
    seen: set[str] = set()
    kept, removed = [], []
    for image in images:
        key = image.url.strip()
        if key in seen:
            removed.append(image)
        else:
            seen.add(key)
            kept.append(image)
    return kept, removed


def build_output(
    rows: Iterable[ImageRow],
    stack: MediaStack,
    *,
    cap_override: int | None = None,
    dedupe: bool = False,
    exclude_urls: Iterable[str] | None = None,
) -> BuildResult:
    """Pivot grouped rows into the chosen media stack layout."""
    excluded = {u.strip() for u in (exclude_urls or []) if u}
    grouped = group_by_sku(rows)
    cap = stack.effective_cap(cap_override)

    warnings: list[str] = []
    dropped: list[SkippedRow] = []
    prepared: dict[str, list[ImageRow]] = {}

    for sku, images in grouped.items():
        if excluded:
            kept = [i for i in images if i.url.strip() not in excluded]
            for image in images:
                if image.url.strip() in excluded:
                    dropped.append(
                        SkippedRow(image.source_row, sku, image.sequence, image.url, "excluded: broken link")
                    )
            images = kept
        if dedupe:
            images, removed = _dedupe(images)
            for image in removed:
                dropped.append(
                    SkippedRow(image.source_row, sku, image.sequence, image.url, "duplicate URL within SKU")
                )

        seen_seq: dict[float, int] = {}
        for image in images:
            seen_seq[image.sequence] = seen_seq.get(image.sequence, 0) + 1
        dupes = sorted(s for s, c in seen_seq.items() if c > 1)
        if dupes:
            pretty = ", ".join(f"{s:g}" for s in dupes[:5])
            warnings.append(f"{sku}: repeated sequence value(s) {pretty} -- order between them is by file position.")

        if cap is not None and len(images) > cap:
            overflow = len(images) - cap
            if stack.on_overflow == TRUNCATE:
                for image in images[cap:]:
                    dropped.append(
                        SkippedRow(image.source_row, sku, image.sequence, image.url,
                                   f"over the {cap}-image limit for {stack.label}")
                    )
                images = images[:cap]
                warnings.append(f"{sku}: {overflow} image(s) dropped -- {stack.label} allows {cap}.")
            else:
                warnings.append(f"{sku}: {len(images)} images exceeds the {cap} {stack.label} allows.")

        if images:
            prepared[sku] = images

    max_images = max((len(v) for v in prepared.values()), default=0)

    if stack.shape == LONG:
        frame = _long_frame(prepared, stack)
    elif stack.shape == JOINED:
        frame = _joined_frame(prepared, stack)
    else:
        frame = _wide_frame(prepared, stack, max_images)

    return BuildResult(frame=frame, grouped=prepared, warnings=warnings, dropped=dropped, max_images=max_images)


def _wide_frame(grouped: dict[str, list[ImageRow]], stack: MediaStack, max_images: int) -> pd.DataFrame:
    columns = [stack.sku_header]
    if stack.has_main_column:
        columns.append(stack.main_header or "Main Image")
        columns += [stack.other_column_name(n) for n in range(1, max(max_images - 1, 0) + 1)]
    else:
        columns += [stack.other_column_name(n) for n in range(1, max_images + 1)]

    records = []
    for sku, images in grouped.items():
        record: dict[str, Any] = {stack.sku_header: sku}
        for position, image in enumerate(images):
            record[columns[position + 1]] = image.url
        records.append(record)
    return pd.DataFrame(records, columns=columns).fillna("")


def _joined_frame(grouped: dict[str, list[ImageRow]], stack: MediaStack) -> pd.DataFrame:
    columns = [stack.sku_header]
    if stack.has_main_column:
        columns.append(stack.main_header or "Main Image")
    columns.append(stack.joined_header or "Images")

    records = []
    for sku, images in grouped.items():
        record: dict[str, Any] = {stack.sku_header: sku}
        rest = images
        if stack.has_main_column:
            record[columns[1]] = images[0].url if images else ""
            rest = images[1:]
        record[columns[-1]] = stack.delimiter.join(i.url for i in rest)
        records.append(record)
    return pd.DataFrame(records, columns=columns).fillna("")


def _long_frame(grouped: dict[str, list[ImageRow]], stack: MediaStack) -> pd.DataFrame:
    columns = [stack.sku_header, stack.url_header, stack.position_header]
    records = []
    for sku, images in grouped.items():
        for position, image in enumerate(images):
            records.append({
                stack.sku_header: sku,
                stack.url_header: image.url,
                stack.position_header: position + stack.position_start,
            })
    return pd.DataFrame(records, columns=columns)


def run(
    source: str | bytes | io.BytesIO,
    stack: MediaStack,
    *,
    sheet_name: str | int | None = 0,
    header_row: int = DEFAULT_HEADER_ROW,
    sku_col: str = DEFAULT_SKU_COL,
    seq_col: str = DEFAULT_SEQ_COL,
    url_col: str = DEFAULT_URL_COL,
    filename: str | None = None,
    **build_kwargs: Any,
) -> tuple[ParseResult, BuildResult]:
    """Convenience end-to-end: read -> parse -> build."""
    frame = read_table(source, sheet_name=sheet_name, header_row=header_row, filename=filename)
    parsed = parse_rows(
        frame, sku_col=sku_col, seq_col=seq_col, url_col=url_col,
        header_row=header_row, sheet_name=str(sheet_name) if sheet_name is not None else None,
    )
    built = build_output(parsed.rows, stack, **build_kwargs)
    return parsed, built
