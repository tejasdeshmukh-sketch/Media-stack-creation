from __future__ import annotations

import io

import pandas as pd
import pytest

from mmf_image_links import core
from mmf_image_links.stacks import get_stack, load_stacks


def make_frame(records):
    """Build a header-less frame shaped like the macro expects: A,B,C,D,E."""
    rows = []
    for sku, seq, url in records:
        rows.append([sku, None, None, seq, url])
    return pd.DataFrame(rows)


def parse(records, **kwargs):
    return core.parse_rows(make_frame(records), **kwargs)


# --------------------------------------------------------------------- parsing

def test_keeps_only_complete_rows():
    parsed = parse([
        ("SKU-1", 1, "http://x/1.jpg"),
        ("", 2, "http://x/2.jpg"),          # blank SKU
        ("SKU-1", 3, ""),                   # blank link
        ("SKU-1", "abc", "http://x/4.jpg"), # non-numeric sequence
        ("SKU-2", 1, "http://x/5.jpg"),
    ])
    assert len(parsed.rows) == 2
    assert len(parsed.skipped) == 3
    assert parsed.total_data_rows == 5
    reasons = {s.reason for s in parsed.skipped}
    assert reasons == {"blank SKU", "blank image link", "sequence is not numeric"}


def test_numeric_strings_count_as_numeric():
    parsed = parse([("SKU-1", "2", "http://x/2.jpg"), ("SKU-1", " 1 ", "http://x/1.jpg")])
    assert len(parsed.rows) == 2
    assert [r.sequence for r in core.sort_rows(parsed.rows)] == [1.0, 2.0]


def test_values_are_trimmed():
    parsed = parse([("  SKU-1  ", 1, "  http://x/1.jpg  ")])
    assert parsed.rows[0].sku == "SKU-1"
    assert parsed.rows[0].url == "http://x/1.jpg"


def test_fully_blank_rows_are_ignored_not_reported():
    parsed = parse([("SKU-1", 1, "http://x/1.jpg"), (None, None, None)])
    assert parsed.total_data_rows == 1
    assert parsed.skipped == []


def test_source_row_numbers_account_for_the_header():
    parsed = parse([("SKU-1", 1, "http://x/1.jpg")], header_row=1)
    assert parsed.rows[0].source_row == 2  # row 1 is the header, like the VBA loop from r=2


def test_missing_column_raises_a_readable_error():
    narrow = pd.DataFrame([["SKU-1", 1]])
    with pytest.raises(ValueError, match="past the end of the sheet"):
        core.parse_rows(narrow, url_col="E")


# ---------------------------------------------------------------- sort / group

def test_sorts_by_sku_then_sequence():
    parsed = parse([
        ("B", 2, "b2"), ("A", 3, "a3"), ("B", 1, "b1"), ("A", 1, "a1"), ("A", 2, "a2"),
    ])
    grouped = core.group_by_sku(parsed.rows)
    assert list(grouped) == ["A", "B"]
    assert [r.url for r in grouped["A"]] == ["a1", "a2", "a3"]
    assert [r.url for r in grouped["B"]] == ["b1", "b2"]


def test_non_integer_and_negative_sequences_sort_numerically():
    parsed = parse([("A", 10, "ten"), ("A", 2, "two"), ("A", 1.5, "one-five"), ("A", -1, "neg")])
    assert [r.url for r in core.sort_rows(parsed.rows)] == ["neg", "one-five", "two", "ten"]


def test_sku_grouping_is_case_insensitive_in_ordering_only():
    parsed = parse([("b-1", 1, "b"), ("A-1", 1, "a")])
    grouped = core.group_by_sku(parsed.rows)
    assert list(grouped) == ["A-1", "b-1"]  # Excel's text sort ignores case


# --------------------------------------------------------------- wide output

def test_vba_parity_layout():
    parsed = parse([("A", 1, "a1"), ("A", 2, "a2"), ("A", 3, "a3"), ("B", 1, "b1")])
    built = core.build_output(parsed.rows, get_stack("vba_legacy"))
    assert list(built.frame.columns) == ["Master Id/ Sku", "Main Image", "Other Image 1", "Other Image 2"]
    row_a = built.frame.iloc[0]
    assert row_a["Master Id/ Sku"] == "A"
    assert row_a["Main Image"] == "a1"
    assert row_a["Other Image 1"] == "a2"
    assert row_a["Other Image 2"] == "a3"
    # short SKUs pad with empty strings, exactly like the macro leaves blank cells
    assert built.frame.iloc[1]["Other Image 1"] == ""


def test_column_count_follows_the_widest_sku():
    parsed = parse([("A", 1, "a1"), ("B", 1, "b1"), ("B", 2, "b2"), ("B", 3, "b3")])
    built = core.build_output(parsed.rows, get_stack("vba_legacy"))
    assert built.max_images == 3
    assert len(built.frame.columns) == 4


def test_amazon_headers_and_cap():
    records = [("A", i, f"a{i}") for i in range(1, 13)]  # 12 images, Amazon allows 9
    built = core.build_output(parse(records).rows, get_stack("amazon_flatfile"))
    assert list(built.frame.columns) == ["item_sku", "main_image_url"] + [
        f"other_image_url{n}" for n in range(1, 9)
    ]
    assert len(built.dropped) == 3
    assert built.warnings and "3 image(s) dropped" in built.warnings[0]


def test_amazon_pt_zero_padding():
    built = core.build_output(parse([("A", i, f"a{i}") for i in range(1, 4)]).rows, get_stack("amazon_pt"))
    assert list(built.frame.columns) == ["SKU", "MAIN", "PT01", "PT02"]


def test_generic_flat_has_no_main_column():
    built = core.build_output(parse([("A", 1, "a1"), ("A", 2, "a2")]).rows, get_stack("generic_flat"))
    assert list(built.frame.columns) == ["SKU", "Image 1", "Image 2"]


# ------------------------------------------------------- joined / long output

def test_walmart_joins_secondary_images():
    built = core.build_output(parse([("A", i, f"a{i}") for i in range(1, 5)]).rows, get_stack("walmart"))
    assert list(built.frame.columns) == ["SKU", "Main Image URL", "Additional Image URL"]
    assert built.frame.iloc[0]["Main Image URL"] == "a1"
    assert built.frame.iloc[0]["Additional Image URL"] == "a2,a3,a4"


def test_ebay_pipe_joins_every_image():
    built = core.build_output(parse([("A", i, f"a{i}") for i in range(1, 4)]).rows, get_stack("ebay"))
    assert list(built.frame.columns) == ["CustomLabel", "PicURL"]
    assert built.frame.iloc[0]["PicURL"] == "a1|a2|a3"


def test_shopify_emits_one_row_per_image():
    parsed = parse([("A", 1, "a1"), ("A", 2, "a2"), ("B", 1, "b1")])
    built = core.build_output(parsed.rows, get_stack("shopify"))
    assert list(built.frame.columns) == ["Handle", "Image Src", "Image Position"]
    assert len(built.frame) == 3
    assert built.frame["Image Position"].tolist() == [1, 2, 1]
    assert built.frame["Handle"].tolist() == ["A", "A", "B"]


# ------------------------------------------------------------------ options

def test_cap_override_truncates():
    built = core.build_output(parse([("A", i, f"a{i}") for i in range(1, 6)]).rows,
                              get_stack("amazon_flatfile"), cap_override=3)
    assert built.max_images == 3
    assert len(built.dropped) == 2


def test_cap_override_cannot_exceed_the_template_limit():
    stack = get_stack("amazon_flatfile")
    assert stack.effective_cap(50) == 9
    assert stack.effective_cap(4) == 4
    assert get_stack("vba_legacy").effective_cap(4) == 4


def test_dedupe_removes_repeats_within_a_sku_only():
    parsed = parse([("A", 1, "same"), ("A", 2, "same"), ("B", 1, "same")])
    built = core.build_output(parsed.rows, get_stack("vba_legacy"), dedupe=True)
    assert len(built.grouped["A"]) == 1
    assert len(built.grouped["B"]) == 1
    assert len(built.dropped) == 1


def test_excluding_broken_urls_shifts_the_main_image_up():
    parsed = parse([("A", 1, "dead"), ("A", 2, "good2"), ("A", 3, "good3")])
    built = core.build_output(parsed.rows, get_stack("vba_legacy"), exclude_urls=["dead"])
    assert built.frame.iloc[0]["Main Image"] == "good2"
    assert built.dropped[0].reason == "excluded: broken link"


def test_duplicate_sequence_raises_a_warning():
    built = core.build_output(parse([("A", 1, "x"), ("A", 1, "y")]).rows, get_stack("vba_legacy"))
    assert any("repeated sequence" in w for w in built.warnings)


def test_sku_with_every_image_excluded_is_dropped_entirely():
    parsed = parse([("A", 1, "dead"), ("B", 1, "good")])
    built = core.build_output(parsed.rows, get_stack("vba_legacy"), exclude_urls=["dead"])
    assert list(built.grouped) == ["B"]


# ------------------------------------------------------------- file round trip

def test_reads_a_real_xlsx_end_to_end(tmp_path):
    path = tmp_path / "src.xlsx"
    pd.DataFrame(
        [["SKU-1", "x", "y", 2, "http://x/2.jpg"],
         ["SKU-1", "x", "y", 1, "http://x/1.jpg"],
         ["SKU-2", "x", "y", 1, "http://x/3.jpg"]],
        columns=["SKU", "Brand", "Title", "Sequence", "Image Link"],
    ).to_excel(path, index=False)

    parsed, built = core.run(str(path), get_stack("vba_legacy"))
    assert len(parsed.rows) == 3
    assert built.frame.iloc[0]["Main Image"] == "http://x/1.jpg"
    assert built.frame.iloc[0]["Other Image 1"] == "http://x/2.jpg"


def test_reads_csv_by_column_letter():
    csv = (
        "SKU,Brand,Title,Sequence,Image Link\n"
        "SKU-1,b,t,2,http://x/2.jpg\n"
        "SKU-1,b,t,1,http://x/1.jpg\n"
    ).encode()
    parsed, built = core.run(csv, get_stack("vba_legacy"), filename="d.csv")
    assert built.frame.iloc[0]["Main Image"] == "http://x/1.jpg"


def test_export_produces_a_readable_workbook():
    from mmf_image_links import export

    built = core.build_output(parse([("A", 1, "a1"), ("A", 2, "a2")]).rows, get_stack("vba_legacy"))
    blob = export.to_workbook(built.frame, warnings=["hello"])
    sheets = pd.read_excel(io.BytesIO(blob), sheet_name=None)
    assert "output_image_links" in sheets
    assert "warnings" in sheets
    assert sheets["output_image_links"].iloc[0]["Main Image"] == "a1"


# ------------------------------------------------- regression: review findings

def test_nan_and_inf_text_are_not_numeric_sequences():
    """float() parses these; VBA's IsNumeric does not, and a NaN poisons the sort."""
    parsed = parse([
        ("A", "nan", "u1"), ("A", "inf", "u2"), ("A", "-Infinity", "u3"), ("A", "1_0", "u4"),
        ("A", 1, "keep"),
    ])
    assert [r.url for r in parsed.rows] == ["keep"]
    assert len(parsed.skipped) == 4
    assert all(s.reason == "sequence is not numeric" for s in parsed.skipped)


def test_a_real_nan_float_is_not_numeric():
    parsed = parse([("A", float("nan"), "u1"), ("A", 1, "keep")])
    assert [r.url for r in parsed.rows] == ["keep"]


def test_numeric_skus_sort_the_way_excel_sorts_them():
    parsed = parse([("ABC", 1, "c"), ("10", 1, "b"), ("9", 1, "a")])
    grouped = core.group_by_sku(parsed.rows)
    assert list(grouped) == ["9", "10", "ABC"]  # numbers first, numerically, then text


def test_leading_zero_skus_survive_unchanged():
    """The macro let Excel coerce '007' to 7; keeping it as text is the fix."""
    built = core.build_output(parse([("007", 1, "a")]).rows, get_stack("vba_legacy"))
    assert built.frame.iloc[0]["Master Id/ Sku"] == "007"


def test_control_characters_do_not_break_the_excel_export():
    from mmf_image_links import export

    parsed = parse([("SK\x0bU", 1, "http://x/a.jpg\x00")])
    built = core.build_output(parsed.rows, get_stack("vba_legacy"))
    blob = export.to_workbook(built.frame)  # openpyxl raises IllegalCharacterError unsanitized
    out = pd.read_excel(io.BytesIO(blob))
    assert out.iloc[0]["Master Id/ Sku"] == "SKU"
    assert out.iloc[0]["Main Image"] == "http://x/a.jpg"


def test_control_characters_are_stripped_from_audit_sheets_too():
    from mmf_image_links import export

    parsed = parse([("SK\x0bU", "hello\x0b", "")])
    blob = export.to_workbook(pd.DataFrame({"a": ["x"]}), skipped=parsed.skipped_frame())
    sheets = pd.read_excel(io.BytesIO(blob), sheet_name=None)
    assert sheets["skipped_rows"].iloc[0]["SKU"] == "SKU"


def test_reading_every_sheet_at_once_is_rejected_clearly(tmp_path):
    path = tmp_path / "s.xlsx"
    pd.DataFrame([["A", "", "", 1, "u"]]).to_excel(path, index=False, header=False)
    with pytest.raises(ValueError, match="sheet_name=None"):
        core.read_table(str(path), sheet_name=None)


def test_content_range_parsing():
    from mmf_image_links.validate import _full_length

    assert _full_length({"Content-Range": "bytes 0-99/5000", "Content-Length": "100"}) == 5000
    assert _full_length({"Content-Range": "bytes 0-99/*", "Content-Length": "100"}) is None
    assert _full_length({"Content-Length": "5000"}) == 5000
    assert _full_length({}) is None


# ----------------------------------------------------------------- templates

def test_every_stack_in_the_yaml_builds_without_error():
    parsed = parse([("A", 1, "a1"), ("A", 2, "a2"), ("B", 1, "b1")])
    for stack in load_stacks():
        built = core.build_output(parsed.rows, stack)
        assert not built.frame.empty, stack.key
        assert stack.sku_header in built.frame.columns, stack.key
