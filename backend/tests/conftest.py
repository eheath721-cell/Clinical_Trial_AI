from __future__ import annotations

import os
import tempfile
from datetime import date

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["TRIAL_SOURCE"] = "snapshot"
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ["DOCUMENT_STORAGE_DIR"] = tempfile.mkdtemp(prefix="tc-docs-")
os.environ["LLM_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401  (register tables before create_all)
from app.core import db as dbmod  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.modules.eligibility.patient import (  # noqa: E402
    ConditionFact,
    FactRef,
    LabFact,
    MedFact,
    PatientFacts,
)

AS_OF = date(2026, 11, 2)


@pytest.fixture()
def client():
    engine = dbmod.configure_engine(os.environ["DATABASE_URL"])
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    from app.main import create_app
    from app.modules.accounts import router as accounts_router

    accounts_router._attempts.clear()
    with TestClient(create_app()) as c:
        yield c
    Base.metadata.drop_all(engine)


class Session:
    def __init__(self, client: TestClient):
        self.c = client

    def _h(self):
        return {"x-csrf-token": self.c.cookies.get("tc_csrf", "")}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(), **kw)

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self._h())

    def delete(self, url):
        return self.c.delete(url, headers=self._h())


def register(client: TestClient, email="patient@example.com", password="correct horse battery") -> Session:
    r = client.post("/api/auth/register", json={"email": email, "password": password, "accept_terms": True,
                                               "accept_privacy": True, "accept_health_data": True})
    assert r.status_code == 201, r.text
    return Session(client)


@pytest.fixture()
def user(client) -> Session:
    return register(client)


# ----------------------------------------------------------------------------- synthetic patient builders


def ref(kind: str, label: str, prov="patient_reported", fid=None) -> FactRef:
    return FactRef(kind, fid or label, label, prov)


def facts(age=24, sex="unknown", labs=(), conditions=(), meds=()) -> PatientFacts:
    f = PatientFacts(as_of=AS_OF, age_years=age, age_basis="date_of_birth" if age is not None else None,
                     age_ref=ref("demographic", f"Age {age}") if age is not None else None, sex=sex)
    for analyte, value, unit, collected, *rest in labs:
        ref_high = rest[0] if rest else None
        f.labs.append(LabFact(analyte, analyte, value, None, unit, None, ref_high, collected,
                              ref("lab", f"{analyte} {value:g} {unit}")))
    for concept, assertion, *rest in conditions:
        onset = rest[0] if rest else None
        quals = rest[1] if len(rest) > 1 else {}
        prov = rest[2] if len(rest) > 2 else "patient_reported"
        f.conditions.append(ConditionFact(concept, concept, assertion, onset, quals,
                                          ref("condition", f"{concept}: {assertion} ({prov})", prov)))
    for concept, status, *rest in meds:
        started = rest[0] if rest else None
        stopped = rest[1] if len(rest) > 1 else None
        f.meds.append(MedFact(concept, concept, status, started, stopped, ref("medication", f"{concept}: {status}")))
    return f


def demo_patient() -> PatientFacts:
    """The synthetic patient from the product brief."""
    return facts(age=24, labs=[("lpa", 185.0, "nmol/L", None)],
                 conditions=[("mi", "absent"), ("cad", "absent")], meds=[("lipid_lowering", "not_current")])
