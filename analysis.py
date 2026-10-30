"""Turns FHIR Observations into tables, and runs the duplicate-test check."""
from datetime import datetime

import pandas as pd

import lab_catalog as cat
from converter import ORIGINAL_EXT
from hl7v2 import VIENNA


def observations_to_df(observations: list, organizations: dict) -> pd.DataFrame:
    rows = []
    for o in observations:
        codings = o.get("code", {}).get("coding", [])
        loinc = next((c["code"] for c in codings if c.get("system") == cat.LOINC), None)
        local = next((c for c in codings if c.get("system") != cat.LOINC), {})
        key = cat.LOINC_TO_KEY.get(loinc)
        org_id = o.get("performer", [{}])[0].get("reference", "/").split("/")[-1]
        q = o.get("valueQuantity", {})
        orig = next((e["valueQuantity"] for e in o.get("extension", []) if e.get("url") == ORIGINAL_EXT), q)
        interp = o.get("interpretation", [{}])[0].get("coding", [{}])[0].get("code", "")
        rows.append({
            "test": key or f"unmapped:{local.get('code')}",
            "name": cat.TESTS[key]["name"] if key else f"{local.get('display', '?')} (not mapped)",
            "loinc": loinc,
            "mapped": key is not None,
            "lab": organizations.get(org_id, {}).get("name", org_id),
            "time": pd.to_datetime(o["effectiveDateTime"], utc=True).tz_convert(VIENNA),
            "value": q.get("value", o.get("valueString")),
            "unit": q.get("unit", ""),
            "flag": interp,
            "reported_value": orig.get("value"),
            "reported_unit": orig.get("unit", ""),
            "local_code": local.get("code"),
            "range": range_text(o),
            "range_low": (o.get("referenceRange") or [{}])[0].get("low", {}).get("value"),
            "range_high": (o.get("referenceRange") or [{}])[0].get("high", {}).get("value"),
            "id": o.get("id"),
        })
    df = pd.DataFrame(rows)
    return df.sort_values("time") if not df.empty else df


FLAG_TEXT = {"HH": "Critical high", "LL": "Critical low", "H": "High", "L": "Low", "N": "Normal", "A": "Abnormal"}


def range_text(obs: dict) -> str:
    """Reference range in the same unit as the displayed value."""
    rr = (obs.get("referenceRange") or [{}])[0]
    low, high = rr.get("low", {}).get("value"), rr.get("high", {}).get("value")
    unit = obs.get("valueQuantity", {}).get("unit", "")
    if low is not None and high is not None:
        return f"{low:g}–{high:g} {unit}".strip()
    if high is not None:
        return f"< {high:g} {unit}".strip()
    if low is not None:
        return f"> {low:g} {unit}".strip()
    return rr.get("text", "")


def fmt_value(value, unit) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value} {unit}".strip()


def latest_per_test(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    last = df.groupby("test").tail(1).copy()
    counts = df.groupby("test").size().rename("results")
    labs = df.groupby("test")["lab"].nunique().rename("labs")
    return last.join(counts, on="test").join(labs, on="test").sort_values(["mapped", "name"], ascending=[False, True])


def duplicate_check(df: pd.DataFrame, tests: list, now=None) -> list:
    """For each test the doctor wants to order: is there a recent result already?"""
    now = now or datetime.now(VIENNA)
    out = []
    for key in tests:
        t = cat.TESTS[key]
        prev = df[df.test == key] if not df.empty else df
        if prev.empty:
            out.append({"test": t["name"], "status": "ok", "message": "No previous result on record."})
            continue
        last = prev.iloc[-1]
        days = (now - last["time"].to_pydatetime()).days
        info = (f"{fmt_value(last['value'], last['unit'])} ({_flag_word(last['flag'])}) on {last['time']:%d.%m.%Y} "
                f"at {last['lab']}, {days} days ago")
        if days < t["retest_days"]:
            out.append({"test": t["name"], "status": "duplicate",
                        "message": f"Recent result exists: {info}. Usual minimum interval: {t['retest_days']} days."})
        else:
            out.append({"test": t["name"], "status": "ok", "message": f"Last result: {info}."})
    return out


# How long a follow-up may stay unfinished before it counts as overdue (illustrative).
OVERDUE_DAYS = {"stat": 1, "urgent": 3, "routine": 7}


def task_view(task: dict, now=None) -> dict:
    """Adds age and overdue status to a follow-up Task for display."""
    now = now or datetime.now(VIENNA)
    authored = pd.to_datetime(task["authoredOn"]).to_pydatetime()
    age_h = (now - authored).total_seconds() / 3600
    limit = OVERDUE_DAYS.get(task.get("priority", "routine"), 7)
    done = task["status"] in ("completed", "cancelled")
    return {
        "id": task["id"],
        "patient_ref": task.get("for", {}).get("reference", ""),
        "owner_ref": task.get("owner", {}).get("reference", ""),
        "status": task.get("businessStatus", {}).get("text", task["status"]),
        "done": done,
        "priority": task.get("priority", "routine"),
        "description": task.get("description", ""),
        "authored": authored,
        "age": _age_text(age_h),
        "overdue": (not done) and age_h > limit * 24,
        "history": task.get("note", []),
    }


def _age_text(hours: float) -> str:
    if hours < 1:
        return "less than 1 hour"
    if hours < 2:
        return "1 hour"
    if hours < 48:
        return f"{int(hours)} hours"
    return f"{int(hours // 24)} days"


def _flag_word(code):
    return {"H": "high", "L": "low", "N": "normal", "HH": "critical high", "LL": "critical low"}.get(code, "no flag")
