"""
Allergies: maps each system's own allergy codes to one standard substance, like lab_catalog does
for lab tests.

Standard codes used:
- Medicines: WHO ATC classification (http://www.whocc.no/atc)
- Other substances and "no known allergy": SNOMED CT (http://snomed.info/sct)
"""
ATC = "http://www.whocc.no/atc"
SNOMED = "http://snomed.info/sct"
CLINICAL = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
VERIFICATION = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"

NKA = {"system": SNOMED, "code": "716186003", "display": "No known allergy (situation)"}

SUBSTANCES = {
    "penicillin": {"name": "Penicillin", "category": "medication",
                   "coding": {"system": ATC, "code": "J01C", "display": "Beta-lactam antibacterials, penicillins"}},
    "amoxicillin": {"name": "Amoxicillin", "category": "medication",
                    "coding": {"system": ATC, "code": "J01CA04", "display": "amoxicillin"}},
    "ibuprofen": {"name": "Ibuprofen", "category": "medication",
                  "coding": {"system": ATC, "code": "M01AE01", "display": "ibuprofen"}},
    "aspirin": {"name": "Acetylsalicylic acid (aspirin)", "category": "medication",
                "coding": {"system": ATC, "code": "N02BA01", "display": "acetylsalicylic acid"}},
    "metformin": {"name": "Metformin", "category": "medication",
                  "coding": {"system": ATC, "code": "A10BA02", "display": "metformin"}},
    "contrast_iodine": {"name": "Iodinated contrast media", "category": "medication",
                        "coding": {"system": ATC, "code": "V08A", "display": "X-ray contrast media, iodinated"}},
    "latex": {"name": "Latex", "category": "environment",
              "coding": {"system": SNOMED, "code": "111088007", "display": "Latex (substance)"}},
    "peanut": {"name": "Peanut", "category": "food",
               "coding": {"system": SNOMED, "code": "762952008", "display": "Peanut (substance)"}},
    "bee_venom": {"name": "Bee venom", "category": "environment",
                  "coding": {"system": SNOMED, "code": "288328004", "display": "Bee venom (substance)"}},
}

# Each sending system's own codes (HL7 v2 AL1-3) -> substance key. "NKA" = no known allergies.
LOCAL_CODES = {
    "KH_DEMO": {"PEN": "penicillin", "KM-JOD": "contrast_iodine", "NKA": "nka"},
    "ORDINATION_HUBER": {"PENI": "penicillin", "IBU": "ibuprofen", "LATEX": "latex", "NKA": "nka"},
}

# HL7 v2 table 0127 (allergen type) -> FHIR category / type
AL1_CATEGORY = {"DA": "medication", "FA": "food", "EA": "environment", "AA": "environment",
                "PA": "environment", "LA": "environment"}
# HL7 v2 table 0128 (severity) -> (FHIR criticality, FHIR reaction severity)
AL1_SEVERITY = {"SV": ("high", "severe"), "MO": ("low", "moderate"), "MI": ("low", "mild"),
                "U": ("unable-to-assess", None), "": ("unable-to-assess", None)}

CRITICALITY_TEXT = {"high": "High risk", "low": "Low risk", "unable-to-assess": "Risk not assessed"}
CATEGORY_TEXT = {"medication": "Medicine", "food": "Food", "environment": "Environment", "biologic": "Biologic"}


def map_allergen(facility: str, code: str, text: str):
    """Returns a substance key ('nka' for no known allergies), or None if unknown."""
    key = LOCAL_CODES.get(facility, {}).get(code)
    if key:
        return key
    t = (text or "").strip().lower()
    for k, s in SUBSTANCES.items():  # fall back to the name, e.g. "Penicillin"
        if t and (t == s["name"].lower() or t.rstrip("s") == s["name"].lower().rstrip("s")):
            return k
    return None


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.strip().lower()).strip("-") or "unknown"
