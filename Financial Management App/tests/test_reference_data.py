"""Unit tests for the source-format parsers.

These decode three vendor formats that nothing else validates, so a silent
change here would quietly corrupt a dimension.
"""

from __future__ import annotations

import pytest

from fin_services.reference_data import (
    account_status,
    normalize_product_code,
    parse_bool,
    parse_policy,
    parse_product_code,
    parse_source_date,
    split_list,
)


# ------------------------------------------------------------- product codes


@pytest.mark.parametrize("code,expected", [
    ("Admin-EH",         {"channel": "direct", "fee_kind": "admin",      "benefit_code": "EH", "hst_rate": None}),
    ("Admin-EH(13)",     {"channel": "direct", "fee_kind": "admin",      "benefit_code": "EH", "hst_rate": 13}),
    ("Admin-EH(14)",     {"channel": "direct", "fee_kind": "admin",      "benefit_code": "EH", "hst_rate": 14}),
    ("Admin-EH(15)",     {"channel": "direct", "fee_kind": "admin",      "benefit_code": "EH", "hst_rate": 15}),
    ("VEN-Admin-EH(13)", {"channel": "vendor", "fee_kind": "admin",      "benefit_code": "EH", "hst_rate": 13}),
    ("ASO Admin-EH",     {"channel": "aso",    "fee_kind": "admin",      "benefit_code": "EH", "hst_rate": None}),
    ("Comm-EH",          {"channel": "direct", "fee_kind": "commission", "benefit_code": "EH", "hst_rate": None}),
])
def test_product_code_decomposition(code, expected):
    got = parse_product_code(code)
    for key, value in expected.items():
        assert got[key] == value, f"{code}: {key}"


def test_hst_suffix_is_a_tax_rate_not_a_pay_frequency():
    """The whole EH family is one benefit sold under four tax jurisdictions."""
    family = ["Admin-EH", "Admin-EH(13)", "Admin-EH(14)", "Admin-EH(15)"]
    parsed = [parse_product_code(c) for c in family]
    assert {p["benefit_code"] for p in parsed} == {"EH"}
    assert [p["hst_rate"] for p in parsed] == [None, 13, 14, 15]


def test_channel_and_fee_kind_stay_out_of_the_benefit_code():
    """Comm-EH is a commission and ASO is not direct — these must not merge."""
    keys = {
        (p["benefit_code"], p["channel"], p["fee_kind"])
        for p in map(parse_product_code, ["Admin-EH", "Comm-EH", "ASO Admin-EH", "VEN-Admin-EH"])
    }
    assert len(keys) == 4


def test_space_before_hst_suffix_is_tolerated():
    """'VEN-Admin-Sub Fee (15)' occurs in the live data."""
    p = parse_product_code("VEN-Admin-Sub Fee (15)")
    assert p["hst_rate"] == 15
    assert p["benefit_code"] == "SUB FEE"
    assert p["channel"] == "vendor"


@pytest.mark.parametrize("a,b", [
    ("COMM-EV", "Comm-EV"),
    ("VEN-admin-SA", "VEN-Admin-SA"),
    ("Ven-Admin-HS", "VEN-Admin-HS"),
])
def test_casing_drift_normalises_to_one_code(a, b):
    assert normalize_product_code(a) == normalize_product_code(b)


@pytest.mark.parametrize("code,fee_kind", [
    ("GST-Rounding", "tax"),
    ("HST-Rounding", "tax"),
    ("nsf-fee", "fee"),
    ("wire-fee", "fee"),
    ("Admin-Rounding", "adjustment"),
    ("Admin Error - Write off", "adjustment"),
    ("Admin-PAD Processing Fee", "fee"),
    ("Email Feed", "other"),
    ("Statement of Work", "other"),
])
def test_standalone_codes_are_classified(code, fee_kind):
    assert parse_product_code(code)["fee_kind"] == fee_kind


# ------------------------------------------------------------------ policies


def test_policy_splits_carrier_from_number():
    p = parse_policy("Co-operators - 1013-Life")
    assert p["carrier_name"] == "Co-operators"
    assert p["policy_no"] == "1013-Life"
    assert p["benefit_line"] == "Life"


def test_policy_benefit_line_comes_from_an_allowlist_only():
    """Most suffixes are numeric — 0008 is not a benefit."""
    assert parse_policy("Chubb - AB10562701")["benefit_line"] is None
    assert parse_policy("Carrier - 1234-0008")["benefit_line"] is None
    assert parse_policy("GreenShield - 54201-Dental")["benefit_line"] == "Dental"


def test_policy_flags_tbd_as_a_placeholder():
    p = parse_policy("Desjardins - TBD")
    assert p["is_placeholder"] == 1
    assert parse_policy("Desjardins - 667526")["is_placeholder"] == 0


def test_policy_without_delimiter_keeps_the_whole_value():
    p = parse_policy("99147")
    assert p["carrier_name"] is None and p["policy_no"] == "99147"


def test_policy_blank_returns_none():
    assert parse_policy("   ") is None


# --------------------------------------------------------------- lists, dates


def test_split_list_handles_pipe_joined_and_empties():
    assert split_list("A | B | C") == ["A", "B", "C"]
    assert split_list("") == []
    assert split_list(None) == []
    assert split_list("nan") == []
    assert split_list("Solo") == ["Solo"]


@pytest.mark.parametrize("raw,iso", [
    ("May 1, 2021", "2021-05-01"),
    ("Aug 30, 2021", "2021-08-30"),
    ("Apr 29, 2026", "2026-04-29"),
    ("2026-01-15", "2026-01-15"),
])
def test_source_dates_normalise_to_iso(raw, iso):
    assert parse_source_date(raw) == iso


def test_unparseable_date_returns_none_rather_than_raising():
    """A bad date is counted into the import's parity report, not a load failure."""
    assert parse_source_date("sometime last spring") is None
    assert parse_source_date("") is None
    assert parse_source_date(None) is None


# ----------------------------------------------------------------- flags


def test_parse_bool_reads_the_literal_strings_the_csv_writes():
    assert parse_bool("True") == 1
    assert parse_bool("true") == 1
    assert parse_bool("False") == 0
    assert parse_bool("") == 0


def test_account_status_collapses_active_and_updating():
    assert account_status("True", "False") == "active"
    assert account_status("False", "False") == "terminated"
    assert account_status("True", "True") == "updating"
    assert account_status("False", "True") == "updating"
