"""
HL7 v2 lab message  ->  FHIR R4 transaction Bundle.

One ORU^R01 message becomes:
  Patient           identified by the e-card social insurance number (SVNR)
  Organization      the lab that produced the result
  DiagnosticReport  one per OBR (the lab report), keeps the original HL7 message attached
  Observation       one per OBX (each single value), LOINC-coded, in a canonical unit

  Practitioner      the patient's GP (HL7 PD1-4) and the ordering doctor (OBR-16)
  ServiceRequest    who ordered the test
  Task              a follow-up to-do for the responsible doctor, if a recent result is abnormal

Patient, Organization and Practitioner use *conditional create* (ifNoneExist): if they already
exist on the server they are reused, so importing reports from five labs gives ONE patient record.
"""
import base64
import json
import re
import uuid
from datetime import datetime, timedelta

import allergy_catalog as alc
import lab_catalog as cat
import hl7v2

BASE = "https://labbridge.example"
TAG = {"system": "urn:labbridge", "code": "hackathon-demo"}
ORIGINAL_EXT = f"{BASE}/fhir/StructureDefinition/original-quantity"
INTERP_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
INTERP_DISPLAY = {"N": "Normal", "H": "High", "L": "Low", "HH": "Critical high",
                  "LL": "Critical low", "A": "Abnormal"}
ABNORMAL = {"H", "L", "HH", "LL", "A"}
FOLLOWUP_WINDOW_DAYS = 30  # older results are history: imported, but no new follow-up task
STATUS = {"F": "final", "P": "preliminary", "C": "corrected", "X": "cancelled"}
LAB_CATEGORY = [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                             "code": "laboratory", "display": "Laboratory"}]}]


def _urn():
    return f"urn:uuid:{uuid.uuid4()}"


def report_identifier(facility: str, filler_id: str) -> dict:
    return {"system": f"{BASE}/{facility}/report", "value": filler_id}


def _parse_range(text: str):
    """'70-99' -> (70, 99); '<5' -> (None, 5); '>60' -> (60, None)."""
    t = (text or "").replace(",", ".").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.fullmatch(r"<=?(\d+(?:\.\d+)?)", t)
    if m:
        return None, float(m.group(1))
    m = re.fullmatch(r">=?(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1)), None
    return None, None


def _interpretation(flag: str, value, low, high):
    f = (flag or "").strip().upper()
    if f in INTERP_DISPLAY:
        code = f
    elif value is not None and low is not None and value < low:
        code = "L"
    elif value is not None and high is not None and value > high:
        code = "H"
    elif value is not None and (low is not None or high is not None):
        code = "N"
    else:
        return None
    return [{"coding": [{"system": INTERP_SYSTEM, "code": code, "display": INTERP_DISPLAY[code]}]}]


def _patient(pid: dict) -> dict:
    gender = {"F": "female", "M": "male", "O": "other"}.get(pid["sex"].upper(), "unknown")
    p = {
        "resourceType": "Patient",
        "meta": {"tag": [TAG]},
        "identifier": [{"system": cat.SVNR_SYSTEM, "value": pid["id"]}],
        "name": [{"family": pid["family"], "given": [pid["given"]] if pid["given"] else []}],
        "gender": gender,
    }
    bd = pid.get("birth_date", "")
    if len(bd) >= 8:
        p["birthDate"] = f"{bd[0:4]}-{bd[4:6]}-{bd[6:8]}"
    return p


def _organization(facility: str) -> dict:
    return {
        "resourceType": "Organization",
        "meta": {"tag": [TAG]},
        "identifier": [{"system": f"{BASE}/lab-id", "value": facility}],
        "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/organization-type",
                              "code": "prov", "display": "Healthcare Provider"}],
                  "text": cat.facility_kind(facility)}],
        "name": cat.lab_name(facility),
    }


def _observation(res: dict, order: dict, facility: str, patient_ref: str, org_ref: str, issues: list) -> dict:
    key = cat.map_code(facility, res["code"], res["coding_system"])
    local = {"system": f"{BASE}/{facility}/codes", "code": res["code"], "display": res["text"]}
    obs = {
        "resourceType": "Observation",
        "meta": {"tag": [TAG]},
        "identifier": [{"system": f"{BASE}/{facility}/result", "value": f"{order['filler_id']}-{res['set_id']}"}],
        "status": STATUS.get(res["status"].upper(), "final"),
        "category": LAB_CATEGORY,
        "subject": {"reference": patient_ref},
        "effectiveDateTime": order["sample_time"].isoformat(),
        "performer": [{"reference": org_ref}],
    }
    low, high = _parse_range(res["range"])

    numeric = None
    if res["value_type"] in ("NM", "SN", ""):
        try:
            numeric = float(res["value"].replace(",", "."))
        except ValueError:
            numeric = None

    if key is None:
        # Unknown code: store it honestly, flagged, with the lab's own code only.
        issues.append(f"{facility}: code '{res['code']}' ({res['text']}) not mapped to LOINC")
        obs["code"] = {"coding": [local], "text": f"{res['text']} (unmapped)"}
        if numeric is not None:
            obs["valueQuantity"] = {"value": numeric, "unit": res["unit"]}
        else:
            obs["valueString"] = res["value"]
        interp = _interpretation(res["flag"], numeric, low, high)
        if interp:
            obs["interpretation"] = interp
        if res["range"]:
            obs["referenceRange"] = [{"text": res["range"]}]
        return obs

    t = cat.TESTS[key]
    obs["code"] = {"coding": [{"system": cat.LOINC, "code": t["loinc"], "display": t["display"]}, local],
                   "text": t["name"]}
    if numeric is None:
        obs["valueString"] = res["value"]
        return obs

    value = cat.to_canonical(key, numeric, res["unit"])
    if value is None:
        issues.append(f"{facility}: unit '{res['unit']}' for {t['name']} not convertible; kept as reported")
        obs["valueQuantity"] = {"value": numeric, "unit": res["unit"]}
        return obs

    obs["valueQuantity"] = {"value": value, "unit": t["unit"], "system": cat.UCUM, "code": t["ucum"]}
    obs["extension"] = [{"url": ORIGINAL_EXT, "valueQuantity": {"value": numeric, "unit": res["unit"]}}]
    rng = {"text": f"{res['range']} {res['unit']} (as reported)"} if res["range"] else None
    if rng:
        q = lambda v: {"value": cat.to_canonical(key, v, res["unit"]), "unit": t["unit"],
                       "system": cat.UCUM, "code": t["ucum"]}
        if low is not None:
            rng["low"] = q(low)
        if high is not None:
            rng["high"] = q(high)
        obs["referenceRange"] = [rng]
    interp = _interpretation(res["flag"], numeric, low, high)  # compare in the lab's own units
    if interp:
        obs["interpretation"] = interp
    return obs


def _practitioner(xcn: dict) -> dict:
    return {
        "resourceType": "Practitioner",
        "meta": {"tag": [TAG]},
        "identifier": [{"system": f"{BASE}/practitioner-id", "value": xcn["id"]}],
        "name": [{"family": xcn["family"], "given": [xcn["given"]] if xcn["given"] else [],
                  "prefix": [xcn["prefix"]] if xcn["prefix"] else []}],
    }


def practitioner_name(p: dict) -> str:
    n = (p or {}).get("name", [{}])[0]
    return " ".join(n.get("prefix", []) + n.get("given", []) + [n.get("family", "")]).strip() or "Unknown doctor"


def _abnormal(obs: dict):
    code = obs.get("interpretation", [{}])[0].get("coding", [{}])[0].get("code", "N")
    return code if code in ABNORMAL else None


def _describe(obs: dict, flag: str) -> str:
    q = obs.get("valueQuantity")
    val = f"{q['value']} {q.get('unit', '')}".strip() if q else obs.get("valueString", "")
    return f"{obs['code'].get('text', '?')} {val} ({INTERP_DISPLAY[flag].lower()})"


def _followup_task(order, report_urn, patient_urn, owner_ref, orderer_urn, flagged, issued, lab, routing):
    critical = any(f in ("HH", "LL") for _, f in flagged)
    task = {
        "resourceType": "Task",
        "meta": {"tag": [TAG]},
        "status": "requested",
        "businessStatus": {"text": "Open"},
        "intent": "order",
        "priority": "stat" if critical else "urgent",
        "code": {"text": "Review abnormal lab result"},
        "description": f"{lab}: " + "; ".join(_describe(o, f) for o, f in flagged),
        "focus": {"reference": report_urn},
        "for": {"reference": patient_urn},
        "authoredOn": issued.isoformat(),
        "lastModified": issued.isoformat(),
        "note": [{"authorString": "LabBridge", "time": issued.isoformat(), "text": routing}],
    }
    if owner_ref:
        task["owner"] = {"reference": owner_ref}
    if orderer_urn:
        task["requester"] = {"reference": orderer_urn}
    return task


def message_to_bundle(msg: dict, skip_reports: set = frozenset(), existing_gp_ref: str = None, now=None):
    """Returns (bundle or None, stats dict). Reports whose id is in skip_reports are left out.

    Routing: a follow-up Task goes to the patient's GP as stored on the server (existing_gp_ref),
    else the GP named in the message (PD1), else the doctor who ordered the test (OBR-16).
    """
    now = now or datetime.now(hl7v2.VIENNA)
    facility = msg["msh"]["sending_facility"]
    pid = msg["pid"]
    issues = []
    if pid.get("id_type", "").upper() == "SVNR" and not cat.svnr_is_valid(pid["id"]):
        issues.append(f"Patient id {pid['id']} fails the SVNR checksum")

    patient_urn, org_urn = _urn(), _urn()
    entries, doctors = [], {}

    def doctor_ref(xcn):
        """Adds a Practitioner (conditional create, once per bundle) and returns its urn."""
        if not xcn:
            return None
        if xcn["id"] not in doctors:
            urn = _urn()
            doctors[xcn["id"]] = urn
            entries.append({"fullUrl": urn, "resource": _practitioner(xcn),
                            "request": {"method": "POST", "url": "Practitioner",
                                        "ifNoneExist": f"identifier={BASE}/practitioner-id|{xcn['id']}"}})
        return doctors[xcn["id"]]

    patient = _patient(pid)
    gp_urn = doctor_ref(msg.get("gp"))
    if gp_urn:
        patient["generalPractitioner"] = [{"reference": gp_urn}]
    entries.insert(0, {"fullUrl": patient_urn, "resource": patient,
                       "request": {"method": "POST", "url": "Patient",
                                   "ifNoneExist": f"identifier={cat.SVNR_SYSTEM}|{pid['id']}"}})
    entries.append({"fullUrl": org_urn, "resource": _organization(facility),
                    "request": {"method": "POST", "url": "Organization",
                                "ifNoneExist": f"identifier={BASE}/lab-id|{facility}"}})

    stats = {"reports": 0, "observations": 0, "skipped": 0, "tasks": 0, "allergies": 0, "issues": issues}
    raw_b64 = base64.b64encode(msg["raw"].encode()).decode()
    issued = msg["msh"]["datetime"] or now

    # Allergies (HL7 v2 AL1). One record per patient and substance, whichever system reports it first.
    msg_type = msg["msh"].get("type", "").replace("^", " ")
    for al in msg.get("allergies", []):
        key = alc.map_allergen(facility, al["code"], al["text"])
        if key is None:
            issues.append(f"{facility}: allergen '{al['code']}' ({al['text']}) not mapped to a standard code")
        criticality, severity = alc.AL1_SEVERITY.get(al["severity"], ("unable-to-assess", None))
        res = make_allergy(
            pid["id"], patient_urn, key or "other-" + alc.slug(al["text"] or al["code"]), al["text"],
            local={"system": f"{BASE}/{facility}/allergens", "code": al["code"], "display": al["text"]},
            category=alc.AL1_CATEGORY.get(al["type"]), criticality=criticality, severity=severity,
            reactions=al["reactions"], kind="intolerance" if al["type"] == "MC" else "allergy",
            onset=al["since"], recorded=issued,
            note=f"Reported by {cat.lab_name(facility)} (HL7 v2 {msg_type}).")
        entries.append({"fullUrl": _urn(), "resource": res,
                        "request": {"method": "POST", "url": "AllergyIntolerance",
                                    "ifNoneExist": f"identifier={BASE}/allergy|{res['identifier'][0]['value']}"}})
        stats["allergies"] += 1

    for order in msg["orders"]:
        if order["filler_id"] in skip_reports:
            stats["skipped"] += 1
            continue
        obs_entries = []
        for res in order["results"]:
            obs_entries.append({"fullUrl": _urn(),
                                "resource": _observation(res, order, facility, patient_urn, org_urn, issues),
                                "request": {"method": "POST", "url": "Observation"}})
        orderer_urn = doctor_ref(order.get("orderer"))
        report_urn = _urn()
        report = {
            "resourceType": "DiagnosticReport",
            "meta": {"tag": [TAG]},
            "identifier": [report_identifier(facility, order["filler_id"])],
            "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                                      "code": "LAB", "display": "Laboratory"}]}],
            "code": {"coding": [{"system": cat.LOINC, "code": "11502-2", "display": "Laboratory report"}],
                     "text": order["text"] or "Laboratory report"},
            "subject": {"reference": patient_urn},
            "effectiveDateTime": order["sample_time"].isoformat(),
            "issued": issued.isoformat(),
            "performer": [{"reference": org_urn}],
            "result": [{"reference": e["fullUrl"]} for e in obs_entries],
            "presentedForm": [{"contentType": "text/plain", "title": "Original HL7 v2 message",
                               "data": raw_b64}],
        }
        if orderer_urn:  # who ordered the test, as a FHIR ServiceRequest
            sr_urn = _urn()
            entries.append({"fullUrl": sr_urn, "request": {"method": "POST", "url": "ServiceRequest"}, "resource": {
                "resourceType": "ServiceRequest", "meta": {"tag": [TAG]}, "status": "completed",
                "intent": "order", "category": [{"text": "Laboratory"}],
                "code": {"text": order["text"] or "Laboratory test"},
                "subject": {"reference": patient_urn}, "requester": {"reference": orderer_urn},
                "authoredOn": order["sample_time"].isoformat()}})
            report["basedOn"] = [{"reference": sr_urn}]
        entries.append({"fullUrl": report_urn, "resource": report,
                        "request": {"method": "POST", "url": "DiagnosticReport"}})
        entries += obs_entries
        stats["reports"] += 1
        stats["observations"] += len(obs_entries)

        # Follow-up: recent reports with abnormal values become a Task for the responsible doctor.
        flagged = [(e["resource"], f) for e in obs_entries if (f := _abnormal(e["resource"]))]
        recent = now - order["sample_time"] <= timedelta(days=FOLLOWUP_WINDOW_DAYS)
        if flagged and recent:
            if existing_gp_ref:
                owner, routing = existing_gp_ref, "Routed to the patient's GP (from the patient record)."
            elif gp_urn:
                owner, routing = gp_urn, "Routed to the GP named in the lab message."
            elif orderer_urn:
                owner, routing = orderer_urn, "No GP on record: routed to the ordering doctor."
            else:
                owner, routing = None, "No responsible doctor known: unassigned."
            task = _followup_task(order, report_urn, patient_urn, owner, orderer_urn, flagged, issued,
                                  cat.lab_name(facility), routing)
            entries.append({"fullUrl": _urn(), "resource": task, "request": {"method": "POST", "url": "Task"}})
            stats["tasks"] += 1

    if stats["reports"] == 0 and stats["allergies"] == 0:
        return None, stats
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}, stats


def import_hl7(server, text: str, now=None) -> dict:
    """Parses an HL7 file, skips reports already on the server, sends the rest. Returns a summary."""
    summary = {"messages": 0, "reports": 0, "observations": 0, "skipped": 0, "tasks": 0, "allergies": 0,
               "issues": [], "errors": []}
    try:
        messages = hl7v2.parse_text(text)
    except Exception as e:
        summary["errors"].append(f"Could not parse file: {e}")
        return summary
    for msg in messages:
        summary["messages"] += 1
        facility = msg["msh"]["sending_facility"]
        skip = {o["filler_id"] for o in msg["orders"]
                if server.report_exists(report_identifier(facility, o["filler_id"]))}
        existing = server.find_patient(cat.SVNR_SYSTEM, msg["pid"]["id"])
        gp_ref = ((existing or {}).get("generalPractitioner") or [{}])[0].get("reference")
        bundle, stats = message_to_bundle(msg, skip, gp_ref, now)
        summary["skipped"] += stats["skipped"]
        summary["issues"] += stats["issues"]
        if bundle is None:
            continue
        try:
            server.transaction(bundle)
            for k in ("reports", "observations", "tasks", "allergies"):
                summary[k] += stats[k]
        except Exception as e:
            summary["errors"].append(f"Message {msg['msh'].get('control_id')}: {e}")
    return summary


# ---------- follow-up workflow (doctor clicks in the inbox) ----------

def advance_task(task: dict, doctor_name: str, now=None) -> dict:
    """Open -> Acknowledged -> Patient informed. Every step is recorded in Task.note (audit trail)."""
    now = (now or datetime.now(hl7v2.VIENNA)).isoformat()
    t = json.loads(json.dumps(task))
    if t["status"] == "requested":
        t["status"], t["businessStatus"], step = "in-progress", {"text": "Acknowledged"}, "Result acknowledged"
    elif t["status"] == "in-progress":
        t["status"], t["businessStatus"], step = "completed", {"text": "Patient informed"}, "Patient informed"
        t["executionPeriod"] = {"end": now}
    else:
        return t
    t["lastModified"] = now
    t.setdefault("note", []).append({"authorString": doctor_name, "time": now, "text": step})
    return t


# ---------- allergies ----------

def make_allergy(svnr: str, patient_ref: str, key: str, text: str = "", local: dict = None, category: str = None,
                 criticality: str = None, severity: str = None, reactions=(), kind: str = "allergy",
                 onset: str = "", recorded=None, recorder_ref: str = None, note: str = None) -> dict:
    """FHIR AllergyIntolerance. key: a substance from allergy_catalog, 'nka' (no known allergies),
    or 'other-<name>' for substances without a standard code."""
    recorded = recorded or datetime.now(hl7v2.VIENNA)
    sub = alc.SUBSTANCES.get(key)
    codings = [alc.NKA] if key == "nka" else ([sub["coding"]] if sub else [])
    if local:
        codings.append(local)
    name = "No known allergies" if key == "nka" else (sub["name"] if sub else text)
    res = {
        "resourceType": "AllergyIntolerance",
        "meta": {"tag": [TAG]},
        "identifier": [{"system": f"{BASE}/allergy", "value": f"{svnr}-{key}"}],
        "clinicalStatus": {"coding": [{"system": alc.CLINICAL, "code": "active", "display": "Active"}]},
        "verificationStatus": {"coding": [{"system": alc.VERIFICATION, "code": "confirmed", "display": "Confirmed"}]},
        "code": ({"coding": codings, "text": name} if codings else {"text": name}),
        "patient": {"reference": patient_ref},
        "recordedDate": recorded.isoformat(),
    }
    if key != "nka":
        res["type"] = kind
        cat_ = category or (sub or {}).get("category")
        if cat_:
            res["category"] = [cat_]
        if criticality:
            res["criticality"] = criticality
        if reactions:
            reaction = {"manifestation": [{"text": r} for r in reactions]}
            if severity:
                reaction["severity"] = severity
            res["reaction"] = [reaction]
        if onset and len(onset) >= 8:
            res["onsetDateTime"] = f"{onset[0:4]}-{onset[4:6]}-{onset[6:8]}"
    if recorder_ref:
        res["recorder"] = {"reference": recorder_ref}
    if note:
        res["note"] = [{"text": note, "time": recorded.isoformat()}]
    return res


def allergy_is_active(a: dict) -> bool:
    ver = a.get("verificationStatus", {}).get("coding", [{}])[0].get("code")
    clin = a.get("clinicalStatus", {}).get("coding", [{}])[0].get("code")
    return ver != "entered-in-error" and clin == "active"


def allergy_is_nka(a: dict) -> bool:
    return any(c.get("code") == alc.NKA["code"] for c in a.get("code", {}).get("coding", []))


def retire_allergy(a: dict, who: str, how: str, now=None) -> dict:
    """how='entered-in-error' (recorded by mistake) or 'inactive' (no longer applies)."""
    now = (now or datetime.now(hl7v2.VIENNA)).isoformat()
    t = json.loads(json.dumps(a))
    if how == "entered-in-error":
        t["verificationStatus"] = {"coding": [{"system": alc.VERIFICATION, "code": "entered-in-error",
                                               "display": "Entered in Error"}]}
        t.pop("clinicalStatus", None)  # FHIR rule: no clinical status on entered-in-error records
        text = "Removed: entered in error"
    else:
        t["clinicalStatus"] = {"coding": [{"system": alc.CLINICAL, "code": "inactive", "display": "Inactive"}]}
        text = "Set to inactive: an allergy has since been recorded"
    t.setdefault("note", []).append({"authorString": who, "time": now, "text": text})
    return t
