"""Headless runner: same logic as the app, for batch jobs and CI.

    python -m mmf_image_links.cli input.xlsx -s amazon_flatfile -o out.xlsx --validate
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import core, export, validate
from .stacks import load_stacks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmf-image-links", description=__doc__.splitlines()[0])
    parser.add_argument("input", help="source .xlsx / .xlsm / .csv")
    parser.add_argument("-s", "--stack", default="vba_legacy", help="media stack key (see --list-stacks)")
    parser.add_argument("-o", "--output", help="output path (.xlsx or .csv); defaults to stdout summary only")
    parser.add_argument("--sheet", default=0, help="sheet name or index (default: first)")
    parser.add_argument("--header-row", type=int, default=core.DEFAULT_HEADER_ROW)
    parser.add_argument("--sku-col", default=core.DEFAULT_SKU_COL)
    parser.add_argument("--seq-col", default=core.DEFAULT_SEQ_COL)
    parser.add_argument("--url-col", default=core.DEFAULT_URL_COL)
    parser.add_argument("--cap", type=int, default=None, help="override the stack's image cap")
    parser.add_argument("--dedupe", action="store_true", help="drop duplicate URLs within a SKU")
    parser.add_argument("--validate", action="store_true", help="check that every image URL loads")
    parser.add_argument("--exclude-broken", action="store_true", help="omit unreachable URLs (implies --validate)")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--list-stacks", action="store_true", help="print the available media stacks and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_stacks:
        for stack in load_stacks():
            cap = "unlimited" if stack.max_images is None else str(stack.max_images)
            print(f"{stack.key:<20} {stack.label}  [shape={stack.shape}, max={cap}]")
        return 0

    stacks = {s.key: s for s in load_stacks()}
    if args.stack not in stacks:
        print(f"Unknown stack {args.stack!r}. Try --list-stacks.", file=sys.stderr)
        return 2
    stack = stacks[args.stack]

    sheet = args.sheet
    if isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)

    try:
        frame = core.read_table(args.input, sheet_name=sheet, header_row=args.header_row,
                                filename=args.input)
        parsed = core.parse_rows(
            frame, sku_col=args.sku_col, seq_col=args.seq_col,
            url_col=args.url_col, header_row=args.header_row,
        )
    except (ValueError, pd.errors.ParserError) as exc:
        print(f"Could not read {args.input}: {exc}", file=sys.stderr)
        return 2
    if not parsed.rows:
        print("No valid SKU / Sequence / Image Link rows found.", file=sys.stderr)
        return 1

    checks: dict[str, validate.UrlCheck] = {}
    if args.validate or args.exclude_broken:
        checks = validate.check_urls([r.url for r in parsed.rows], workers=args.workers)
        summary = validate.summarize(checks)
        print(f"link check: {summary['ok']} ok, {summary['broken']} broken, of {summary['checked']}")

    built = core.build_output(
        parsed.rows, stack,
        cap_override=args.cap, dedupe=args.dedupe,
        exclude_urls=validate.broken_urls(checks) if args.exclude_broken else None,
    )

    print(f"stack       : {stack.label}")
    print(f"rows read   : {parsed.total_data_rows}")
    print(f"usable      : {len(parsed.rows)} image(s) across {parsed.sku_count} SKU(s)")
    print(f"skipped     : {len(parsed.skipped)}")
    print(f"output      : {len(built.frame)} row(s) x {len(built.frame.columns)} column(s)")
    for warning in built.warnings:
        print(f"  warn: {warning}")

    if args.output:
        if args.output.lower().endswith(".csv"):
            with open(args.output, "wb") as fh:
                fh.write(export.to_csv(built.frame))
        else:
            audit = parsed.skipped_frame()
            check_frame = pd.DataFrame(validate.as_rows(checks)) if checks else None
            with open(args.output, "wb") as fh:
                fh.write(export.to_workbook(
                    built.frame, skipped=audit, checks=check_frame, warnings=built.warnings
                ))
        print(f"written     : {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
