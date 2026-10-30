"""
Visual building blocks for the LabBridge dashboard (HTML + CSS rendered through Streamlit).

Design notes
- Typeface: Atkinson Hyperlegible (Braille Institute), chosen because it keeps easily confused
  characters apart (1 l I, 0 O, 5 S): useful when reading lab values quickly.
- Colour: navy for structure, violet (the cap colour of blood-count tubes) as the brand accent,
  red only for critical results, amber for abnormal, green for normal.
- Signature element: the range gauge. A bar shows the normal range, a dot shows the patient's value.
"""
import html
import math

NAVY, VIOLET, RED, AMBER, GREEN, MUTED = "#14213D", "#5B4BC4", "#C8102E", "#B7791F", "#2F855A", "#5D6B85"
FLAG_TEXT = {"HH": "Critical high", "LL": "Critical low", "H": "High", "L": "Low", "N": "Normal", "A": "Abnormal"}
SEVERITY = {"HH": "crit", "LL": "crit", "H": "abn", "L": "abn", "A": "abn", "N": "ok"}

CSS = """
<style>
  .block-container {padding-top: 2.2rem; max-width: 1180px;}
  h1, h2, h3, h4 {letter-spacing: -0.01em;}
  .tnum {font-variant-numeric: tabular-nums;}

  /* ---------- sidebar ---------- */
  .brand {display: flex; align-items: center; gap: 12px; margin: 4px 0 6px 0;}
  .brand-name {font-size: 1.45rem; font-weight: 700; color: #FFFFFF; line-height: 1;}
  .brand-sub {font-size: 0.85rem; color: #9FB0CF; margin: 2px 0 22px 0; line-height: 1.35;}
  .me {display: flex; align-items: center; gap: 10px; margin: 0 0 6px 0;}
  .me-label {font-size: 0.78rem; color: #9FB0CF;}
  [data-testid="stSidebar"] [data-testid="stRadio"], [data-testid="stSidebar"] [data-testid="stRadio"] > div {width: 100%;}
  [data-testid="stSidebar"] [role="radiogroup"] {gap: 4px; width: 100%; display: flex; flex-direction: column;
      align-items: stretch;}
  [data-testid="stSidebar"] [role="radiogroup"] > div {width: 100%;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"] {width: 100%; padding: 10px 14px; border-radius: 8px;
      margin: 0; transition: background-color 120ms ease;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {background: #1E2D4F;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {background: #2A3B66;
      box-shadow: inset 3px 0 0 #A99BFF;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {font-weight: 700; color: #FFFFFF;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child {display: none;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"] p {font-size: 1rem;}
  [data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:focus-visible) {outline: 2px solid #A99BFF;}

  /* ---------- avatars, pills ---------- */
  .avatar {flex: none; width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center;
      font-weight: 700; font-size: 0.95rem; color: #FFFFFF; background: #5B4BC4;}
  .avatar.sm {width: 34px; height: 34px; font-size: 0.8rem; background: #A99BFF; color: #14213D;}
  .avatar.lg {width: 64px; height: 64px; font-size: 1.35rem;}
  .avatar.crit {background: #C8102E;} .avatar.abn {background: #B7791F;}
  .pill {display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 700;
      white-space: nowrap;}
  .pill.crit {background: #FDE7EA; color: #A50D26;}
  .pill.abn  {background: #FFF4DB; color: #8A5A0B;}
  .pill.ok   {background: #E6F4EC; color: #22663F;}
  .pill.mute {background: #E9EDF4; color: #44526E;}

  /* ---------- critical bar (the only animation: it is meant to catch the eye) ---------- */
  .alertbar {display: flex; align-items: center; gap: 12px; background: #C8102E; color: #FFFFFF;
      padding: 13px 18px; border-radius: 12px; font-weight: 700;}
  .alertbar .sub {font-weight: 400; color: #FFD9DF;}
  .pulse {flex: none; width: 10px; height: 10px; border-radius: 50%; background: #FFFFFF;
      box-shadow: 0 0 0 0 rgba(255,255,255,0.7); animation: pulse 1.6s infinite;}
  @keyframes pulse {0% {box-shadow: 0 0 0 0 rgba(255,255,255,0.7);} 70% {box-shadow: 0 0 0 10px rgba(255,255,255,0);}
      100% {box-shadow: 0 0 0 0 rgba(255,255,255,0);}}
  @media (prefers-reduced-motion: reduce) {.pulse {animation: none;}}

  /* ---------- headings ---------- */
  .hello {color: #5D6B85; font-size: 1rem; margin: 8px 0 2px 0;}
  .headline {font-size: 2.1rem; font-weight: 700; line-height: 1.18; color: #14213D; max-width: 22em;
      margin: 0 0 6px 0;}
  .sub {color: #5D6B85; font-size: 0.95rem;}
  .group {font-size: 1.05rem; font-weight: 700; color: #14213D; margin: 26px 0 8px 0;}
  .group small {font-weight: 400; color: #5D6B85; font-size: 0.9rem; margin-left: 8px;}

  /* ---------- cards ---------- */
  [class*="st-key-card-"] {background: #FFFFFF; border-radius: 14px !important; padding: 20px 22px 14px 22px !important;
      box-shadow: 0 1px 2px rgba(20,33,61,0.05), 0 6px 18px -8px rgba(20,33,61,0.12);}
  [class*="st-key-card-crit"] {border-left: 6px solid #C8102E !important;}
  [class*="st-key-card-abn"]  {border-left: 6px solid #E0A12E !important;}
  [class*="st-key-card-pt"]   {border-left: 6px solid #5B4BC4 !important;}
  [class*="st-key-card-algh"] {border-left: 6px solid #C8102E !important;}
  [class*="st-key-card-algl"] {border-left: 6px solid #14213D !important;}
  .card-head {display: flex; align-items: center; gap: 14px;}
  .card-who {flex: 1; min-width: 0;}
  .card-name {font-size: 1.25rem; font-weight: 700; color: #14213D; line-height: 1.2;}
  .card-facts {display: flex; flex-wrap: wrap; gap: 4px 16px; color: #5D6B85; font-size: 0.9rem; margin-top: 2px;}
  .card-when {text-align: right;}
  .card-when .t {color: #5D6B85; font-size: 0.85rem; margin-top: 4px;}
  .card-when .t.late {color: #C8102E; font-weight: 700;}
  .card-src {color: #44526E; font-size: 0.92rem; margin: 12px 0 4px 0;}

  /* ---------- results with range gauges ---------- */
  .rlist {margin: 6px 0 4px 0;}
  .rrow {display: grid; grid-template-columns: minmax(150px, 1.3fr) 112px minmax(140px, 1.5fr) 128px 112px;
      align-items: center; gap: 16px; padding: 10px 2px; border-top: 1px solid #EEF1F6;}
  .rrow.head {border-top: none; color: #5D6B85; font-size: 0.82rem; padding-bottom: 4px;}
  .rname {font-weight: 700; color: #14213D;}
  .rname small {display: block; font-weight: 400; color: #8391AB; font-size: 0.78rem;}
  .rval {font-size: 1.05rem; font-weight: 700; font-variant-numeric: tabular-nums;}
  .rval.crit {color: #C8102E;} .rval.abn {color: #8A5A0B;} .rval.ok {color: #44526E; font-weight: 400;}
  .rrange {color: #5D6B85; font-size: 0.88rem; font-variant-numeric: tabular-nums;}
  .rrow.ok .rname {font-weight: 400; color: #44526E;}
  .gauge {position: relative; height: 10px; border-radius: 999px; background: #EEF1F6;}
  .gauge .band {position: absolute; top: 0; bottom: 0; border-radius: 999px; background: #CDEBD9;}
  .gauge .dot {position: absolute; top: 50%; width: 14px; height: 14px; margin: -7px 0 0 -7px; border-radius: 50%;
      border: 2px solid #FFFFFF; box-shadow: 0 0 0 1px rgba(20,33,61,0.25);}
  .dot.crit {background: #C8102E;} .dot.abn {background: #E0A12E;} .dot.ok {background: #2F855A;}
  @media (max-width: 860px) {
    .rrow {grid-template-columns: 1fr auto; gap: 6px 12px;}
    .rrow .gauge {grid-column: 1 / -1;} .rrow.head {display: none;}
  }

  /* ---------- follow-up progress ---------- */
  .stepper {display: flex; align-items: center; gap: 0; margin: 14px 0 6px 0; font-size: 0.85rem; color: #8391AB;}
  .step {display: flex; align-items: center; gap: 7px; white-space: nowrap;}
  .step i {width: 12px; height: 12px; border-radius: 50%; border: 2px solid #C5CEDC; background: #FFFFFF; flex: none;}
  .step.done {color: #44526E;} .step.done i {background: #5B4BC4; border-color: #5B4BC4;}
  .step.now {color: #14213D; font-weight: 700;} .step.now i {border-color: #5B4BC4; box-shadow: 0 0 0 3px #E4E0FA;}
  .line {flex: 0 1 46px; min-width: 18px; height: 2px; background: #DCE2EB; margin: 0 8px;}
  .line.done {background: #5B4BC4;}

  /* ---------- patient header ---------- */
  .pt-head {display: flex; align-items: center; gap: 18px;}
  .pt-name {font-size: 1.9rem; font-weight: 700; color: #14213D; line-height: 1.15;}
  .facts {display: flex; flex-wrap: wrap; gap: 8px 28px; margin-top: 8px;}
  .fact span {display: block; font-size: 0.78rem; color: #8391AB;}
  .fact b {font-weight: 700; color: #14213D; font-variant-numeric: tabular-nums;}
  .note {display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 12px; font-size: 0.95rem;}
  .note.crit {background: #FDE7EA; color: #7A0A1C;} .note.abn {background: #FFF4DB; color: #6B4508;}
  .note.ok {background: #E6F4EC; color: #1E5A37;}
  /* ---------- allergies: like a hospital allergy wristband, red means a high-risk allergy ---------- */
  .allergy {display: flex; align-items: center; flex-wrap: wrap; gap: 8px 10px; padding: 10px 14px;
      border-radius: 12px; background: #FFFFFF; border: 1.5px solid #F4C2CA; margin: 2px 0 6px 0;}
  .allergy .lbl {font-weight: 700; color: #A50D26; margin-right: 4px;}
  .allergy .why {color: #5D6B85; font-size: 0.88rem;}
  .allergy.none {border-color: #BFE3CD;} .allergy.none .lbl {color: #22663F;}
  .allergy.unknown {border-color: #F1D79A; background: #FFFBEF;} .allergy.unknown .lbl {color: #8A5A0B;}
  .alg {display: inline-flex; align-items: baseline; gap: 6px; padding: 4px 11px; border-radius: 999px;
      border: 1.5px solid #14213D; font-weight: 700; font-size: 0.9rem; color: #14213D; background: #FFFFFF;}
  .alg small {font-weight: 400; font-size: 0.78rem; color: #5D6B85;}
  .alg.high {background: #C8102E; border-color: #C8102E; color: #FFFFFF;}
  .alg.high small {color: #FFD9DF;}
  .card-alg {margin: 10px 0 2px 0;}
  .card-alg .allergy {padding: 7px 12px; font-size: 0.92rem;}
  .empty {text-align: center; padding: 60px 20px 20px 20px;}
  .empty .headline {margin: 18px auto 8px auto;}
</style>
"""


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def logo(size: int = 36) -> str:
    """Three blood tubes with coloured caps (blood count, serum, heparin)."""
    tubes = []
    for i, cap in enumerate(["#A99BFF", "#F2C14E", "#4FB286"]):
        x = 4 + i * 11
        tubes.append(f'<rect x="{x}" y="9" width="8" height="23" rx="4" fill="#FFFFFF" fill-opacity="0.92"/>'
                     f'<rect x="{x}" y="{22 - i * 3}" width="8" height="{10 + i * 3}" rx="4" fill="#C8102E" fill-opacity="0.85"/>'
                     f'<rect x="{x - 1}" y="4" width="10" height="6" rx="2" fill="{cap}"/>')
    return f'<svg width="{size}" height="{size}" viewBox="0 0 36 36" aria-hidden="true">{"".join(tubes)}</svg>'


def initials(name: str) -> str:
    parts = [p for p in name.replace("Dr.", "").split() if p]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper() if parts else "?"


def avatar(name: str, kind: str = "", size: str = "") -> str:
    return f'<div class="avatar {kind} {size}">{esc(initials(name))}</div>'


def pill(flag: str) -> str:
    return f'<span class="pill {SEVERITY.get(flag, "mute")}">{FLAG_TEXT.get(flag, "No flag")}</span>'


def _num(x):
    """None for missing values (pandas turns None into NaN)."""
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def gauge(value, low, high, flag) -> str:
    value, low, high = _num(value) if isinstance(value, (int, float)) else None, _num(low), _num(high)
    if value is None or (low is None and high is None):
        return '<div class="rrange">no numeric range</div>'
    lo = low if low is not None else 0.0
    hi = high if high is not None else (lo * 2 or 1.0)
    span = (hi - lo) or 1.0
    vmin = min(lo - span * 0.6, value - span * 0.15)
    vmax = max(hi + span * 0.6, value + span * 0.15)
    if low is None:
        vmin = min(0.0, value)
    pct = lambda x: max(0.0, min(100.0, (x - vmin) / (vmax - vmin) * 100))
    left, width = pct(lo), pct(hi) - pct(lo)
    return (f'<div class="gauge" title="Reference range {lo:g}–{hi:g}">'
            f'<div class="band" style="left:{left:.1f}%;width:{width:.1f}%"></div>'
            f'<div class="dot {SEVERITY.get(flag, "ok")}" style="left:{pct(value):.1f}%"></div></div>')


def fmt_value(value, unit) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value} {unit}".strip()


def results(rows, show_lab: bool = False) -> str:
    """rows: dicts with name, value, unit, range, range_low, range_high, flag (and lab)."""
    out = ['<div class="rlist"><div class="rrow head"><div>Test</div><div>Result</div>'
           '<div>Position in reference range</div><div>Reference range</div><div>Flag</div></div>']
    for r in rows:
        sev = SEVERITY.get(r["flag"], "ok")
        sub = f'<small>{esc(r["lab"])}</small>' if show_lab and r.get("lab") else ""
        out.append(f'<div class="rrow {sev}"><div class="rname">{esc(r["name"])}{sub}</div>'
                   f'<div class="rval {sev}">{esc(fmt_value(r["value"], r["unit"]))}</div>'
                   f'{gauge(r["value"], r.get("range_low"), r.get("range_high"), r["flag"])}'
                   f'<div class="rrange">{esc(r["range"] or "–")}</div><div>{pill(r["flag"])}</div></div>')
    out.append("</div>")
    return "".join(out)


def stepper(task_status: str) -> str:
    """Follow-up progress: Received -> Acknowledged -> Patient informed."""
    reached = {"requested": 1, "in-progress": 2, "completed": 3}.get(task_status, 1)
    names = ["Result received", "Acknowledged", "Patient informed"]
    parts = []
    for i, n in enumerate(names, 1):
        cls = "done" if i <= reached else ("now" if i == reached + 1 else "")
        parts.append(f'<div class="step {cls}"><i></i>{n}</div>')
        if i < len(names):
            parts.append(f'<div class="line {"done" if i + 1 <= reached else ""}"></div>')
    return f'<div class="stepper">{"".join(parts)}</div>'


def facts(pairs) -> str:
    return '<div class="facts">' + "".join(f'<div class="fact"><span>{esc(k)}</span><b>{esc(v)}</b></div>'
                                           for k, v in pairs) + "</div>"


# ---------- allergies ----------

def allergy_view(a: dict) -> dict:
    """Flattens a FHIR AllergyIntolerance for display."""
    import allergy_catalog as alc
    ver = a.get("verificationStatus", {}).get("coding", [{}])[0].get("code")
    clin = a.get("clinicalStatus", {}).get("coding", [{}])[0].get("code")
    reactions = [m.get("text", "") for r in a.get("reaction", []) for m in r.get("manifestation", [])]
    severity = next((r.get("severity") for r in a.get("reaction", []) if r.get("severity")), None)
    nka = any(c.get("code") == alc.NKA["code"] for c in a.get("code", {}).get("coding", []))
    return {
        "id": a.get("id"),
        "name": a.get("code", {}).get("text", "Unknown substance"),
        "active": ver != "entered-in-error" and clin == "active",
        "nka": nka,
        "kind": a.get("type", "allergy"),
        "criticality": a.get("criticality"),
        "category": (a.get("category") or [None])[0],
        "reactions": reactions,
        "severity": severity,
        "onset": a.get("onsetDateTime"),
        "recorded": a.get("recordedDate"),
        "recorder_ref": a.get("recorder", {}).get("reference"),
        "notes": a.get("note", []),
        "identifier": (a.get("identifier") or [{}])[0].get("value"),
    }


def allergy_state(views: list):
    """('recorded', allergies) / ('nka', [nka record]) / ('unknown', [])"""
    active = [v for v in views if v["active"]]
    real = [v for v in active if not v["nka"]]
    if real:
        order = {"high": 0, "unable-to-assess": 1, "low": 2}
        return "recorded", sorted(real, key=lambda v: (order.get(v["criticality"], 1), v["name"]))
    nka = [v for v in active if v["nka"]]
    return ("nka", nka) if nka else ("unknown", [])


def allergy_band(views: list, who=None) -> str:
    """The allergy strip shown on the patient page and on worklist cards."""
    state, items = allergy_state(views)
    if state == "unknown":
        return ('<div class="allergy unknown"><span class="lbl">Allergies not recorded</span>'
                '<span class="why">No system has sent allergy information. Ask the patient before prescribing.</span></div>')
    if state == "nka":
        v = items[0]
        when = (v["recorded"] or "")[:10]
        by = f" by {esc(who(v['recorder_ref']))}" if who and v["recorder_ref"] else ""
        when_txt = f"{when[8:10]}.{when[5:7]}.{when[0:4]}" if len(when) == 10 else ""
        return (f'<div class="allergy none"><span class="lbl">No known allergies</span>'
                f'<span class="why">confirmed {when_txt}{by}</span></div>')
    chips = []
    for v in items:
        high = v["criticality"] == "high"
        tag = "high risk" if high else ("intolerance" if v["kind"] == "intolerance" else "")
        title = esc(", ".join(v["reactions"])) if v["reactions"] else ""
        chips.append(f'<span class="alg {"high" if high else ""}" title="{title}">{esc(v["name"])}'
                     + (f"<small>{tag}</small>" if tag else "") + "</span>")
    return f'<div class="allergy"><span class="lbl">Allergies</span>{"".join(chips)}</div>'
