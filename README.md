# LabBridge

**Every lab result, from every lab, in one standard record, and in front of the right doctor.**
Track 2: Health Data Interoperability · Vienna

> Every lab result in Vienna should be **readable** (any lab, one standard), **visible** (one record
> per e-card), and **acted on** (no abnormal result goes unnoticed).

## The problem

A patient in Vienna gets blood work at her GP (via one lab), then at a hospital (via another lab).
Each lab:
- sends results in its own HL7 v2 dialect, with its **own internal test codes** (`KREA` vs `CREA-E`)
- reports in **different units** (creatinine in mg/dL vs µmol/L, HbA1c in % vs mmol/mol)
- often doesn't know the patient's GP at all

What goes wrong, with evidence:
- **Results arrive after the patient has left.** In a Boston study, 41% of patients were discharged
  before all results were back; doctors were unaware of 65 potentially actionable ones.
- **Abnormal results don't reach the patient.** In 23 US primary care practices, 7.1% of abnormal
  results were not communicated (or not documented as communicated).
- **Tests get repeated.** Austria's Court of Audit (2024) found ELGA's gaps lead to unnecessary
  duplicate examinations. In a US hospital study, ~12% of orders for 17 common tests were duplicates.

## The solution

```
 Labor Alpha (HL7 v2, mg/dL) ─┐                                          ┌─► latest results & trends, all labs
                              ├─► parse ─► map to LOINC ─► FHIR server ─┼─► "already tested?" check
 Labor Beta  (HL7 v2, SI)    ─┘            convert units                 └─► abnormal? → on the GP's worklist
```

| Feature | Problem it solves | FHIR |
|---|---|---|
| **Normalisation**: lab codes → LOINC, one unit per test | Values from different labs can't be compared | `Observation` (LOINC, UCUM) |
| **One record per e-card** | Results scattered across labs | `Patient` with SVNR identifier (HL7 Austria) |
| **Before ordering check** | Duplicate tests | reads `Observation`s |
| **Result routing**: abnormal result goes to the patient's GP, even if the lab doesn't know the GP | Results arriving after discharge get lost | `Patient.generalPractitioner`, `Practitioner` |
| **Worklist**: critical results first, open → acknowledged → patient informed, overdue in red, full audit trail | Abnormal results never acted on | `Task` (owner, status, priority, notes) |
| **Allergies from every system**: hospital and GP send allergies in their own codes; LabBridge merges them into one list, shown on every patient screen and worklist card | Allergies known in one place, missing in another | `AllergyIntolerance` (ATC, SNOMED CT) |
| **Nothing silently dropped**: unknown codes kept and flagged | Silent data loss | local code kept in `Observation.code` |

Routing rule: the patient's GP from the patient record → else the GP named in the lab message
(HL7 `PD1`) → else the doctor who ordered the test (HL7 `OBR-16`). Results older than 30 days are
imported as history without creating new tasks.

Allergies arrive in HL7 v2 `AL1` segments (in patient update messages, `ADT^A08`). Each system's own
code is mapped to a standard one (medicines: WHO ATC; other substances and "no known allergy":
SNOMED CT). The same substance from two systems is stored once. The app separates three states,
because they mean different things for safety: **allergies on file**, **no known allergies**
(confirmed), and **allergies not recorded** (nobody has asked yet).

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

### Using the app

- **Sidebar, top:** who is signed in, and **Go to: Worklist / Patient lookup**.
- **Sidebar, Data sources and demo** (collapsed, so it stays out of a doctor's way): FHIR server choice,
  HL7 file import, **Load demo data**, **Simulate late hospital result**, **Reset local data**.
- **Red bar at the top:** appears on every screen when the signed-in doctor has unreviewed critical
  results, with a **Review now** button.
- **Worklist:** critical results first, then other abnormal results; each card shows the patient, the
  values with reference ranges, when it arrived, who ordered it, and the next action.
- **Patient lookup:** search by e-card number or pick a patient. The allergy strip, open follow-ups and
  all out-of-range values are shown first; details are in the tabs below
  (All results, Allergies, Trends, Before ordering, Follow-up history, Source data).
- **Allergies tab:** details of each allergy (reaction, since when, which system reported it), a form
  to record a new one, **Record: no known allergies**, and **Remove, entered in error**.

Demo patients (fake, checksum-valid SVNRs): **Anna Demo 1235120458**, **Max Muster 4562030971**.
Demo doctors: Dr. Maria Huber (Anna's GP), Dr. Peter Novak (Max's GP), Dr. Stefan Berger (hospital).
Anna's allergies come from the hospital (penicillin, iodinated contrast media) and her GP's practice
(penicillin again, ibuprofen intolerance). Max has no allergy information yet.
`python demo_data.py` regenerates the files in `sample_data/` with fresh dates.

Start in **Local (offline)** mode. Switch to **HAPI public test server** to show it on a real FHIR
server. That server is public: fake patients only. Test it once on your laptop before the event.

## Demo script (4–5 minutes)

1. **The problem** (30 s): "In Boston, 41% of patients left hospital before all their results were back."
   Open `labor_beta.hl7` in a text editor: "This is what labs send today."
2. **Import**: Data sources and demo → **Load demo data**. Dr. Huber's worklist shows one overdue
   report: abnormal results from two weeks ago that nobody has followed up.
3. **Readable**: **Open patient record** → Trends → Creatinine → **"As reported by each lab"**: ~1 vs ~120,
   meaningless. Switch to **"Converted to one unit"**: a steady rise. "Her kidneys are getting worse;
   no single lab could show you that."
4. **Visible**: **Before ordering** → HbA1c and cholesterol were done two weeks ago at another lab. "One needle saved."
5. **Acted on**: "Anna went home yesterday. Her last hospital blood test comes back this morning."
   Click **Simulate late hospital result**: the red bar appears at once. **Review now** → critical
   potassium at the top of the worklist. "The hospital lab didn't even know who her GP is. LabBridge did."
   Point at the allergy strip on the card: "Before she calls Anna about new medication, she sees the
   penicillin allergy the hospital recorded, even though it never reached her practice software."
   **Acknowledge result** → **Mark patient informed** → the red bar disappears; show the audit trail in
   the patient's Follow-up history.
6. **Allergies**: open Max's record: "Allergies not recorded" in amber. Record **no known allergies**:
   it turns green, with who confirmed it and when.
7. **The standard**: Source data tab, HL7 v2 left, FHIR right: "Any FHIR system can read this."

## Why it's relevant (for the pitch and Q&A)

- Austria now **requires lab results to be stored in ELGA**: office-based doctors since July 2025,
  hospitals since January 2026. In 2024 the Court of Audit noted ELGA's gaps cause duplicate examinations.
- ELGA is the **archive** of documents (currently HL7 CDA). LabBridge works on the **values** and the
  **workflow**: comparable across labs, checked at order time, and assigned to a responsible doctor.
- The **European Health Data Space** requires standardised exchange across EU countries by 2029,
  and FHIR is the direction Austria and the EU are moving in.
- Allergies are one of the core sections of the **European Patient Summary**, the first data set
  the EHDS requires countries to exchange. LabBridge shows them next to every lab result.
- Most labs and practice systems still speak **HL7 v2** today. LabBridge accepts the world as it is
  and outputs the standard the world is moving to.

**Expected judge questions:**
- *"ELGA already has lab reports. Why this?"* ELGA stores documents; it doesn't tell a GP "this result
  needs your attention", or warn before a duplicate order. LabBridge could read ELGA as another input.
- *"HL7-to-FHIR converters already exist."* Yes, and you'd use them in production. The value here is
  what happens after conversion: normalisation, routing and follow-up.
- *"Won't doctors get alert fatigue?"* One task per report, not per value; only recent results; and
  priorities (critical first). Thresholds would be tuned with clinicians.
- *"Privacy?"* Synthetic data only. In production: access via ELGA / e-card infrastructure,
  patient consent, audit logs (the follow-up history already records who did what, when).
- *"Are the rules clinically right?"* Retest intervals and overdue limits are illustrative; real ones
  would come from lab medicine guidelines. The system informs; it never blocks a doctor.

## Split the work (2 people)

| Person A: data & standards | Person B: dashboard & pitch |
|---|---|
| `hl7v2.py`, `converter.py`, `lab_catalog.py` | `app.py`, demo script, slides |
| Add a third lab with a new dialect | Polish the worklist, German labels |
| Get HAPI mode working on venue Wi-Fi | Record a backup demo video |

Both should be able to explain: HL7 v2 segments (MSH, PID, PD1, OBR, OBX, AL1), what LOINC, UCUM,
ATC and SNOMED CT are, and the FHIR resources used (Patient, Practitioner, Organization,
ServiceRequest, DiagnosticReport, Observation, Task, AllergyIntolerance).

## 24-hour plan

| Time | Goal |
|---|---|
| 0–1 h | Check the rules on pre-built code. Run it together, walk through one HL7 message line by line |
| 1–5 h | Pick ONE stretch goal; Person B adapts UI to the organisers' theme or data |
| 5–12 h | Build the stretch goal; start slides (problem → live demo → relevance → next steps) |
| 12–16 h | Sleep in shifts |
| 16–19 h | Bug fixes, **feature freeze at hour 19**, record backup video |
| 19–24 h | Rehearse the 4-minute demo at least 3 times, prepare Q&A answers |

## Stretch goals (pick one)

1. **Mapping helper**: for unmapped codes, suggest a LOINC match from the test name and let the
   doctor confirm. Directly addresses the Vitamin D warning in the demo.
2. **Patient view**: a simple page where Anna sees her own results and whether her doctor has
   reviewed them ("Your GP has seen this result").
3. **Third lab with a new dialect**, e.g. one that already sends LOINC codes (`^LN`).
4. **Doctor's order flow**: create a FHIR `ServiceRequest` only after the duplicate check passes.
5. **German UI**.

## Files

| File | Purpose |
|---|---|
| `hl7v2.py` | HL7 v2 parser (and writer, for demo data) |
| `lab_catalog.py` | LOINC mapping, unit conversion, SVNR checksum, retest intervals |
| `allergy_catalog.py` | Allergy substances with ATC / SNOMED CT codes, each system's own allergy codes |
| `converter.py` | HL7 v2 → FHIR transaction Bundle; routing; follow-up tasks; task workflow |
| `fhir_client.py` | FHIR REST client + offline local store |
| `analysis.py` | Tables, latest values, duplicate-order check, overdue rules |
| `demo_data.py` | Fake lab messages and allergy messages, incl. the late-result scenario |
| `app.py` | Streamlit dashboard: worklist + patient lookup |
| `ui.py` | Visual building blocks: range gauges, follow-up progress, avatars, styles |
| `.streamlit/config.toml` | Colours and font of the app |

## Design choices (good to mention in the pitch)

- **Typeface: Atkinson Hyperlegible**, made by the Braille Institute so characters that are easy to
  confuse (1 l I, 0 O, 5 S) look clearly different. Misreading a lab value is a real risk.
- **Colour has one meaning each:** red only for safety-critical information (critical results and
  high-risk allergies, like a hospital allergy wristband), amber for abnormal, green for normal,
  violet (the cap colour of blood-count tubes) for the app itself.
- **Range gauge for every value:** the green band is the reference range, the dot is the patient.
  A doctor sees how far out of range a value is without reading numbers.
- **Urgent first:** the worklist opens with critical results, and a red bar stays on every screen
  until a critical result is acknowledged.
- The font loads from Google Fonts, so it needs internet; offline, the app falls back to a system font.

All patients, doctors, labs and values are fictional. Reference ranges, retest intervals and overdue
limits are illustrative, not clinical guidance.
