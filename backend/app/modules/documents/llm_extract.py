"""Optional LLM extraction pass (gated by `phi_allowed`). Output is validated: every fact must
quote an excerpt that appears verbatim in the document and every number must appear in that
excerpt. Validated facts are still only *candidates* for user review."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from app.clinical.vocab import analyte_index, concept_index, normalize_unit
from app.modules.agents.llm import get_llm
from app.modules.documents.extraction import Candidate


class LLMFact(BaseModel):
    fact_type: Literal["lab", "condition", "medication", "procedure"]
    code: str | None
    name: str
    value: float | None = None
    unit: str | None = None
    status: Literal["present", "absent", "current", "past", "not_current"] | None = None
    date: str | None = None
    page: int
    excerpt: str


class LLMFacts(BaseModel):
    facts: list[LLMFact]


SYSTEM = (
    "Extract clinical facts about the PATIENT from the document. Ignore family history and facts about other people. "
    "Quote the exact supporting excerpt (verbatim, from a single page). Keep units exactly as written. Do not infer "
    "diagnoses from lab values. Mark negated findings ('no history of X') as status 'absent'. Only use codes from: "
    "{codes}. Use code null when nothing fits."
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def llm_candidates(pages: list[str]) -> list[Candidate]:
    llm = get_llm()
    if not llm.available:
        return []
    codes = ", ".join(sorted(list(concept_index()) + list(analyte_index())))
    doc = "\n\n".join(f"--- page {i} ---\n{p}" for i, p in enumerate(pages, start=1))
    result = llm.parse(system=SYSTEM.format(codes=codes), user=doc, schema=LLMFacts, max_tokens=8000)
    if result is None:
        return []
    out: list[Candidate] = []
    for f in result.facts:
        if not (1 <= f.page <= len(pages)) or _norm(f.excerpt) not in _norm(pages[f.page - 1]):
            continue  # excerpt not found verbatim -> discard
        if f.value is not None and not re.search(rf"(?<!\d){re.escape(f'{f.value:g}')}(?!\d)", f.excerpt):
            continue
        if f.fact_type == "lab":
            if f.code not in analyte_index() or f.value is None:
                continue
            payload = {"analyte": f.code, "display_name": analyte_index()[f.code].label, "value_numeric": f.value,
                       "unit": normalize_unit(f.unit) if f.unit else None, "reference_low": None,
                       "reference_high": None, "reference_text": None, "collected_on": f.date, "value_text": None,
                       "flag": None}
        elif f.fact_type in ("condition", "procedure"):
            if f.code and f.code not in concept_index():
                continue
            payload = {"concept": f.code, "name": f.name, "assertion": "absent" if f.status == "absent" else "present",
                       ("performed_on" if f.fact_type == "procedure" else "onset_date"): f.date}
        else:
            if f.code and f.code not in concept_index():
                continue
            payload = {"concept": f.code, "name": f.name, "status": f.status if f.status in ("current", "past",
                                                                                              "not_current") else "current",
                       "dose": None}
        out.append(Candidate(f.fact_type, payload, f.page, f.excerpt, method="llm", confidence=0.6,
                             warnings=["Found by AI extraction; verify against the original document."]))
    return out
