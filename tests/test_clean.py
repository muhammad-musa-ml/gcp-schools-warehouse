import pyarrow.parquet as pq
import pytest

from ingest import clean
from ingest.schema import RAW_COLUMNS, SCHEMA


def test_squish_collapses_whitespace_and_empties_to_none():
    assert clean.squish("  Albertville,   AL ") == "Albertville, AL"
    assert clean.squish("   ") is None


def test_clean_record_renames_and_types(make_fields):
    rec = dict(zip(RAW_COLUMNS, make_fields(), strict=True))
    row = clean.clean_record(rec)
    assert row["school_name"] == "Lake Country School"
    assert row["county_fips"] == "55133"
    assert row["county_name_nces"] == "Waukesha"
    assert row["locale_code"] == 21
    assert (row["locale_group"], row["locale_detail"]) == ("Suburb", "Large")
    assert row["latitude"] == pytest.approx(43.099701)
    assert row["cbsa_type"] == 1
    assert "OPSTFIPS" not in row and "stfip" not in row


def test_not_applicable_markers_become_null(make_fields):
    rec = dict(
        zip(
            RAW_COLUMNS,
            make_fields(CBSA="N", NMCBSA="N", CBSATYPE="0", CSA="N", NMCSA="N"),
            strict=True,
        )
    )
    row = clean.clean_record(rec)
    assert row["cbsa_code"] is None and row["cbsa_name"] is None
    assert row["csa_code"] is None and row["csa_name"] is None
    assert row["cbsa_type"] == 0


def test_zip_is_trimmed_to_five_digits_or_null(make_fields):
    def zip_of(z):
        return clean.clean_record(dict(zip(RAW_COLUMNS, make_fields(ZIP=z), strict=True)))["zip"]

    assert zip_of("53703-1234") == "53703"
    assert zip_of("537031234") == "53703"
    assert zip_of("5370") is None
    assert zip_of("") is None


def test_unknown_locale_keeps_code_without_labels(make_fields):
    rec = dict(zip(RAW_COLUMNS, make_fields(LOCALE="99"), strict=True))
    row = clean.clean_record(rec)
    assert row["locale_code"] == 99
    assert row["locale_group"] is None


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"NAME": "   "}, "empty school name"),
        ({"NCESSCH": "55000130057"}, "NCESSCH"),
        ({"LEAID": "55"}, "LEAID"),
        ({"CNTY": "5513"}, "CNTY"),
        ({"LAT": "abc"}, "not a number"),
        ({"LAT": ""}, "not a number"),
        ({"LAT": "-43.1"}, "outside the Wisconsin box"),
        ({"LON": "88.38"}, "outside the Wisconsin box"),
        ({"LAT": "nan"}, "outside the Wisconsin box"),
        ({"SCHOOLYEAR": " "}, "school year"),
    ],
)
def test_bad_values_are_rejected(make_fields, overrides, fragment):
    rec = dict(zip(RAW_COLUMNS, make_fields(**overrides), strict=True))
    with pytest.raises(clean.RowError, match=fragment):
        clean.clean_record(rec)


def test_clean_rows_filters_state_and_collects_rejects(make_fields):
    rows = [
        make_fields(),
        make_fields(NCESSCH="010000500870", LEAID="0100005", STATE="AL", CNTY="01095"),
        make_fields(NCESSCH="550001602378", NAME="Blair-Taylor Middle/High"),
        make_fields(NCESSCH="550001602379", LAT="0"),
        make_fields()[:-3],
        make_fields(),  # same id as the first row
    ]
    out = clean.clean_rows(rows)
    assert out.rows_seen == 6
    assert out.rows_other_states == 1
    assert [r["ncessch"] for r in out.records] == ["550001300578", "550001602378"]
    reasons = [r.reason for r in out.rejects]
    assert any("outside the Wisconsin box" in r for r in reasons)
    assert any("expected 23 fields, got 20" in r for r in reasons)
    assert any("duplicate NCESSCH 550001300578" in r for r in reasons)
    assert len(out.rejects) == 3


def test_quoted_name_with_pipe_survives_the_reader(make_line):
    lines = [
        make_line(NAME='"Impact | Salish Sea Elementary"', NCESSCH="530034803749", STATE="WA"),
        make_line(NAME='"Bethel | Park Elementary"', NCESSCH="550001602380"),
    ]
    out = clean.clean_rows(clean.read_rows(lines))
    assert out.rejects == []
    assert out.rows_other_states == 1
    assert out.records[0]["school_name"] == "Bethel | Park Elementary"


def test_parquet_output_matches_schema_and_is_sorted(tmp_path, make_fields):
    out = clean.clean_rows(
        [make_fields(NCESSCH="550001602378"), make_fields(), make_fields(NCESSCH="550000100001")]
    )
    path = tmp_path / "sub" / "schools.parquet"
    n = clean.write_parquet(out.records, path)
    table = pq.read_table(path)
    assert n == table.num_rows == 3
    assert table.schema.equals(SCHEMA)
    ids = table.column("ncessch").to_pylist()
    assert ids == sorted(ids)


def test_write_rejects_round_trips_embedded_pipes(tmp_path):
    path = tmp_path / "rejects.csv"
    clean.write_rejects([clean.Reject(7, "bad", "a|b|c")], path)
    assert path.read_text(encoding="utf-8").splitlines() == ["record,reason,raw", "7,bad,a|b|c"]
