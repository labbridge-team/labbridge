"""
The "dictionary" that makes different labs comparable.

Every lab uses its own internal test codes and its own units. This file maps:
  lab's local code  ->  one standard test (LOINC)
  lab's unit        ->  one canonical unit (with the conversion factor)

Extending LabBridge to a new lab = adding one entry to LABS.
Conversion factors are standard; reference values and retest intervals are
ILLUSTRATIVE for a demo, not clinical guidance.
"""

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"  # Austrian social insurance number (HL7 Austria)


def _same(v):
    return v


# key -> LOINC code + display, readable name, canonical unit (+UCUM code), decimals,
#        unit conversions to canonical, illustrative minimum retest interval in days
TESTS = {
    "glucose": {
        "loinc": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma",
        "name": "Glucose (Blutzucker)", "unit": "mg/dL", "ucum": "mg/dL", "decimals": 0,
        "convert": {"mg/dl": _same, "mmol/l": lambda v: v * 18.016}, "retest_days": 7,
    },
    "hba1c": {
        "loinc": "4548-4", "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
        "name": "HbA1c", "unit": "%", "ucum": "%", "decimals": 1,
        "convert": {"%": _same, "mmol/mol": lambda v: v / 10.929 + 2.15}, "retest_days": 90,
    },
    "creatinine": {
        "loinc": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma",
        "name": "Creatinine (Kreatinin)", "unit": "mg/dL", "ucum": "mg/dL", "decimals": 2,
        "convert": {"mg/dl": _same, "umol/l": lambda v: v / 88.42}, "retest_days": 7,
    },
    "potassium": {
        "loinc": "2823-3", "display": "Potassium [Moles/volume] in Serum or Plasma",
        "name": "Potassium (Kalium)", "unit": "mmol/L", "ucum": "mmol/L", "decimals": 1,
        "convert": {"mmol/l": _same}, "retest_days": 3,
    },
    "sodium": {
        "loinc": "2951-2", "display": "Sodium [Moles/volume] in Serum or Plasma",
        "name": "Sodium (Natrium)", "unit": "mmol/L", "ucum": "mmol/L", "decimals": 0,
        "convert": {"mmol/l": _same}, "retest_days": 3,
    },
    "cholesterol": {
        "loinc": "2093-3", "display": "Cholesterol [Mass/volume] in Serum or Plasma",
        "name": "Total cholesterol", "unit": "mg/dL", "ucum": "mg/dL", "decimals": 0,
        "convert": {"mg/dl": _same, "mmol/l": lambda v: v * 38.67}, "retest_days": 90,
    },
    "hemoglobin": {
        "loinc": "718-7", "display": "Hemoglobin [Mass/volume] in Blood",
        "name": "Haemoglobin", "unit": "g/dL", "ucum": "g/dL", "decimals": 1,
        "convert": {"g/dl": _same, "g/l": lambda v: v / 10}, "retest_days": 7,
    },
    "crp": {
        "loinc": "1988-5", "display": "C reactive protein [Mass/volume] in Serum or Plasma",
        "name": "CRP", "unit": "mg/L", "ucum": "mg/L", "decimals": 1,
        "convert": {"mg/l": _same, "mg/dl": lambda v: v * 10}, "retest_days": 2,
    },
    "tsh": {
        "loinc": "3016-3", "display": "Thyrotropin [Units/volume] in Serum or Plasma",
        "name": "TSH", "unit": "mIU/L", "ucum": "m[IU]/L", "decimals": 2,
        "convert": {"miu/l": _same, "uiu/ml": _same}, "retest_days": 42,
    },
    "leukocytes": {
        "loinc": "6690-2", "display": "Leukocytes [#/volume] in Blood by Automated count",
        "name": "Leukocytes", "unit": "G/L", "ucum": "10*9/L", "decimals": 1,
        "convert": {"g/l(cells)": _same, "10^9/l": _same, "giga/l": _same}, "retest_days": 7,
    },
}
LOINC_TO_KEY = {t["loinc"]: k for k, t in TESTS.items()}

# Two FICTIONAL Viennese labs: different codes, different units for the same tests.
LABS = {
    "LABOR_ALPHA": {
        "name": "Labor Alpha Wien (fictional)",
        "codes": {"GLU": "glucose", "HBA1C": "hba1c", "KREA": "creatinine", "K": "potassium",
                  "NA": "sodium", "CHOL": "cholesterol", "HB": "hemoglobin", "CRP": "crp",
                  "TSH": "tsh", "LEUK": "leukocytes"},
    },
    "LABOR_BETA": {
        "name": "Labor Beta Wien (fictional)",
        "codes": {"GLUC-S": "glucose", "A1C-IFCC": "hba1c", "CREA-E": "creatinine",
                  "KALIUM": "potassium", "NATRIUM": "sodium", "TCHOL": "cholesterol",
                  "HGB": "hemoglobin", "CRP-Q": "crp", "TSH3": "tsh", "WBC": "leukocytes"},
    },
}


def norm_unit(unit: str) -> str:
    return (unit or "").strip().lower().replace("µ", "u").replace("μ", "u")


# Other (fictional) systems that send data: they send allergies, not lab results.
FACILITIES = {
    "KH_DEMO": {"name": "Krankenhaus Demo Wien (fictional)", "kind": "Hospital"},
    "ORDINATION_HUBER": {"name": "Ordination Dr. Huber (fictional)", "kind": "GP practice"},
}


def lab_name(facility: str) -> str:
    return LABS.get(facility, FACILITIES.get(facility, {})).get("name", facility)


def facility_kind(facility: str) -> str:
    return FACILITIES.get(facility, {}).get("kind", "Laboratory")


def map_code(facility: str, code: str, coding_system: str):
    """Returns the test key, or None if this lab's code is unknown."""
    if coding_system.upper() in ("LN", "LOINC") and code in LOINC_TO_KEY:
        return LOINC_TO_KEY[code]  # lab already sends LOINC: nothing to map
    return LABS.get(facility, {}).get("codes", {}).get(code)


def to_canonical(key: str, value: float, unit: str):
    """Converts a value to the test's canonical unit. Returns None if the unit is unknown."""
    t = TESTS[key]
    u = norm_unit(unit)
    if key == "leukocytes" and u == "g/l":
        u = "g/l(cells)"  # 'G/L' (giga per litre) for cell counts, not grams per litre
    fn = t["convert"].get(u)
    if fn is None:
        return None
    return round(fn(value), t["decimals"])


def svnr_is_valid(svnr: str) -> bool:
    """Austrian SVNR: 10 digits, 4th digit is a check digit over the other nine."""
    if not (svnr.isdigit() and len(svnr) == 10):
        return False
    d = [int(c) for c in svnr]
    weights = [3, 7, 9, 0, 5, 8, 4, 2, 1, 6]
    check = sum(w * x for w, x in zip(weights, d)) % 11
    return check != 10 and check == d[3]


def make_svnr(serial: int, birth_ddmmyy: str) -> str:
    """Builds a checksum-valid (FAKE) SVNR, for demo patients only."""
    for s in range(serial, serial + 50):
        base = f"{s:03d}"
        d = [int(c) for c in base + "0" + birth_ddmmyy]
        check = sum(w * x for w, x in zip([3, 7, 9, 0, 5, 8, 4, 2, 1, 6], d)) % 11
        if check != 10:
            return f"{base}{check}{birth_ddmmyy}"
    raise ValueError("no valid serial found")
