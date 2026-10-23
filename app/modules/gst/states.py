"""GST state codes and helpers.

Codes follow the GST state code list used in GSTINs. 96 and 97 are the
special codes for other countries and other territory. Verify against the
official list before release.
"""

from app.core.exceptions import ValidationError

STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "96": "Other Countries",
    "97": "Other Territory",
}

OTHER_COUNTRY = "96"
OTHER_TERRITORY = "97"

# Union territories without a legislature: intra-state supply attracts
# CGST + UTGST instead of CGST + SGST.
UTGST_TERRITORIES = frozenset({"04", "26", "31", "35", "38", "97"})


def normalize_state_code(code, field: str = "state_code") -> str:
    """Return a valid two-digit state code string ('7' becomes '07')."""
    if not isinstance(code, str):
        raise ValidationError(f"{field} must be a string, not {type(code).__name__}")
    cleaned = code.strip()
    if len(cleaned) == 1 and cleaned.isdigit():
        cleaned = cleaned.zfill(2)
    if cleaned not in STATE_CODES:
        raise ValidationError(f"{field} is not a valid GST state code: {code!r}")
    return cleaned


def state_name(code) -> str:
    return STATE_CODES[normalize_state_code(code)]


def is_utgst_territory(code) -> bool:
    return normalize_state_code(code) in UTGST_TERRITORIES
