"""
Minimal HL7 v2 parser for lab result messages (ORU^R01).

HL7 v2 basics:
- A message is a list of SEGMENTS, one per line (MSH, PID, OBR, OBX, ...).
- Fields inside a segment are separated by  |
- Components inside a field are separated by  ^
- MSH is special: its first field IS the separator "|", so MSH field numbers are shifted by one.

Segments we use:
  MSH  message header   (who sent it, when, message id)
  PID  patient          (PID-3 id, PID-5 name, PID-7 birth date, PID-8 sex)
  OBR  test order       (OBR-3 lab's report number, OBR-4 test/panel, OBR-7 sample time)
  OBX  one result       (OBX-3 test code, OBX-5 value, OBX-6 unit, OBX-7 range, OBX-8 flag, OBX-11 status)
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

VIENNA = ZoneInfo("Europe/Vienna")


def _comp(field: str) -> list:
    return field.split("^") if field else []


def _get(parts: list, i: int) -> str:
    return parts[i] if i < len(parts) else ""


def parse_ts(ts: str):
    """HL7 timestamp YYYYMMDD[HHMM[SS]] (local time, Vienna) -> aware datetime."""
    ts = (ts or "").strip()
    if not ts:
        return None
    fmt = {8: "%Y%m%d", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}.get(len(ts[:14]))
    if not fmt:
        raise ValueError(f"Unsupported HL7 timestamp: {ts}")
    return datetime.strptime(ts[:14], fmt).replace(tzinfo=VIENNA)


def parse_xcn(field: str):
    """HL7 'XCN' (a person, e.g. a doctor): ID^Family^Given^Middle^Suffix^Prefix. None if empty."""
    c = _comp(field)
    if not c or not c[0]:
        return None
    return {"id": c[0], "family": _get(c, 1), "given": _get(c, 2), "prefix": _get(c, 5)}


def split_messages(text: str) -> list:
    """A file may contain several messages; each starts with an MSH segment."""
    segments = [s for s in re.split(r"[\r\n]+", text) if s.strip()]
    messages, current = [], []
    for seg in segments:
        if seg.startswith("MSH") and current:
            messages.append(current)
            current = []
        current.append(seg)
    if current:
        messages.append(current)
    return messages


def parse_message(segments: list) -> dict:
    msg = {"raw": "\r".join(segments), "msh": {}, "pid": {}, "gp": None, "orders": [], "allergies": []}
    for seg in segments:
        p = seg.split("|")
        kind = p[0]
        if kind == "MSH":
            # MSH-n is p[n-1] because MSH-1 is the "|" separator itself
            msg["msh"] = {
                "sending_app": (_comp(_get(p, 2)) or [""])[0],
                "sending_facility": (_comp(_get(p, 3)) or [""])[0],
                "datetime": parse_ts(_get(p, 6)),
                "type": _get(p, 8),
                "control_id": _get(p, 9),
                "version": _get(p, 11),
            }
        elif kind == "PID":
            ident = _comp(_get(p, 3))
            name = _comp(_get(p, 5))
            msg["pid"] = {
                "id": ident[0] if ident else "",
                "id_type": ident[3] if len(ident) > 3 else "",
                "family": name[0] if name else "",
                "given": name[1] if len(name) > 1 else "",
                "birth_date": _get(p, 7),
                "sex": _get(p, 8),
            }
        elif kind == "AL1":
            # AL1: one allergy. AL1-2 type, AL1-3 allergen, AL1-4 severity, AL1-5 reactions (~ repeats), AL1-6 since
            code = _comp(_get(p, 3))
            msg["allergies"].append({
                "type": _get(p, 2),
                "code": _get(code, 0),
                "text": _get(code, 1),
                "severity": _get(p, 4).upper(),
                "reactions": [r for r in _get(p, 5).split("~") if r],
                "since": _get(p, 6),
            })
        elif kind == "PD1":
            msg["gp"] = parse_xcn(_get(p, 4))  # PD1-4: patient's primary care provider (GP)
        elif kind == "OBR":
            svc = _comp(_get(p, 4))
            msg["orders"].append({
                "filler_id": _get(p, 3),
                "code": svc[0] if svc else "",
                "text": svc[1] if len(svc) > 1 else "",
                "sample_time": parse_ts(_get(p, 7)),
                "orderer": parse_xcn(_get(p, 16)),  # OBR-16: doctor who ordered the test
                "results": [],
            })
        elif kind == "OBX":
            if not msg["orders"]:
                raise ValueError("OBX segment before any OBR segment")
            code = _comp(_get(p, 3))
            msg["orders"][-1]["results"].append({
                "set_id": _get(p, 1),
                "value_type": _get(p, 2),
                "code": code[0] if code else "",
                "text": code[1] if len(code) > 1 else "",
                "coding_system": code[2] if len(code) > 2 else "",
                "value": _get(p, 5),
                "unit": _get(p, 6),
                "range": _get(p, 7),
                "flag": _get(p, 8),
                "status": _get(p, 11),
            })
    if msg["msh"].get("type", "").split("^")[0] not in ("ORU", "ADT"):
        raise ValueError(f"Unsupported message type {msg['msh'].get('type')}: expected lab results (ORU) "
                         f"or patient data (ADT)")
    return msg


def parse_text(text: str) -> list:
    return [parse_message(m) for m in split_messages(text)]


# ---------- writing (used by the demo data generator) ----------

def fmt_ts(dt) -> str:
    return dt.astimezone(VIENNA).strftime("%Y%m%d%H%M")


def build_adt(facility: str, control_id: str, sent, patient: dict, allergies: list, event: str = "A08") -> str:
    """Patient update message (ADT^A08) carrying allergies in AL1 segments.
    allergies: [{"type","code","text","severity","reactions":[...],"since"}]"""
    segs = [
        f"MSH|^~\\&|KIS|{facility}|LABBRIDGE|LABBRIDGE|{fmt_ts(sent)}||ADT^{event}|{control_id}|P|2.5",
        f"EVN|{event}|{fmt_ts(sent)}",
        f"PID|1||{patient['svnr']}^^^SVNR||{patient['family']}^{patient['given']}||{patient['birth']}|{patient['sex']}",
    ]
    if patient.get("gp"):
        segs.append(f"PD1||||{patient['gp']}")
    for i, a in enumerate(allergies, 1):
        segs.append(f"AL1|{i}|{a['type']}|{a['code']}^{a['text']}^L|{a['severity']}|"
                    f"{'~'.join(a['reactions'])}|{a.get('since', '')}")
    return "\r\n".join(segs) + "\r\n"


def build_oru(facility: str, control_id: str, sent, patient: dict, orders: list) -> str:
    """orders: [{"filler_id","code","text","sample_time","results":[{code,text,value,unit,range,flag}]}]"""
    segs = [
        f"MSH|^~\\&|LIS|{facility}|PRAXSYS|ORDINATION|{fmt_ts(sent)}||ORU^R01|{control_id}|P|2.5",
        f"PID|1||{patient['svnr']}^^^SVNR||{patient['family']}^{patient['given']}||{patient['birth']}|{patient['sex']}",
    ]
    if patient.get("gp"):
        segs.append(f"PD1||||{patient['gp']}")
    for i, o in enumerate(orders, 1):
        segs.append(f"OBR|{i}||{o['filler_id']}|{o['code']}^{o['text']}^L|||{fmt_ts(o['sample_time'])}"
                    + "|" * 9 + o.get("orderer", ""))
        for j, r in enumerate(o["results"], 1):
            vt = "NM" if isinstance(r["value"], (int, float)) else "ST"
            segs.append(f"OBX|{j}|{vt}|{r['code']}^{r['text']}^L||{r['value']}|{r['unit']}|{r['range']}|{r['flag']}|||F")
    return "\r\n".join(segs) + "\r\n"
