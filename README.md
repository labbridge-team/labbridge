# LabBridge

**Every lab result, from every lab, in one standard record, and in front of the right doctor.**
Track 2: Health Data Interoperability · Vienna

For the full reasoning behind every design choice, see [DECISIONS.md](DECISIONS.md).

![LabBridge worklist: a critical result at the top, routed to the patient's GP](docs/screenshots/1-worklist.png)

![LabBridge patient record: allergies and out-of-range values from every lab](docs/screenshots/2-patient-record.png)

More screenshots, with explanations, are in [DECISIONS.md](DECISIONS.md#what-it-looks-like).

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

## Why it matters

- Austria now **requires lab results to be stored in ELGA**: office-based doctors since July 2025,
  hospitals since January 2026. In 2024 the Court of Audit noted ELGA's gaps cause duplicate examinations.
- ELGA is the **archive** of documents (currently HL7 CDA). LabBridge works on the **values** and the
  **workflow**: comparable across labs, checked at order time, and assigned to a responsible doctor.
  ELGA could become one more input.
- The **European Health Data Space** requires standardised exchange across EU countries by 2029,
  and FHIR is the direction Austria and the EU are moving in.
- Allergies are one of the core sections of the **European Patient Summary**, the first data set
  the EHDS requires countries to exchange. LabBridge shows them next to every lab result.
- Most labs and practice systems still speak **HL7 v2** today. LabBridge accepts the world as it is
  and outputs the standard the world is moving to.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser. Click **Load demo data** to start.

### Using the app

- **Sidebar, top:** who is signed in, and **Go to: Worklist / Patient lookup**.
- **Sidebar, Data sources and demo** (collapsed, so it stays out of a doctor's way): FHIR server choice,
  HL7 file import, **Load demo data**, **Simulate late hospital result**, **Reset local data**.
- **Red bar at the top:** appears on every screen when the signed-in doctor has unreviewed critical
  results, with a **Review now** button.
- **Worklist:** critical results first, then other abnormal results; each card shows the patient, their
  allergies, the values with reference ranges, when it arrived, who ordered it, and the next action.
- **Patient lookup:** search by e-card number or pick a patient. The allergy strip, open follow-ups and
  all out-of-range values are shown first; details are in the tabs below
  (All results, Allergies, Trends, Before ordering, Follow-up history, Source data).
- **Allergies tab:** details of each allergy (reaction, since when, which system reported it), a form
  to record a new one, **Record: no known allergies**, and **Remove, entered in error**.

### A short tour

1. **Load demo data.** Dr. Huber's worklist shows one overdue report: abnormal results from two weeks
   ago that nobody has followed up.
2. **Open patient record → Trends → Creatinine.** Switch between **As reported by each lab** (values
   seem to jump from about 1 to about 120) and **Converted to one unit** (a steady rise across both labs).
3. **Before ordering.** HbA1c and cholesterol were measured two weeks ago, at another lab.
4. **Data sources and demo → Simulate late hospital result.** A critical potassium result arrives after
   the patient has left hospital. The red bar appears; **Review now** shows it at the top of her GP's
   worklist, with her allergies on the card. **Acknowledge result**, then **Mark patient informed**.
5. **Search 4562030971 (Max Muster).** His allergies are not recorded. **Allergies → Record: no known
   allergies** changes the strip to green, with who confirmed it and when.
6. **Source data.** The original HL7 v2 message next to the FHIR record LabBridge stored.

### Demo data

All patients, doctors, labs, hospitals and values are fictional, generated by `demo_data.py`
(`python demo_data.py` rewrites `sample_data/` with fresh dates).

- Patients (checksum-valid but fake SVNRs): **Anna Demo 1235120458**, **Max Muster 4562030971**.
- Doctors: Dr. Maria Huber (Anna's GP), Dr. Peter Novak (Max's GP), Dr. Stefan Berger (hospital).
- Anna's allergies come from the hospital (penicillin, iodinated contrast media) and her GP's practice
  (penicillin again, ibuprofen intolerance). Max has no allergy information.

The app runs on a local offline store by default. Under **Data sources and demo** it can also use the
public **HAPI FHIR test server** or any FHIR server URL. The public server is visible to everyone, so
use fake patients only.

## Design choices

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

## Files

| File | Purpose |
|---|---|
| `hl7v2.py` | HL7 v2 parser (and writer, for demo data) |
| `lab_catalog.py` | LOINC mapping, unit conversion, SVNR checksum, retest intervals |
| `allergy_catalog.py` | Allergy substances with ATC / SNOMED CT codes, each system's own allergy codes |
| `converter.py` | HL7 v2 → FHIR transaction Bundle; routing; follow-up tasks; task workflow; allergies |
| `fhir_client.py` | FHIR REST client + offline local store |
| `analysis.py` | Tables, latest values, duplicate-order check, overdue rules |
| `demo_data.py` | Fake lab messages and allergy messages, incl. the late-result scenario |
| `app.py` | Streamlit dashboard: worklist + patient lookup |
| `ui.py` | Visual building blocks: range gauges, follow-up progress, allergy strip, styles |
| `.streamlit/config.toml` | Colours and font of the app |
| `DECISIONS.md` | Design report: why LabBridge exists, how it works, every decision and its alternatives |

## Limitations and next steps

LabBridge is a prototype, not ready for real patients: it has no login, access control or consent
management, reads only HL7 v2, and uses small hand-written mapping tables. Reference ranges, retest
intervals and overdue limits are illustrative, not clinical guidance. See
[DECISIONS.md](DECISIONS.md#5-limitations) for the full list and the planned next steps.
