"""
Generates realistic FAKE HL7 v2 lab messages from two fictional Viennese labs.

Story for the demo:
  Anna Demo (diabetic) had blood work at her GP via Labor Alpha (mg/dL, %),
  then at a hospital via Labor Beta (SI units: mmol/L, umol/L, mmol/mol).
  Looked at as reported, her values seem to jump around. After LabBridge
  normalises them, a clear trend appears: kidney function and HbA1c are worsening.
  Her last tests were 2 weeks ago, so re-ordering HbA1c or cholesterol now is a duplicate.
  Those results were abnormal and are still waiting for her GP's review (an overdue follow-up).
  late_result_file(): a critical potassium result arrives after she left hospital, and is
  routed to her GP even though the hospital lab doesn't know who her GP is.

Dates are relative to today, so the demo always looks current.
Run `python demo_data.py` to (re)write the files in sample_data/.
"""
import os
from datetime import datetime, timedelta

from hl7v2 import VIENNA, build_adt, build_oru
from lab_catalog import make_svnr

# Doctors (HL7 "XCN" format: ID^Family^Given^Middle^Suffix^Prefix). All fictional.
DR_HUBER = "GP001^Huber^Maria^^^Dr."      # Anna's GP (Allgemeinmedizin)
DR_NOVAK = "GP002^Novak^Peter^^^Dr."      # Max's GP
DR_BERGER = "KH101^Berger^Stefan^^^Dr."   # hospital doctor

ANNA = {"svnr": make_svnr(123, "120458"), "family": "Demo", "given": "Anna", "birth": "19580412", "sex": "F",
        "gp": DR_HUBER}
MAX = {"svnr": make_svnr(456, "030971"), "family": "Muster", "given": "Max", "birth": "19710903", "sex": "M",
       "gp": DR_NOVAK}

# code, text, unit, range, then one value per visit
ALPHA_ANNA = [
    ("GLU", "Glucose", "mg/dL", "70-99", [128, 135, 142]),
    ("HBA1C", "HbA1c", "%", "4.0-6.0", [7.2, 7.5, 7.8]),
    ("KREA", "Kreatinin", "mg/dL", "0.50-1.00", [1.00, 1.10, 1.20]),
    ("K", "Kalium", "mmol/L", "3.5-5.1", [4.3, 4.5, 4.8]),
    ("NA", "Natrium", "mmol/L", "136-145", [140, 139, 138]),
    ("CHOL", "Cholesterin gesamt", "mg/dL", "<200", [232, 224, 218]),
    ("HB", "Haemoglobin", "g/dL", "12.0-16.0", [13.1, 12.8, 12.6]),
]
BETA_ANNA = [
    ("GLUC-S", "Glukose Serum", "mmol/L", "3.9-5.5", [8.1, 8.4]),
    ("A1C-IFCC", "HbA1c IFCC", "mmol/mol", "20-42", [64, 66]),
    ("CREA-E", "Kreatinin enzymatisch", "umol/L", "45-84", [115, 124]),
    ("KALIUM", "Kalium", "mmol/L", "3.5-5.1", [5.0, 5.3]),
    ("NATRIUM", "Natrium", "mmol/L", "136-145", [137, 137]),
    ("TCHOL", "Gesamtcholesterin", "mmol/L", "<5.2", [5.5, 5.4]),
    ("HGB", "Haemoglobin", "g/L", "120-160", [123, 119]),
    ("CRP-Q", "CRP quantitativ", "mg/dL", "<0.5", [0.4, 0.3]),
]
ALPHA_MAX = [
    ("TSH", "TSH basal", "mIU/L", "0.27-4.20", [2.1]),
    ("LEUK", "Leukozyten", "G/L", "4.0-10.0", [6.4]),
    ("CRP", "CRP", "mg/L", "<5", [3.0]),
    ("HB", "Haemoglobin", "g/dL", "13.5-17.5", [15.2]),
]
BETA_MAX = [
    ("TSH3", "TSH 3. Generation", "mIU/L", "0.27-4.20", [1.9]),
    ("WBC", "Leukozyten", "G/L", "4.0-10.0", [6.8]),
    ("CRP-Q", "CRP quantitativ", "mg/dL", "<0.5", [0.2]),
]


def _flag(value, rng):
    if "-" in rng:
        lo, hi = (float(x) for x in rng.split("-"))
        return "L" if value < lo else "H" if value > hi else "N"
    if rng.startswith("<"):
        return "H" if value >= float(rng[1:]) else "N"
    return ""


def _visits(lab, facility, prefix, patient, panel, days_ago, today, extra_last=None, orderer=None, gp_known=True):
    """gp_known=False: the lab doesn't know the patient's GP (typical for hospital labs), so no PD1 segment."""
    sender = patient if gp_known else {k: v for k, v in patient.items() if k != "gp"}
    orderer = orderer or patient["gp"]
    msgs = []
    for i, d in enumerate(days_ago):
        sample = (today - timedelta(days=d)).replace(hour=7, minute=30)
        results = [{"code": c, "text": t, "value": vals[i], "unit": u, "range": r, "flag": _flag(vals[i], r)}
                   for c, t, u, r, vals in panel]
        if extra_last and i == len(days_ago) - 1:
            results += extra_last
        filler = f"{prefix}{sample:%y%m%d}{patient['svnr'][:3]}"
        orders = [{"filler_id": filler, "code": "PANEL", "text": "Laborbefund", "sample_time": sample,
                   "orderer": orderer, "results": results}]
        msgs.append(build_oru(facility, f"{prefix}-MSG-{filler}", sample.replace(hour=14), sender, orders))
    return msgs


def demo_files(today=None) -> dict:
    today = today or datetime.now(VIENNA)
    vitd = [{"code": "VITD", "text": "25-OH-Vitamin D", "value": 18, "unit": "ng/mL", "range": "30-100", "flag": "L"}]
    alpha = (_visits("alpha", "LABOR_ALPHA", "A", ANNA, ALPHA_ANNA, [340, 250, 160], today)
             + _visits("alpha", "LABOR_ALPHA", "A", MAX, ALPHA_MAX, [30], today))
    beta = (_visits("beta", "LABOR_BETA", "B", ANNA, BETA_ANNA, [75, 14], today, extra_last=vitd,
                    orderer=DR_BERGER, gp_known=False)
            + _visits("beta", "LABOR_BETA", "B", MAX, BETA_MAX, [3], today, orderer=DR_BERGER, gp_known=False))
    return {"labor_alpha.hl7": "".join(alpha), "labor_beta.hl7": "".join(beta), **allergy_files(today)}


def allergy_files(today=None) -> dict:
    """Allergies arrive from two other systems, each with its own codes:
    - the hospital (patient update when Anna was admitted): penicillin, iodinated contrast media
    - Dr. Huber's practice software: penicillin again (stored only once), ibuprofen intolerance
    Max has no allergy information anywhere, so the app shows "Allergies not recorded"."""
    today = today or datetime.now(VIENNA)
    hospital = {k: v for k, v in ANNA.items() if k != "gp"}  # the hospital doesn't know her GP
    adt_kh = build_adt("KH_DEMO", "KH-ADT-0001", (today - timedelta(days=76)).replace(hour=9, minute=12), hospital, [
        {"type": "DA", "code": "PEN", "text": "Penicillin", "severity": "SV",
         "reactions": ["Urtikaria", "Atemnot"], "since": "20190312"},
        {"type": "DA", "code": "KM-JOD", "text": "Jodhaltiges Kontrastmittel", "severity": "MO",
         "reactions": ["Hautausschlag"], "since": "20230605"},
    ])
    adt_gp = build_adt("ORDINATION_HUBER", "OH-ADT-0001", (today - timedelta(days=160)).replace(hour=11, minute=40),
                       ANNA, [
        {"type": "DA", "code": "PENI", "text": "Penicilline", "severity": "SV", "reactions": ["Urtikaria"]},
        {"type": "MC", "code": "IBU", "text": "Ibuprofen", "severity": "MI", "reactions": ["Magenbeschwerden"]},
    ])
    return {"hospital_patient_update.hl7": adt_kh, "gp_practice_allergies.hl7": adt_gp}


def late_result_file(now=None):
    """The 'result arrives after discharge' scenario: blood was taken in hospital last night,
    the result comes back this morning, after Anna has gone home. The hospital lab doesn't know
    her GP, but LabBridge does (from her patient record), so the result is routed there."""
    now = now or datetime.now(VIENNA)
    sample = now - timedelta(hours=20)
    filler = f"B{sample:%y%m%d%H}LATE"
    patient = {k: v for k, v in ANNA.items() if k != "gp"}
    orders = [{"filler_id": filler, "code": "NACH", "text": "Nachbefund nach Entlassung", "sample_time": sample,
               "orderer": DR_BERGER, "results": [
                   {"code": "KALIUM", "text": "Kalium", "value": 6.2, "unit": "mmol/L", "range": "3.5-5.1", "flag": "HH"},
                   {"code": "CREA-E", "text": "Kreatinin enzymatisch", "value": 141, "unit": "umol/L",
                    "range": "45-84", "flag": "H"},
                   {"code": "NATRIUM", "text": "Natrium", "value": 138, "unit": "mmol/L", "range": "136-145", "flag": "N"},
               ]}]
    return "labor_beta_late_result.hl7", build_oru("LABOR_BETA", f"B-MSG-{filler}", now - timedelta(hours=1),
                                                    patient, orders)


if __name__ == "__main__":
    os.makedirs("sample_data", exist_ok=True)
    for name, text in list(demo_files().items()) + [late_result_file()]:
        with open(os.path.join("sample_data", name), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print("wrote sample_data/" + name)
    print("Demo patients:", ANNA["given"], ANNA["svnr"], "|", MAX["given"], MAX["svnr"])
