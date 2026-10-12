import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .schema import BBOX, LOCALES, RAW_COLUMNS, SCHEMA, STATE

_SPACES = re.compile(r"\s+")
_ZIP = re.compile(r"(\d{5})(?:-?\d{4})?")


class RowError(ValueError):
    pass


@dataclass
class Reject:
    record: int
    reason: str
    raw: str


@dataclass
class CleanResult:
    records: list[dict] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    rows_seen: int = 0
    rows_other_states: int = 0


def read_rows(lines: Iterable[str]) -> Iterable[list[str]]:
    # The file is pipe-delimited but a few names are quoted because they contain a pipe.
    return csv.reader(lines, delimiter="|", quotechar='"')


def squish(value: str) -> str | None:
    value = _SPACES.sub(" ", value).strip()
    return value or None


def _digits(value: str, width: int, label: str) -> str:
    v = value.strip()
    if not (v.isdigit() and len(v) == width):
        raise RowError(f"{label} {value!r} is not {width} digits")
    return v


def _area(value: str) -> str | None:
    # CBSA and CSA columns carry a literal N for schools outside any statistical area
    v = squish(value)
    return None if v == "N" else v


def _zip5(value: str) -> str | None:
    m = _ZIP.fullmatch(value.strip())
    return m.group(1) if m else None


def _small_int(value: str) -> int | None:
    v = value.strip()
    return int(v) if v.isdigit() else None


def _coordinate(value: str, axis: str) -> float:
    try:
        x = float(value)
    except ValueError:
        raise RowError(f"{axis} {value!r} is not a number") from None
    lo, hi = BBOX[axis]
    if not lo <= x <= hi:
        raise RowError(f"{axis} {x} is outside the Wisconsin box")
    return x


def clean_record(rec: dict[str, str]) -> dict:
    name = squish(rec["NAME"])
    if name is None:
        raise RowError("empty school name")
    county = squish(rec["NMCNTY"])
    if county and county.endswith(" County"):
        county = county[: -len(" County")]
    locale = _small_int(rec["LOCALE"])
    group, detail = LOCALES.get(locale, (None, None))
    year = squish(rec["SCHOOLYEAR"])
    if year is None:
        raise RowError("missing school year")
    return {
        "ncessch": _digits(rec["NCESSCH"], 12, "NCESSCH"),
        "leaid": _digits(rec["LEAID"], 7, "LEAID"),
        "school_name": name,
        "street": squish(rec["STREET"]),
        "city": squish(rec["CITY"]),
        "state": STATE,
        "zip": _zip5(rec["ZIP"]),
        "county_fips": _digits(rec["CNTY"], 5, "CNTY"),
        "county_name_nces": county,
        "locale_code": locale,
        "locale_group": group,
        "locale_detail": detail,
        "latitude": _coordinate(rec["LAT"], "lat"),
        "longitude": _coordinate(rec["LON"], "lon"),
        "cbsa_code": _area(rec["CBSA"]),
        "cbsa_name": _area(rec["NMCBSA"]),
        "cbsa_type": _small_int(rec["CBSATYPE"]),
        "csa_code": _area(rec["CSA"]),
        "csa_name": _area(rec["NMCSA"]),
        "congressional_district": squish(rec["CD"]),
        "state_leg_lower": squish(rec["SLDL"]),
        "state_leg_upper": squish(rec["SLDU"]),
        "school_year": year,
    }


def clean_rows(rows: Iterable[list[str]]) -> CleanResult:
    out = CleanResult()
    seen: set[str] = set()
    for n, fields in enumerate(rows, start=1):
        out.rows_seen += 1
        if len(fields) != len(RAW_COLUMNS):
            reason = f"expected {len(RAW_COLUMNS)} fields, got {len(fields)}"
            out.rejects.append(Reject(n, reason, "|".join(fields)))
            continue
        rec = dict(zip(RAW_COLUMNS, fields, strict=True))
        if rec["STATE"].strip().upper() != STATE:
            out.rows_other_states += 1
            continue
        try:
            row = clean_record(rec)
            if row["ncessch"] in seen:
                raise RowError(f"duplicate NCESSCH {row['ncessch']}")
        except RowError as e:
            out.rejects.append(Reject(n, str(e), "|".join(fields)))
            continue
        seen.add(row["ncessch"])
        out.records.append(row)
    return out


def to_table(records: list[dict]) -> pa.Table:
    ordered = sorted(records, key=lambda r: r["ncessch"])
    return pa.Table.from_pylist(ordered, schema=SCHEMA)


def write_parquet(records: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = to_table(records)
    pq.write_table(table, path, compression="snappy")
    return table.num_rows


def write_rejects(rejects: list[Reject], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["record", "reason", "raw"])
        for r in rejects:
            w.writerow([r.record, r.reason, r.raw])
