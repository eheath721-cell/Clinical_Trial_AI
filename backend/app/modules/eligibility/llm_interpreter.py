"""LLM fallback for eligibility criteria the deterministic recognizers cannot parse.

Only public registry text is sent (never patient data). The model maps the criterion onto the
same structured requirement vocabulary the rules use; output is then validated so the LLM
cannot introduce thresholds, units or concepts that are not grounded in the criterion text.
If validation fails the criterion stays "needs review".
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.clinical.vocab import ANALYTES, CONCEPTS, analyte_index, concept_index, normalize_unit
from app.modules.agents.llm import get_llm


class Threshold(BaseModel):
    op: Literal[">=", ">", "<=", "<"]
    value: float
    unit: str | None


class Atomic(BaseModel):
    type: Literal["condition", "medication", "lab", "age", "vague"]
    concept: str | None = Field(None, description="Vocabulary code for condition/medication")
    analyte: str | None = Field(None, description="Analyte code for lab requirements")
    negated: bool = False
    mode: Literal["current", "ever", "within_window"] | None = None
    window_days: int | None = None
    thresholds: list[Threshold] = Field(default_factory=list)
    min_age: int | None = None
    max_age: int | None = None
    reason: str | None = Field(None, description="For vague items: the phrase defined only in the protocol")


class Interpretation(BaseModel):
    interpretable: bool
    combine: Literal["all", "any"]
    items: list[Atomic]


def _system_prompt() -> str:
    concepts = ", ".join(f"{c.code} ({c.label})" for c in CONCEPTS)
    analytes = ", ".join(f"{a.code} ({a.label}; units {', '.join(a.units)})" for a in ANALYTES)
    return (
        "You convert one clinical-trial eligibility criterion into structured requirements.\n"
        "Rules: use only concept codes and analyte codes from the lists below; copy numeric thresholds and units "
        "exactly as written in the criterion; never invent a threshold, unit, time window or concept; if part of the "
        "criterion depends on protocol definitions or investigator judgment, emit a 'vague' item quoting that phrase; "
        "if you cannot represent the criterion faithfully, set interpretable=false.\n"
        "A requirement is a statement about the participant (for exclusion criteria, the statement that would "
        "exclude them).\n"
        f"Concepts: {concepts}\nAnalytes: {analytes}"
    )


def _numbers(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)}


def validate(interp: Interpretation, text: str) -> dict | None:
    if not interp.interpretable or not interp.items:
        return None
    nums = _numbers(text)
    low = text.lower()
    items: list[dict] = []
    for it in interp.items:
        if it.type == "condition" or it.type == "medication":
            if not it.concept or it.concept not in concept_index():
                return None
            d = {"type": it.type, "concept": it.concept, "negated": it.negated}
            if it.type == "medication":
                d["mode"] = it.mode or "ever"
            if it.window_days:
                if not (nums & {float(it.window_days), it.window_days / 7, it.window_days / 30, it.window_days / 365}):
                    return None
                d["window_days"] = it.window_days
            items.append(d)
        elif it.type == "lab":
            if not it.analyte or it.analyte not in analyte_index() or not it.thresholds:
                return None
            ths = []
            for th in it.thresholds:
                if th.value not in nums:
                    return None  # threshold not printed in the criterion
                unit = normalize_unit(th.unit) if th.unit else None
                if unit and unit.lower().replace(" ", "") not in low.replace(" ", "") and th.unit.lower() not in low:
                    return None
                ths.append({"op": th.op, "value": th.value, "unit": unit})
            items.append({"type": "lab", "analyte": it.analyte, "thresholds": ths, "combine": "all"})
        elif it.type == "age":
            for v in (it.min_age, it.max_age):
                if v is not None and float(v) not in nums:
                    return None
            items.append({"type": "age", **({"min": it.min_age} if it.min_age else {}),
                          **({"max": it.max_age} if it.max_age else {})})
        elif it.type == "vague":
            items.append({"type": "vague", "reason": (it.reason or "protocol-defined requirement")[:120]})
    if len(items) == 1:
        return {**items[0], "interpreted_by": "llm"}
    return {"type": interp.combine, "items": items, "interpreted_by": "llm"}


def interpret_criterion(text: str, kind: str) -> dict | None:
    llm = get_llm()
    if not llm.available:
        return None
    result = llm.parse(system=_system_prompt(), user=f"{kind.upper()} criterion:\n{text}", schema=Interpretation,
                       max_tokens=4000, effort="low")
    return validate(result, text) if result else None
