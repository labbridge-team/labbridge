"""
LabBridge: lab results from different labs (HL7 v2) -> one FHIR patient record -> doctor dashboard.
Every abnormal result is routed to the responsible doctor and stays on their worklist until acted on.
Run with:  streamlit run app.py
"""
import base64
import json
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

import lab_catalog as cat
import ui
from analysis import duplicate_check, latest_per_test, observations_to_df, task_view
import uuid

import allergy_catalog as alc
from converter import advance_task, import_hl7, make_allergy, practitioner_name, retire_allergy
from demo_data import demo_files, late_result_file
from fhir_client import HAPI_PUBLIC, LocalFhir, RemoteFhir
from hl7v2 import VIENNA

st.set_page_config(page_title="LabBridge", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)
WORKLIST, PATIENT = "Worklist", "Patient lookup"


def html(markup: str, target=st):
    target.markdown(markup, unsafe_allow_html=True)


def ago(dt) -> str:
    hours = (datetime.now(VIENNA) - dt).total_seconds() / 3600
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    return f"{int(hours // 24)} days ago"


# ---------------- Sidebar: data sources (collapsed) ----------------
side_top = st.sidebar.container()
admin = st.sidebar.expander("Data sources and demo")

with admin:
    backend = st.radio("FHIR server", ["Local (offline)", "HAPI public test server", "Custom URL"])
    if backend == "Local (offline)":
        server = LocalFhir()
    elif backend == "HAPI public test server":
        server = RemoteFhir(HAPI_PUBLIC)
        st.caption("Public server: fake patients only.")
    else:
        server = RemoteFhir(st.text_input("Base URL", "http://localhost:8080/fhir"))


def run_import(named_texts):
    total = {"reports": 0, "observations": 0, "skipped": 0, "tasks": 0, "allergies": 0, "issues": [], "errors": []}
    with st.spinner("Importing lab results"):
        for name, text in named_texts:
            s = import_hl7(server, text)
            for k in ("reports", "observations", "skipped", "tasks", "allergies"):
                total[k] += s[k]
            total["issues"] += s["issues"]
            total["errors"] += [f"{name}: {e}" for e in s["errors"]]
    st.session_state["import_summary"] = total


with admin:
    uploads = st.file_uploader("Import HL7 v2 lab messages", type=["hl7", "txt"], accept_multiple_files=True)
    if uploads and st.button("Import files", width="stretch"):
        run_import([(u.name, u.getvalue().decode("utf-8", errors="replace")) for u in uploads])
    if st.button("Load demo data", width="stretch"):
        run_import(list(demo_files().items()))
    if st.button("Simulate late hospital result", width="stretch"):
        run_import([late_result_file()])
    if backend == "Local (offline)" and st.button("Reset local data", width="stretch"):
        server.reset()
        for k in ("import_summary", "patient_pick", "doctor"):
            st.session_state.pop(k, None)
    if "import_summary" in st.session_state:
        s = st.session_state["import_summary"]
        st.caption(f"Last import: {s['reports']} reports, {s['observations']} results, "
                   f"{s['allergies']} allergy entries, {s['tasks']} sent for follow-up, "
                   f"{s['skipped']} already on file.")
        for i in sorted(set(s["issues"])):
            st.caption(f"Note: {i}")
        for e in s["errors"]:
            st.error(e)

# ---------------- Load data ----------------
try:
    patients = {p["id"]: p for p in server.patients()}
    doctors = server.practitioners()
    raw_tasks = {t["id"]: t for t in server.tasks()}
except Exception as e:
    st.error(f"The FHIR server could not be reached ({e}). Switch to Local (offline) under Data sources and demo.")
    st.stop()

tasks = [task_view(t) for t in raw_tasks.values()]
open_by_doc = {}
for v in tasks:
    if not v["done"]:
        open_by_doc[v["owner_ref"]] = open_by_doc.get(v["owner_ref"], 0) + 1


def svnr_of(p):
    return next((i["value"] for i in p.get("identifier", []) if i.get("system") == cat.SVNR_SYSTEM), "–")


def pname(p):
    n = p.get("name", [{}])[0]
    return f"{' '.join(n.get('given', []))} {n.get('family', '')}".strip() or "Unknown patient"


def age_of(p):
    if not p.get("birthDate"):
        return None
    b, t = date.fromisoformat(p["birthDate"]), date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def doc_name(ref):
    return practitioner_name(doctors.get((ref or "").split("/")[-1])) if ref else "Unassigned"


def go_patient(patient_id):
    st.session_state["mode"] = PATIENT
    st.session_state["patient_pick"] = patient_id


def go_worklist():
    st.session_state["mode"] = WORKLIST


# ---------------- Sidebar: brand, doctor, navigation ----------------
with side_top:
    html(f'<div class="brand">{ui.logo()}<div class="brand-name">LabBridge</div></div>'
         '<div class="brand-sub">Lab results from every lab, in one record</div>')
    doc_id = None
    if doctors:
        doc_ids = sorted(doctors, key=lambda d: -open_by_doc.get(f"Practitioner/{d}", 0))
        if st.session_state.get("doctor") not in doctors:
            st.session_state.pop("doctor", None)
        current = st.session_state.get("doctor", doc_ids[0])
        html(f'<div class="me">{ui.avatar(practitioner_name(doctors[current]), size="sm")}'
             f'<div class="me-label">Signed in as</div></div>')
        doc_id = st.selectbox("Signed in as", doc_ids, key="doctor", label_visibility="collapsed",
                              format_func=lambda d: practitioner_name(doctors[d]))
    st.write("")
    mode = st.radio("Go to", [WORKLIST, PATIENT], key="mode", label_visibility="collapsed")
    st.write("")

if not patients:
    html(f'<div class="empty">{ui.logo(64)}<div class="headline">No lab results yet</div>'
         '<p class="sub">Load the demo data to see two Viennese labs, two patients and their doctors,<br>'
         'or import HL7 lab messages under Data sources and demo in the sidebar.</p></div>')
    _, mid, _ = st.columns([2, 1, 2])
    if mid.button("Load demo data", type="primary", width="stretch", key="empty-demo"):
        run_import(list(demo_files().items()))
        st.rerun()
    st.stop()

me = practitioner_name(doctors[doc_id]) if doc_id else "Unassigned"
my_ref = f"Practitioner/{doc_id}"
mine_open = [v for v in tasks if v["owner_ref"] == my_ref and not v["done"]]
critical = [v for v in mine_open if v["priority"] == "stat"]
overdue = [v for v in mine_open if v["overdue"]]

# ---------------- Critical bar (every screen) ----------------
if critical:
    n = len(critical)
    a, b = st.columns([5, 1], vertical_alignment="center") if mode != WORKLIST else (st.container(), None)
    html(f'<div class="alertbar"><span class="pulse"></span>{n} critical result{"s" if n > 1 else ""} '
         f'waiting for your review<span class="sub">oldest received {ago(min(v["authored"] for v in critical))}'
         f'</span></div>', a)
    if mode != WORKLIST:
        b.button("Review now", type="primary", on_click=go_worklist, width="stretch")

# ================= WORKLIST =================
if mode == WORKLIST:
    now = datetime.now(VIENNA)
    greeting = "Good evening" if now.hour < 5 else "Good morning" if now.hour < 12 else ("Good afternoon" if now.hour < 18 else "Good evening")
    surname = me.split()[-1] if doc_id else ""
    bits = []
    if critical:
        bits.append(f"{len(critical)} critical result{'s' if len(critical) > 1 else ''}")
    rest = len(mine_open) - len(critical)
    if rest:
        bits.append(f"{rest} abnormal report{'s' if rest > 1 else ''}")
    headline = (" and ".join(bits) + (" need" if len(mine_open) > 1 else " needs") + " your attention."
                ) if bits else "Nothing is waiting for you."
    html(f'<div class="hello">{greeting}, Dr. {ui.esc(surname)}. {now:%A, %d %B %Y}</div>'
         f'<div class="headline">{headline}</div>'
         + (f'<div class="sub">{len(overdue)} of them overdue.</div>' if overdue else ""))

    orgs = server.organizations()
    obs_cache, alg_cache = {}, {}

    def allergies_of(patient_id):
        if patient_id not in alg_cache:
            alg_cache[patient_id] = [ui.allergy_view(a) for a in server.allergies(patient_id)]
        return alg_cache[patient_id]

    def report_rows(task):
        rep = server.read("DiagnosticReport", task["focus"]["reference"].split("/")[-1]) if task.get("focus") else None
        if not rep:
            return None, []
        pid = rep["subject"]["reference"].split("/")[-1]
        if pid not in obs_cache:
            obs_cache[pid] = observations_to_df(server.observations(pid), orgs)
        df = obs_cache[pid]
        ids = {r["reference"].split("/")[-1] for r in rep.get("result", [])}
        rows = df[df["id"].isin(ids)].to_dict("records") if not df.empty else []
        order = {"HH": 0, "LL": 0, "H": 1, "L": 1, "A": 1}
        rows.sort(key=lambda r: order.get(r["flag"], 2))
        lab = orgs.get(rep["performer"][0]["reference"].split("/")[-1], {}).get("name", "an unknown lab")
        return lab, rows

    def card(v):
        task = raw_tasks[v["id"]]
        p = patients.get(v["patient_ref"].split("/")[-1], {})
        kind = "crit" if v["priority"] == "stat" else "abn"
        lab, rows = report_rows(task)
        age = age_of(p)
        with st.container(border=True, key=f"card-{kind}-{v['id']}"):
            when = (f'<div class="t late">Overdue, received {ago(v["authored"])}</div>' if v["overdue"]
                    else f'<div class="t">Received {ago(v["authored"])}</div>')
            label = "Critical" if kind == "crit" else "Abnormal"
            html(f'<div class="card-head">{ui.avatar(pname(p), kind)}<div class="card-who">'
                 f'<div class="card-name">{ui.esc(pname(p))}</div><div class="card-facts">'
                 f'<span>SVNR {ui.esc(svnr_of(p))}</span>'
                 + (f'<span>{age} years, {ui.esc(p.get("gender", ""))}</span>' if age is not None else "")
                 + f'</div></div><div class="card-when"><span class="pill {kind}">{label}</span>{when}</div></div>')
            ordered = f", ordered by {ui.esc(doc_name(task['requester']['reference']))}" if task.get("requester") else ""
            html(f'<div class="card-src">From {ui.esc(lab or "an unknown lab")}{ordered}.</div>')
            html(f'<div class="card-alg">{ui.allergy_band(allergies_of(v["patient_ref"].split("/")[-1]), doc_name)}</div>')
            html(ui.results(rows) if rows else f"<p>{ui.esc(v['description'])}</p>")
            html(ui.stepper(task["status"]))
            b1, b2, _ = st.columns([1.3, 1.3, 3])
            action = "Acknowledge result" if task["status"] == "requested" else "Mark patient informed"
            if b1.button(action, key=f"adv-{v['id']}", type="primary", width="stretch"):
                server.update(advance_task(task, me))
                st.rerun()
            b2.button("Open patient record", key=f"open-{v['id']}", on_click=go_patient,
                      args=(v["patient_ref"].split("/")[-1],), width="stretch")
            if v["history"]:
                st.caption(v["history"][0]["text"])

    rank = lambda v: (not v["overdue"], v["authored"])
    if not mine_open:
        html('<div class="note ok">Every abnormal result assigned to you has been followed up.</div>')
    if critical:
        html('<div class="group">Critical</div>')
        for v in sorted(critical, key=rank):
            card(v)
    other = [v for v in mine_open if v["priority"] != "stat"]
    if other:
        html('<div class="group">Abnormal results<small>outside the reference range, not critical</small></div>')
        for v in sorted(other, key=rank):
            card(v)

    done = sorted([v for v in tasks if v["owner_ref"] == my_ref and v["done"]],
                  key=lambda v: v["authored"], reverse=True)
    if done:
        st.write("")
        with st.expander(f"Completed follow-ups ({len(done)})"):
            for v in done:
                p = patients.get(v["patient_ref"].split("/")[-1], {})
                st.markdown(f"**{pname(p)}**: {v['description']}")
                st.caption(" → ".join(f"{n.get('text')} ({n.get('authorString')}, "
                                      f"{pd.to_datetime(n.get('time')):%d.%m. %H:%M})" for n in v["history"]))
    st.caption("Overdue after 1 day for critical results and 3 days for other abnormal results (demo values).")
    st.stop()

# ================= PATIENT LOOKUP =================
s1, s2 = st.columns([1, 2])
query = s1.text_input("Search by e-card number (SVNR)", placeholder="10 digits")
if query:
    q = query.replace(" ", "")
    if not cat.svnr_is_valid(q):
        s1.error("This is not a valid e-card number. Check the 10 digits.")
        st.stop()
    patient = server.find_patient(cat.SVNR_SYSTEM, q)
    if not patient:
        s1.info("No record for this e-card number yet.")
        st.stop()
else:
    if st.session_state.get("patient_pick") not in patients:
        st.session_state.pop("patient_pick", None)
    pick = s2.selectbox("Or choose a patient", list(patients), key="patient_pick",
                        format_func=lambda i: f"{pname(patients[i])}  (SVNR {svnr_of(patients[i])})")
    patient = patients[pick]

pid = patient["id"]
orgs = server.organizations()
df = observations_to_df(server.observations(pid), orgs)
reports = sorted(server.reports(pid), key=lambda r: r["effectiveDateTime"], reverse=True)
gp_ref = (patient.get("generalPractitioner") or [{}])[0].get("reference")
pt_tasks = [v for v in tasks if v["patient_ref"] == f"Patient/{pid}"]
pt_open = [v for v in pt_tasks if not v["done"]]

with st.container(border=True, key="card-pt-head"):
    born = date.fromisoformat(patient["birthDate"]).strftime("%d.%m.%Y") if patient.get("birthDate") else "–"
    age = age_of(patient)
    html(f'<div class="pt-head">{ui.avatar(pname(patient), size="lg")}<div>'
         f'<div class="pt-name">{ui.esc(pname(patient))}</div>'
         + ui.facts([("e-card (SVNR)", svnr_of(patient)),
                     ("Born", f"{born} ({age} years)" if age is not None else born),
                     ("Sex", patient.get("gender", "–")),
                     ("GP", doc_name(gp_ref) if gp_ref else "not known"),
                     ("Labs on file", df["lab"].nunique() if not df.empty else 0),
                     ("Reports", len(reports))])
         + '</div></div>')

html(ui.allergy_band([ui.allergy_view(a) for a in server.allergies(pid)], doc_name))


def create(resource: dict):
    server.transaction({"resourceType": "Bundle", "type": "transaction", "entry": [
        {"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource,
         "request": {"method": "POST", "url": resource["resourceType"]}}]})


def allergy_section(patient):
    pid, svnr = patient["id"], svnr_of(patient)
    raw = {a["id"]: a for a in server.allergies(pid)}
    views = [ui.allergy_view(a) for a in raw.values()]
    state, items = ui.allergy_state(views)
    if "alg_msg" in st.session_state:
        html(f'<div class="note ok" style="margin-bottom:10px">{ui.esc(st.session_state.pop("alg_msg"))}</div>')

    if state == "recorded":
        for v in items:
            high = v["criticality"] == "high"
            with st.container(border=True, key=f"card-alg{'h' if high else 'l'}-{v['id']}"):
                left, right = st.columns([5, 1.5], vertical_alignment="top")
                risk = alc.CRITICALITY_TEXT.get(v["criticality"], "Risk not assessed")
                html(f'<div class="card-head"><div class="card-who"><div class="card-name">{ui.esc(v["name"])}</div>'
                     f'</div><span class="pill {"crit" if high else "mute"}">{risk}</span></div>', left)
                reaction = ", ".join(v["reactions"]) or "not described"
                if v["severity"]:
                    reaction += f" ({v['severity']})"
                onset = f"{v['onset'][8:10]}.{v['onset'][5:7]}.{v['onset'][0:4]}" if v["onset"] else "unknown"
                first = v["notes"][0]["text"] if v["notes"] else ""
                source = first if first.startswith(("Reported", "Recorded")) else (
                    f"Recorded by {doc_name(v['recorder_ref'])}" if v["recorder_ref"] else "unknown")
                html(ui.facts([("Type", v["kind"].capitalize()),
                               ("Category", alc.CATEGORY_TEXT.get(v["category"], "–")),
                               ("Reaction", reaction), ("Since", onset)]), left)
                left.caption(f"{source} Recorded on {v['recorded'][8:10]}.{v['recorded'][5:7]}.{v['recorded'][0:4]}.")
                if right.button("Remove, entered in error", key=f"eie-{v['id']}", width="stretch"):
                    server.update(retire_allergy(raw[v["id"]], me, "entered-in-error"))
                    st.session_state["alg_msg"] = f"{v['name']} removed from the allergy list."
                    st.rerun()
    elif state == "nka":
        html('<div class="note ok">The patient has no known allergies. Recording an allergy below replaces this.</div>')
    else:
        html('<div class="note abn">No system has sent allergy information for this patient. '
             'Ask the patient, then record the answer here.</div>')
        st.write("")
        if st.button("Record: no known allergies", key=f"nka-{pid}"):
            create(make_allergy(svnr, f"Patient/{pid}", "nka", recorder_ref=my_ref if doc_id else None,
                                note=f"Recorded by {me} in LabBridge."))
            st.session_state["alg_msg"] = "Saved: no known allergies."
            st.rerun()

    html('<div class="group">Record an allergy</div>')
    with st.form(f"add-allergy-{pid}", clear_on_submit=True):
        c1, c2 = st.columns(2)
        choice = c1.selectbox("Substance", list(alc.SUBSTANCES) + ["other"],
                              format_func=lambda k: alc.SUBSTANCES[k]["name"] if k in alc.SUBSTANCES
                              else "Other, type the name")
        other = c2.text_input("Other substance", placeholder="Only if you chose Other")
        c3, c4, c5 = st.columns(3)
        kind = c3.selectbox("Type", ["allergy", "intolerance"], format_func=str.capitalize)
        crit = c4.selectbox("Risk of a serious reaction", ["high", "low", "unable-to-assess"],
                            format_func=lambda k: alc.CRITICALITY_TEXT[k])
        sev = c5.selectbox("Past reaction was", ["severe", "moderate", "mild", "unknown"], format_func=str.capitalize)
        reaction = st.text_input("Reaction", placeholder="For example: hives, shortness of breath")
        saved = st.form_submit_button("Save allergy", type="primary")
    if saved:
        if choice == "other" and not other.strip():
            st.error("Type the name of the substance, or choose one from the list.")
            return
        key = choice if choice != "other" else (alc.map_allergen("", "", other) or "other-" + alc.slug(other))
        name = alc.SUBSTANCES[key]["name"] if key in alc.SUBSTANCES else other.strip()
        if state == "recorded" and any(v["identifier"] == f"{svnr}-{key}" for v in items):
            st.warning(f"{name} is already on the allergy list.")
            return
        create(make_allergy(svnr, f"Patient/{pid}", key, other.strip(), criticality=crit,
                            severity=None if sev == "unknown" else sev, kind=kind,
                            reactions=[r.strip() for r in reaction.split(",") if r.strip()],
                            recorder_ref=my_ref if doc_id else None, note=f"Recorded by {me} in LabBridge."))
        for v in views:
            if v["active"] and v["nka"]:
                server.update(retire_allergy(raw[v["id"]], me, "inactive"))
        st.session_state["alg_msg"] = f"{name} added to the allergy list."
        st.rerun()
    st.caption("Medicines are coded with WHO ATC, other substances with SNOMED CT. Stored as FHIR AllergyIntolerance.")


if df.empty:
    html('<div class="note abn" style="margin:10px 0">No lab results for this patient yet.</div>')
    html('<div class="group">Allergies</div>')
    allergy_section(patient)
    st.stop()

if pt_open:
    n_crit = sum(v["priority"] == "stat" for v in pt_open)
    owners = ", ".join(sorted({doc_name(v["owner_ref"]) for v in pt_open}))
    msg = (f"{len(pt_open)} abnormal report{'s' if len(pt_open) > 1 else ''} not yet followed up"
           + (f", {n_crit} critical" if n_crit else "") + f". Assigned to {owners}.")
    a, b = st.columns([5, 1], vertical_alignment="center")
    html(f'<div class="note {"crit" if n_crit else "abn"}">{ui.esc(msg)}</div>', a)
    if any(v["owner_ref"] == my_ref for v in pt_open):
        b.button("Go to worklist", on_click=go_worklist, width="stretch")

latest = latest_per_test(df)
attention = latest[latest["flag"].isin(["HH", "LL", "H", "L", "A"])]
attention = attention.assign(_o=attention["flag"].map({"HH": 0, "LL": 0}).fillna(1)).sort_values(["_o", "name"])
html(f'<div class="group">Outside the reference range<small>latest value per test, from any lab, '
     f'in one unit per test</small></div>')
if attention.empty:
    html('<div class="note ok">All latest values are within the reference range.</div>')
else:
    with st.container(border=True, key="card-attn"):
        html(ui.results(attention.to_dict("records"), show_lab=True))

st.write("")
tab1, tab_alg, tab2, tab3, tab4, tab5 = st.tabs(["All results", "Allergies", "Trends", "Before ordering",
                                                 "Follow-up history", "Source data"])

with tab_alg:
    allergy_section(patient)

with tab1:
    with st.container(border=True, key="card-all"):
        html(ui.results(latest.sort_values("name").to_dict("records"), show_lab=True))
    unmapped = latest[~latest["mapped"]]
    if not unmapped.empty:
        st.caption("Not comparable across labs yet, because the lab's own code is not mapped to LOINC: "
                   + ", ".join(f"{r.local_code} from {r.lab}" for r in unmapped.itertuples()) + ".")

with tab2:
    mapped = df[df["mapped"]]
    keys = [k for k in cat.TESTS if k in set(mapped["test"])]
    c1, c2 = st.columns([1, 2])
    key = c1.selectbox("Test", keys, format_func=lambda k: cat.TESTS[k]["name"],
                       index=keys.index("creatinine") if "creatinine" in keys else 0)
    view = c2.radio("Values", ["Converted to one unit", "As reported by each lab"], horizontal=True)
    d = mapped[mapped.test == key].copy()
    converted = view.startswith("Converted")
    d["y"] = d["value"] if converted else d["reported_value"]
    d["Lab"] = d["lab"] if converted else d["lab"] + " (" + d["reported_unit"] + ")"
    d["Shown"] = [ui.fmt_value(v, u) for v, u in zip(d["y"], d["unit"] if converted else d["reported_unit"])]
    lab_colors = alt.Scale(range=[ui.VIOLET, "#E0A12E", "#2F855A", "#3B82C4"])
    x = alt.X("time:T", title=None, axis=alt.Axis(format="%b %Y", labelColor=ui.MUTED, grid=False))
    y = alt.Y("y:Q", title=cat.TESTS[key]["unit"] if converted else "as reported",
              axis=alt.Axis(labelColor=ui.MUTED, titleColor=ui.MUTED, gridColor="#EEF1F6"))
    layers = []
    last = d.iloc[-1]
    if converted and (last["range_low"] is not None or last["range_high"] is not None):
        band = pd.DataFrame({"lo": [last["range_low"] if last["range_low"] is not None else 0],
                             "hi": [last["range_high"] if last["range_high"] is not None else d["y"].max()]})
        layers.append(alt.Chart(band).mark_rect(color="#CDEBD9", opacity=0.6).encode(y="lo:Q", y2="hi:Q"))
    base = alt.Chart(d)
    layers.append(base.mark_line(color="#B8C2D3", strokeWidth=2).encode(x=x, y=y))
    layers.append(base.mark_circle(size=140, opacity=1, stroke="#FFFFFF", strokeWidth=2).encode(
        x=x, y=y, color=alt.Color("Lab:N", scale=lab_colors,
                                  legend=alt.Legend(orient="top", title=None, labelLimit=400, labelFontSize=13)),
        tooltip=[alt.Tooltip("time:T", title="Date", format="%d.%m.%Y"), alt.Tooltip("Lab:N"),
                 alt.Tooltip("Shown:N", title="Value")]))
    chart = alt.layer(*layers).properties(height=320, background="#FFFFFF").configure_view(strokeWidth=0).configure(
        font="Atkinson Hyperlegible, sans-serif")
    with st.container(border=True, key="card-chart"):
        st.altair_chart(chart, width="stretch", theme=None)
        st.caption(f"Green band: reference range. All values in {cat.TESTS[key]['unit']}, LOINC {cat.TESTS[key]['loinc']}."
                   if converted else "Each lab reports in its own unit, so these raw values cannot be compared.")
    hist = pd.DataFrame({
        "Date": d["time"].dt.strftime("%d.%m.%Y"),
        "Lab": d["lab"],
        "Lab's own code": d["local_code"],
        "As reported": [ui.fmt_value(v, u) for v, u in zip(d["reported_value"], d["reported_unit"])],
        "Converted": [ui.fmt_value(v, u) for v, u in zip(d["value"], d["unit"])],
        "Flag": d["flag"].map(ui.FLAG_TEXT).fillna("–"),
    })
    st.dataframe(hist, hide_index=True, width="stretch")

with tab3:
    st.write("See what has already been measured, at any lab, before you order new blood work.")
    wanted = st.multiselect("Tests you plan to order", list(cat.TESTS),
                            default=["hba1c", "creatinine", "cholesterol"],
                            format_func=lambda k: cat.TESTS[k]["name"])
    if st.button("Check", type="primary"):
        for r in duplicate_check(df, wanted):
            kind = "abn" if r["status"] == "duplicate" else "ok"
            verdict = "Already measured recently" if kind == "abn" else "Fine to order"
            html(f'<div class="note {kind}" style="margin-bottom:8px"><b>{ui.esc(r["test"])}</b>'
                 f'<span>{verdict}. {ui.esc(r["message"])}</span></div>')
    st.caption("Minimum retest intervals are demo values, not clinical guidance.")

with tab4:
    if not pt_tasks:
        html('<div class="note ok">No abnormal results have needed follow-up.</div>')
    for v in sorted(pt_tasks, key=lambda v: v["authored"], reverse=True):
        kind = "crit" if v["priority"] == "stat" else "abn"
        with st.container(border=True, key=f"card-hist-{v['id']}"):
            state = "Completed" if v["done"] else ("Overdue" if v["overdue"] else "Open")
            html(f'<div class="card-head"><div class="card-who"><div class="card-name" style="font-size:1.05rem">'
                 f'{ui.esc(v["description"])}</div><div class="card-facts"><span>Assigned to '
                 f'{ui.esc(doc_name(v["owner_ref"]))}</span><span>Created {v["authored"]:%d.%m.%Y %H:%M}</span>'
                 f'</div></div><div class="card-when"><span class="pill '
                 f'{"ok" if v["done"] else ("crit" if v["overdue"] else kind)}">{state}</span></div></div>')
            html(ui.stepper(raw_tasks[v["id"]]["status"]))
            st.caption(" → ".join(f"{n.get('text')} ({n.get('authorString')}, "
                                  f"{pd.to_datetime(n.get('time')):%d.%m. %H:%M})" for n in v["history"]))
    st.caption("Stored as FHIR Task resources: who is responsible, the status, and every step with who and when.")

with tab5:
    def rlabel(r):
        org = orgs.get(r["performer"][0]["reference"].split("/")[-1], {}).get("name", "unknown lab")
        return f"{pd.to_datetime(r['effectiveDateTime']):%d.%m.%Y}, {org}, {len(r.get('result', []))} results"

    rep = st.selectbox("Report", reports, format_func=rlabel)
    a, b = st.columns(2)
    with a:
        html('<div class="group" style="margin-top:8px">Received from the lab (HL7 v2)</div>')
        raw = base64.b64decode(rep["presentedForm"][0]["data"]).decode()
        st.code(raw.replace("\r", "\n"), language=None)
    with b:
        html('<div class="group" style="margin-top:8px">Stored as FHIR</div>')
        slim = {k: v for k, v in rep.items() if k != "presentedForm"}
        st.json(slim, expanded=False)
        first = rep["result"][0]["reference"].split("/")[-1]
        obs = server.read("Observation", first)
        if obs:
            st.caption("First result as a FHIR Observation")
            st.json(obs, expanded=True)
    st.download_button("Download report as FHIR JSON", json.dumps(slim, indent=2),
                       "diagnostic_report.json", "application/fhir+json")
