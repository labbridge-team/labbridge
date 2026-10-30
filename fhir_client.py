"""
Two interchangeable FHIR backends with the same methods:

- RemoteFhir: a real FHIR server over REST (public HAPI test server, or your own).
- LocalFhir:  a JSON file that behaves like a tiny FHIR server (transactions,
              conditional create, reference resolution), so the demo works offline.
"""
import json
import os
import uuid

import requests

from converter import TAG

HAPI_PUBLIC = "https://hapi.fhir.org/baseR4"
HEADERS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}


def _ident(identifier: dict) -> str:
    return f"{identifier['system']}|{identifier['value']}"


class RemoteFhir:
    def __init__(self, base_url: str = HAPI_PUBLIC, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def transaction(self, bundle: dict) -> dict:
        r = requests.post(self.base, json=bundle, headers=HEADERS, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def read(self, rtype: str, rid: str):
        r = requests.get(f"{self.base}/{rtype}/{rid}", headers=HEADERS, timeout=self.timeout)
        return r.json() if r.ok else None

    def _search(self, rtype: str, params: dict) -> list:
        url, out = f"{self.base}/{rtype}", []
        while url:
            r = requests.get(url, params=params, headers=HEADERS, timeout=self.timeout)
            r.raise_for_status()
            b = r.json()
            out += [e["resource"] for e in b.get("entry", []) if e.get("search", {}).get("mode", "match") == "match"]
            url = next((l["url"] for l in b.get("link", []) if l["relation"] == "next"), None)
            params = None
        return out

    def report_exists(self, identifier: dict) -> bool:
        r = requests.get(f"{self.base}/DiagnosticReport",
                         params={"identifier": _ident(identifier), "_summary": "count"},
                         headers=HEADERS, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("total", 0) > 0

    def patients(self) -> list:
        return self._search("Patient", {"_tag": f"{TAG['system']}|{TAG['code']}", "_count": 50})

    def find_patient(self, system: str, value: str):
        found = self._search("Patient", {"identifier": f"{system}|{value}"})
        return found[0] if found else None

    def observations(self, patient_id: str) -> list:
        return self._search("Observation", {"subject": f"Patient/{patient_id}", "_count": 500})

    def reports(self, patient_id: str) -> list:
        return self._search("DiagnosticReport", {"subject": f"Patient/{patient_id}", "_count": 200})

    def organizations(self) -> dict:
        return {o["id"]: o for o in self._search("Organization", {"_tag": f"{TAG['system']}|{TAG['code']}"})}

    def practitioners(self) -> dict:
        return {p["id"]: p for p in self._search("Practitioner", {"_tag": f"{TAG['system']}|{TAG['code']}"})}

    def allergies(self, patient_id: str) -> list:
        return self._search("AllergyIntolerance", {"patient": f"Patient/{patient_id}", "_count": 100})

    def tasks(self, owner_id: str = None, patient_id: str = None) -> list:
        params = {"_tag": f"{TAG['system']}|{TAG['code']}", "_count": 200}
        if owner_id:
            params["owner"] = f"Practitioner/{owner_id}"
        if patient_id:
            params["patient"] = f"Patient/{patient_id}"
        return self._search("Task", params)

    def update(self, resource: dict) -> dict:
        r = requests.put(f"{self.base}/{resource['resourceType']}/{resource['id']}", json=resource,
                         headers=HEADERS, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


class LocalFhir:
    def __init__(self, path: str = "data/local_store.json"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            self._save({})

    def _load(self) -> dict:
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, db: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(db, f)

    def reset(self) -> None:
        self._save({})

    def read(self, rtype: str, rid: str):
        return self._load().get(rtype, {}).get(rid)

    @staticmethod
    def _has_identifier(resource: dict, system: str, value: str) -> bool:
        return any(i.get("system") == system and i.get("value") == value
                   for i in resource.get("identifier", []))

    def _find(self, db, rtype, system, value):
        return next((r for r in db.get(rtype, {}).values() if self._has_identifier(r, system, value)), None)

    def transaction(self, bundle: dict) -> dict:
        db = self._load()
        mapping, created, responses = {}, [], []
        for e in bundle["entry"]:
            res, req = e["resource"], e.get("request", {})
            cond = req.get("ifNoneExist", "")
            if cond.startswith("identifier="):
                system, _, value = cond[len("identifier="):].rpartition("|")
                existing = self._find(db, res["resourceType"], system, value)
                if existing:  # conditional create: reuse what is already there
                    mapping[e["fullUrl"]] = f"{res['resourceType']}/{existing['id']}"
                    responses.append({"response": {"status": "200 OK"}})
                    continue
            res = json.loads(json.dumps(res))
            res["id"] = uuid.uuid4().hex[:16]
            db.setdefault(res["resourceType"], {})[res["id"]] = res
            mapping[e["fullUrl"]] = f"{res['resourceType']}/{res['id']}"
            created.append(res)
            responses.append({"response": {"status": "201 Created"}})
        for res in created:
            _rewrite_refs(res, mapping)
        self._save(db)
        return {"resourceType": "Bundle", "type": "transaction-response", "entry": responses}

    def report_exists(self, identifier: dict) -> bool:
        return self._find(self._load(), "DiagnosticReport", identifier["system"], identifier["value"]) is not None

    def patients(self) -> list:
        return list(self._load().get("Patient", {}).values())

    def find_patient(self, system: str, value: str):
        return self._find(self._load(), "Patient", system, value)

    def _for_patient(self, rtype, patient_id):
        ref = f"Patient/{patient_id}"
        return [r for r in self._load().get(rtype, {}).values() if r.get("subject", {}).get("reference") == ref]

    def observations(self, patient_id: str) -> list:
        return self._for_patient("Observation", patient_id)

    def reports(self, patient_id: str) -> list:
        return self._for_patient("DiagnosticReport", patient_id)

    def organizations(self) -> dict:
        return self._load().get("Organization", {})

    def practitioners(self) -> dict:
        return self._load().get("Practitioner", {})

    def allergies(self, patient_id: str) -> list:
        return [a for a in self._load().get("AllergyIntolerance", {}).values()
                if a.get("patient", {}).get("reference") == f"Patient/{patient_id}"]

    def tasks(self, owner_id: str = None, patient_id: str = None) -> list:
        out = list(self._load().get("Task", {}).values())
        if owner_id:
            out = [t for t in out if t.get("owner", {}).get("reference") == f"Practitioner/{owner_id}"]
        if patient_id:
            out = [t for t in out if t.get("for", {}).get("reference") == f"Patient/{patient_id}"]
        return out

    def update(self, resource: dict) -> dict:
        db = self._load()
        db.setdefault(resource["resourceType"], {})[resource["id"]] = resource
        self._save(db)
        return resource


def _rewrite_refs(node, mapping):
    if isinstance(node, dict):
        if isinstance(node.get("reference"), str) and node["reference"] in mapping:
            node["reference"] = mapping[node["reference"]]
        for v in node.values():
            _rewrite_refs(v, mapping)
    elif isinstance(node, list):
        for v in node:
            _rewrite_refs(v, mapping)
