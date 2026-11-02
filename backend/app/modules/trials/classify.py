"""Deterministic study-category classification.

Distinguishes, from the registry's own fields, between e.g. biomarker-lowering studies
(primary outcome = % change in Lp(a)) and cardiovascular outcome trials (primary outcome =
major cardiovascular events), which usually require established disease or high risk."""

from __future__ import annotations

import re

from app.modules.trials.records import TrialRecord

_OUTCOME_EVENT = re.compile(
    r"major adverse cardiovascular|mace|time to (first )?(occurrence of )?(chd death|cardiovascular death|"
    r"myocardial infarction)|major cardiovascular events|cardiovascular events", re.I)
_OUTCOME_IMAGING = re.compile(r"plaque|\bncp\b|non-?calcified|ccta|computed tomography angiography|ivus|aortic valve|calcium score|"
                              r"peak aortic jet velocity", re.I)
_OUTCOME_BIOMARKER = re.compile(r"(percent|percentage|relative|absolute)?\s*change.*(lp\(a\)|lipoprotein|ldl|"
                                r"apob|cholesterol|triglyceride)", re.I)
_OUTCOME_SAFETY = re.compile(r"adverse events|safety|tolerability|pharmacokinetic|cmax|auc", re.I)

CATEGORIES = {
    "cv_outcomes": {
        "label": "Cardiovascular outcomes trial",
        "explanation": ("Measures whether the treatment reduces heart attacks, strokes or other cardiovascular "
                        "events. These trials are large and typically enroll people with established "
                        "cardiovascular disease or specific risk factors, as stated in their criteria."),
    },
    "imaging": {
        "label": "Imaging study",
        "explanation": "Measures changes on heart or artery imaging (for example plaque on a CT scan).",
    },
    "biomarker": {
        "label": "Biomarker-lowering study",
        "explanation": "Measures how much the treatment lowers a blood marker such as Lp(a) or LDL cholesterol.",
    },
    "early_safety": {
        "label": "Early-phase safety study",
        "explanation": "First-in-human or early-phase study focused on safety, dosing and how the drug is processed.",
    },
    "observational": {
        "label": "Observational study / registry",
        "explanation": "No study treatment is given; researchers collect health information over time.",
    },
    "other": {"label": "Interventional study", "explanation": "Tests a treatment or intervention."},
}


def classify_study(r: TrialRecord) -> dict:
    primary = " ".join(o.measure + " " + (o.description or "") for o in r.primary_outcomes)
    title = f"{r.brief_title} {r.official_title or ''}"
    if (r.study_type or "").upper() == "OBSERVATIONAL":
        code = "observational"
    elif _OUTCOME_EVENT.search(primary) or re.search(r"major (adverse )?cardiovascular events", title, re.I):
        code = "cv_outcomes"
    elif _OUTCOME_IMAGING.search(primary):
        code = "imaging"
    elif _OUTCOME_BIOMARKER.search(primary):
        code = "biomarker"
    elif ("PHASE1" in r.phases or "EARLY_PHASE1" in r.phases) and _OUTCOME_SAFETY.search(primary):
        code = "early_safety"
    else:
        code = "other"
    out = {"code": code, **CATEGORIES[code], "basis": "primary outcome measures listed in the registry"}
    return out
