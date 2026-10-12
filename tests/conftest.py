import pytest

from ingest.schema import RAW_COLUMNS

BASE = {
    "NCESSCH": "550001300578",
    "LEAID": "5500013",
    "NAME": "Lake Country School",
    "OPSTFIPS": "55",
    "STREET": "1800 Vettelson Rd",
    "CITY": "Hartland",
    "STATE": "WI",
    "ZIP": "53029",
    "STFIP": "55",
    "CNTY": "55133",
    "NMCNTY": "Waukesha County",
    "LOCALE": "21",
    "LAT": "43.099701",
    "LON": "-88.385005",
    "CBSA": "33340",
    "NMCBSA": "Milwaukee-Waukesha, WI",
    "CBSATYPE": "1",
    "CSA": "376",
    "NMCSA": "Milwaukee-Racine-Waukesha, WI",
    "CD": "5505",
    "SLDL": "55097",
    "SLDU": "55033",
    "SCHOOLYEAR": "2024-2025",
}


@pytest.fixture
def make_fields():
    def make(**overrides: str) -> list[str]:
        unknown = set(overrides) - set(RAW_COLUMNS)
        assert not unknown, unknown
        return [{**BASE, **overrides}[c] for c in RAW_COLUMNS]

    return make


@pytest.fixture
def make_line(make_fields):
    def make(**overrides: str) -> str:
        return "|".join(make_fields(**overrides)) + "\r\n"

    return make
