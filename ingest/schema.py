import pyarrow as pa

STATE = "WI"

# The EDGE text extract has no header row; this is the order from the xlsx that ships in the zip.
_HEADER = (
    "NCESSCH LEAID NAME OPSTFIPS STREET CITY STATE ZIP STFIP CNTY NMCNTY LOCALE LAT LON "
    "CBSA NMCBSA CBSATYPE CSA NMCSA CD SLDL SLDU SCHOOLYEAR"
)
RAW_COLUMNS = tuple(_HEADER.split())

# NCES urban-centric locale codes
LOCALES = {
    11: ("City", "Large"),
    12: ("City", "Midsize"),
    13: ("City", "Small"),
    21: ("Suburb", "Large"),
    22: ("Suburb", "Midsize"),
    23: ("Suburb", "Small"),
    31: ("Town", "Fringe"),
    32: ("Town", "Distant"),
    33: ("Town", "Remote"),
    41: ("Rural", "Fringe"),
    42: ("Rural", "Distant"),
    43: ("Rural", "Remote"),
}

# Rough box around Wisconsin, a little loose on purpose. It only catches swapped or garbage
# coordinates; the county join in the warehouse is what really checks the points.
BBOX = {"lat": (42.3, 47.2), "lon": (-93.0, -86.5)}

SCHEMA = pa.schema(
    [
        pa.field("ncessch", pa.string(), nullable=False),
        pa.field("leaid", pa.string(), nullable=False),
        pa.field("school_name", pa.string(), nullable=False),
        pa.field("street", pa.string()),
        pa.field("city", pa.string()),
        pa.field("state", pa.string(), nullable=False),
        pa.field("zip", pa.string()),
        pa.field("county_fips", pa.string(), nullable=False),
        pa.field("county_name_nces", pa.string()),
        pa.field("locale_code", pa.int8()),
        pa.field("locale_group", pa.string()),
        pa.field("locale_detail", pa.string()),
        pa.field("latitude", pa.float64(), nullable=False),
        pa.field("longitude", pa.float64(), nullable=False),
        pa.field("cbsa_code", pa.string()),
        pa.field("cbsa_name", pa.string()),
        pa.field("cbsa_type", pa.int8()),
        pa.field("csa_code", pa.string()),
        pa.field("csa_name", pa.string()),
        pa.field("congressional_district", pa.string()),
        pa.field("state_leg_lower", pa.string()),
        pa.field("state_leg_upper", pa.string()),
        pa.field("school_year", pa.string(), nullable=False),
    ]
)
