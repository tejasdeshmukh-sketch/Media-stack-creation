"""MMF Image Links -- Streamlit front end.

Upload -> choose a media stack -> eyeball every image in sequence order ->
download the pivoted file.
"""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from mmf_image_links import core, export, validate
from mmf_image_links.stacks import LONG, load_stacks

TOOL_TITLE = "MMF Image Links"
CREDIT = "Logic originally designed and developed by Yash Kende"

st.set_page_config(page_title=TOOL_TITLE, page_icon="🖼️", layout="wide")

CSS = """
<style>
  .stack-note   { color:#6b7280; font-size:0.86rem; line-height:1.45; margin:-0.4rem 0 0.6rem; }
  .tile         { border:1px solid #e5e7eb; border-radius:10px; overflow:hidden; background:#fff;
                  margin-bottom:0.65rem; }
  .tile.bad     { border-color:#dc2626; box-shadow:0 0 0 1px #dc2626 inset; }
  .tile.warn    { border-color:#d97706; box-shadow:0 0 0 1px #d97706 inset; }
  .tile-head    { display:flex; justify-content:space-between; align-items:center; gap:6px;
                  padding:5px 9px; font-size:0.72rem; font-weight:600; background:#f9fafb;
                  border-bottom:1px solid #e5e7eb; }
  .slot         { color:#111827; letter-spacing:0.02em; text-transform:uppercase; }
  .pill         { border-radius:999px; padding:1px 8px; font-size:0.66rem; font-weight:700; }
  .pill.ok      { background:#dcfce7; color:#166534; }
  .pill.bad     { background:#fee2e2; color:#991b1b; }
  .pill.warn    { background:#fef3c7; color:#92400e; }
  .pill.none    { background:#e5e7eb; color:#4b5563; }
  .thumb        { width:100%; aspect-ratio:1/1; object-fit:contain; background:#f3f4f6; display:block; }
  .thumb-dead   { width:100%; aspect-ratio:1/1; background:repeating-linear-gradient(45deg,#fef2f2,
                  #fef2f2 9px,#fee2e2 9px,#fee2e2 18px); display:flex; align-items:center;
                  justify-content:center; color:#991b1b; font-size:0.74rem; font-weight:600;
                  text-align:center; padding:8px; }
  .tile-foot    { padding:5px 9px; font-size:0.66rem; color:#6b7280; word-break:break-all;
                  border-top:1px solid #f3f4f6; }
  .sku-head     { font-weight:700; font-size:0.95rem; margin:0.9rem 0 0.35rem; }
  @media (prefers-color-scheme: dark) {
    .tile      { background:#111827; border-color:#374151; }
    .tile-head { background:#1f2937; border-color:#374151; }
    .slot      { color:#f9fafb; }
    .tile-foot { border-color:#1f2937; }
  }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- helpers

def status_pill(check: validate.UrlCheck | None, min_side: int) -> tuple[str, str, str]:
    """-> (tile css class, pill css class, pill text)"""
    if check is None:
        return "", "none", "not checked"
    if not check.ok:
        return "bad", "bad", check.label()
    if not check.is_image:
        return "warn", "warn", "not an image"
    side = check.longest_side
    if min_side and side and side < min_side:
        return "warn", "warn", f"{check.width}x{check.height} small"
    return "", "ok", check.label()


def tile_html(url: str, slot: str, check: validate.UrlCheck | None, min_side: int) -> str:
    tile_cls, pill_cls, pill_text = status_pill(check, min_side)
    safe_url = html.escape(url, quote=True)
    short = url if len(url) <= 70 else url[:34] + "..." + url[-30:]
    dead = check is not None and not check.ok
    body = (
        f'<div class="thumb-dead">link failed<br>{html.escape(pill_text)}</div>'
        if dead
        else f'<img class="thumb" src="{safe_url}" loading="lazy" alt="{html.escape(slot)}">'
    )
    return (
        f'<div class="tile {tile_cls}">'
        f'<div class="tile-head"><span class="slot">{html.escape(slot)}</span>'
        f'<span class="pill {pill_cls}">{html.escape(pill_text)}</span></div>'
        f'{body}'
        f'<div class="tile-foot"><a href="{safe_url}" target="_blank" rel="noopener">{html.escape(short)}</a></div>'
        f'</div>'
    )


def reset_downstream() -> None:
    st.session_state.pop("checks", None)


# --------------------------------------------------------------------------- sidebar

stacks = load_stacks()

with st.sidebar:
    st.header("1 · Source")
    upload = st.file_uploader(
        "Excel or CSV export",
        type=["xlsx", "xlsm", "xls", "csv", "tsv", "txt"],
        on_change=reset_downstream,
    )

    st.caption("Columns follow the original macro. Change them if your export differs.")
    col_a, col_b, col_c = st.columns(3)
    sku_col = col_a.text_input("SKU", core.DEFAULT_SKU_COL, max_chars=3)
    seq_col = col_b.text_input("Sequence", core.DEFAULT_SEQ_COL, max_chars=3)
    url_col = col_c.text_input("Image link", core.DEFAULT_URL_COL, max_chars=3)
    header_row = st.number_input("Header rows to skip", min_value=0, max_value=20,
                                 value=core.DEFAULT_HEADER_ROW, step=1)

    st.header("2 · Media stack")
    stack = st.selectbox(
        "Output layout",
        options=stacks,
        format_func=lambda s: s.label,
        help="Controls the output column names and how many images each SKU may carry.",
    )
    st.markdown(f'<div class="stack-note">{html.escape(stack.description)}</div>', unsafe_allow_html=True)

    limit_text = "no limit" if stack.max_images is None else f"{stack.max_images} images"
    st.caption(f"Template limit: **{limit_text}** · shape: `{stack.shape}`")

    use_cap = st.checkbox("Override the image cap")
    cap_override = None
    if use_cap:
        cap_override = int(st.number_input("Max images per SKU", min_value=1, max_value=250, value=7, step=1))

    dedupe = st.checkbox("Drop duplicate URLs within a SKU", value=False)

    st.header("3 · Link check")
    do_validate = st.checkbox("Validate that image URLs load", value=True)
    measure = st.checkbox("Read image dimensions", value=True, disabled=not do_validate,
                          help="Downloads the first chunk of each image to get width x height.")
    # A fixed default + key, so toggling `measure` doesn't re-register the widget
    # and throw away a threshold the user typed.
    min_side = int(st.number_input("Flag images under (px, longest side)", min_value=0, max_value=5000,
                                   value=1600, step=100, key="min_side",
                                   disabled=not (do_validate and measure)))
    exclude_broken = st.checkbox("Exclude broken links from the output", value=False, disabled=not do_validate)
    workers = int(st.slider("Parallel requests", 1, 32, 12, disabled=not do_validate))

    st.divider()
    st.caption(CREDIT)


# --------------------------------------------------------------------------- main

st.title(TOOL_TITLE)
st.caption("Group image links by SKU, order them by sequence, and pivot them into your channel's template.")

if upload is None:
    st.info(
        "Upload an export to begin. Expected shape, straight from the macro: "
        "**column A = SKU**, **column D = Sequence**, **column E = Image Link**, one image per row."
    )
    with st.expander("What this does"):
        st.markdown(
            "1. Keeps rows that have a SKU, an image link and a **numeric** sequence.\n"
            "2. Sorts by SKU, then sequence ascending.\n"
            "3. Groups by SKU -- lowest sequence becomes the main image.\n"
            "4. Pivots into the media stack you picked, and reports anything it had to drop."
        )
    st.stop()

raw = upload.getvalue()

sheet = 0
try:
    names = core.sheet_names(raw, filename=upload.name)
except Exception as exc:
    st.error(f"Could not open that file: {exc}")
    st.stop()

if names:
    sheet = st.selectbox("Sheet", names, index=0)

try:
    frame = core.read_table(raw, sheet_name=sheet, header_row=int(header_row), filename=upload.name)
    parsed = core.parse_rows(
        frame, sku_col=sku_col, seq_col=seq_col, url_col=url_col,
        header_row=int(header_row), sheet_name=str(sheet),
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:
    st.error(f"Could not read that sheet: {exc}")
    st.stop()

if not parsed.rows:
    st.error("No valid SKU / Sequence / Image Link rows found.")
    if parsed.skipped:
        st.dataframe(parsed.skipped_frame(), width="stretch", hide_index=True)
    st.stop()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Rows read", parsed.total_data_rows)
m2.metric("Usable images", len(parsed.rows))
m3.metric("Unique SKUs", parsed.sku_count)
m4.metric("Rows skipped", len(parsed.skipped), delta=None if not parsed.skipped else "check below",
          delta_color="off")

if parsed.skipped:
    with st.expander(f"{len(parsed.skipped)} row(s) skipped -- the macro dropped these silently"):
        st.dataframe(parsed.skipped_frame(), width="stretch", hide_index=True)

# --- link validation -------------------------------------------------------

all_urls = [row.url for row in parsed.rows]

# The cache is only valid for the settings that produced it: a result gathered
# without dimensions has width=None, which would otherwise read as "not small".
cache_signature = (upload.name, str(sheet), sku_col, seq_col, url_col, int(header_row), measure)
if st.session_state.get("checks_signature") != cache_signature:
    st.session_state.pop("checks", None)
    st.session_state["checks_signature"] = cache_signature

checks: dict[str, validate.UrlCheck] = st.session_state.get("checks", {})

if do_validate:
    pending = [u for u in dict.fromkeys(all_urls) if u not in checks]
    if pending:
        bar = st.progress(0.0, text=f"Checking {len(pending)} image URL(s)...")
        fresh = validate.check_urls(
            pending, workers=workers, measure=measure,
            progress=lambda done, total: bar.progress(done / total, text=f"Checked {done} of {total}"),
        )
        bar.empty()
        checks.update(fresh)
        st.session_state["checks"] = checks

    # Report only on URLs that are actually in this run's output.
    checks = {u: checks[u] for u in dict.fromkeys(all_urls) if u in checks}
    summary = validate.summarize(checks)
    small = validate.undersized(checks, min_side) if (min_side and measure) else []
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Links checked", summary["checked"])
    c2.metric("Reachable", summary["ok"])
    c3.metric("Broken", summary["broken"])
    c4.metric(f"Under {min_side}px" if (min_side and measure) else "Not an image",
              len(small) if (min_side and measure) else summary["not_an_image"])

    if summary["broken"]:
        with st.expander(f"{summary['broken']} broken link(s)"):
            bad = validate.broken_urls(checks)
            st.dataframe(pd.DataFrame(validate.as_rows(checks, bad)), width="stretch", hide_index=True)
    if st.button("Re-check all links"):
        st.session_state.pop("checks", None)
        st.rerun()
else:
    checks = {}

# --- build -----------------------------------------------------------------

built = core.build_output(
    parsed.rows,
    stack,
    cap_override=cap_override,
    dedupe=dedupe,
    exclude_urls=validate.broken_urls(checks) if (do_validate and exclude_broken) else None,
)

if built.warnings:
    with st.expander(f"{len(built.warnings)} warning(s)"):
        for warning in built.warnings:
            st.write("• " + warning)

preview_tab, output_tab = st.tabs(["Preview images", f"Output · {stack.label}"])

# --- preview tab -----------------------------------------------------------

with preview_tab:
    skus = list(built.grouped)
    if not skus:
        st.warning("Every image was filtered out. Loosen the cap or turn off 'exclude broken links'.")
    else:
        left, right = st.columns([3, 1])
        search = left.text_input("Filter SKUs", placeholder="type part of a SKU")
        per_page = int(right.selectbox("SKUs per page", [5, 10, 25, 50], index=1))

        shown = [s for s in skus if search.strip().lower() in s.lower()] if search.strip() else skus
        if not shown:
            st.info("No SKU matches that filter.")
        else:
            pages = (len(shown) + per_page - 1) // per_page
            page = 1
            if pages > 1:
                page = int(st.number_input(f"Page (1-{pages})", min_value=1, max_value=pages, value=1, step=1))
            window = shown[(page - 1) * per_page: page * per_page]
            st.caption(f"Showing {len(window)} of {len(shown)} SKU(s), images left-to-right in sequence order.")

            for sku in window:
                images = built.grouped[sku]
                labels = stack.column_labels(len(images))
                bad_count = sum(1 for i in images if (c := checks.get(i.url)) and not c.ok)
                flag = f" · :red[{bad_count} broken]" if bad_count else ""
                st.markdown(
                    f'<div class="sku-head">{html.escape(sku)} '
                    f'<span style="font-weight:400;color:#6b7280">({len(images)} image'
                    f'{"s" if len(images) != 1 else ""})</span></div>',
                    unsafe_allow_html=True,
                )
                if flag:
                    st.markdown(flag)
                per_row = 6
                for start in range(0, len(images), per_row):
                    chunk = images[start:start + per_row]
                    columns = st.columns(per_row)
                    for offset, image in enumerate(chunk):
                        slot = labels[start + offset] if start + offset < len(labels) else f"#{start + offset + 1}"
                        with columns[offset]:
                            st.markdown(
                                tile_html(image.url, f"{slot} · seq {image.sequence:g}",
                                          checks.get(image.url), min_side if measure else 0),
                                unsafe_allow_html=True,
                            )
                st.divider()

# --- output tab ------------------------------------------------------------

with output_tab:
    frame_out = built.frame
    rows_label = "rows" if stack.shape == LONG else "SKUs"
    o1, o2, o3 = st.columns(3)
    o1.metric(f"Output {rows_label}", len(frame_out))
    o2.metric("Columns", len(frame_out.columns))
    o3.metric("Most images on one SKU", built.max_images)

    st.dataframe(frame_out, width="stretch", hide_index=True)

    dropped_frame = core.rows_to_frame(built.dropped)
    if built.dropped:
        with st.expander(f"{len(built.dropped)} image(s) dropped while building this stack"):
            st.dataframe(dropped_frame, width="stretch", hide_index=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = f"image_links_{stack.key}_{stamp}"
    check_frame = pd.DataFrame(validate.as_rows(checks)) if checks else None
    skipped_frame = parsed.skipped_frame()
    audit_parts = [f for f in (skipped_frame, dropped_frame) if not f.empty]
    audit = pd.concat(audit_parts, ignore_index=True) if audit_parts else None

    d1, d2 = st.columns(2)
    d1.download_button(
        "Download Excel",
        data=export.to_workbook(frame_out, skipped=audit, checks=check_frame, warnings=built.warnings),
        file_name=f"{base}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    d2.download_button(
        "Download CSV",
        data=export.to_csv(frame_out),
        file_name=f"{base}.csv",
        mime="text/csv",
        width="stretch",
    )
    st.caption("The Excel file carries extra sheets for skipped rows, dropped images, link checks and warnings.")
