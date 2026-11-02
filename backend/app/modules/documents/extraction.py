"""Clinical fact extraction from uploaded documents.

Pipeline: PDF/text -> per-page text -> deterministic recognizers (labs with units, reference
ranges and collection dates; medications; diagnoses with negation; procedures; genetic
results) -> optional LLM pass (gated, validated) -> candidate facts for USER REVIEW.

Extraction never writes to the patient's profile directly. Every candidate keeps the page
and verbatim excerpt it came from.

Safety rules implemented here:
  * Family-history mentions ("father had an MI at 52") are never attributed to the patient.
  * Negated mentions ("no history of CAD", "denies chest pain") become explicit ABSENT facts.
  * Units are preserved exactly; no conversion happens at extraction time.
  * A collection date is only attached if found in the document; otherwise it is left empty
    and flagged, never assumed.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.clinical.vocab import (
    UNIT_REGEX,
    analyte_index,
    find_analytes,
    find_concepts,
    get_concept,
    normalize_unit,
)

EXTRACTOR_VERSION = "rules-1.0"


@dataclass
class Candidate:
    fact_type: str  # lab | condition | medication | procedure | biomarker
    payload: dict
    page: int
    excerpt: str
    method: str = "rules"
    confidence: float = 0.8
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    pages: list[str]
    candidates: list[Candidate]
    status: str  # extracted | no_text | failed
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.pages)


# ----------------------------------------------------------------------------- text


def pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return [(page.extract_text() or "") for page in reader.pages]


def document_pages(data: bytes, content_type: str) -> list[str]:
    if content_type == "application/pdf" or data[:5] == b"%PDF-":
        return pdf_pages(data)
    return [data.decode("utf-8", errors="replace")]


# ----------------------------------------------------------------------------- dates

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),
    (re.compile(rf"\b({_MONTHS})[a-z]*\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I), "mon"),
]
_COLLECTED_RE = re.compile(r"(collected|collection date|date collected|specimen collected|date of service|"
                           r"drawn|result date|reported)\s*:?\s*", re.I)


def parse_date(text: str) -> date | None:
    for rx, kind in _DATE_RES:
        m = rx.search(text)
        if not m:
            continue
        try:
            if kind == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if kind == "mdy":
                return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
        except ValueError:
            continue
    return None


def collection_date(pages: list[str]) -> tuple[date | None, str | None]:
    for page in pages:
        for line in page.splitlines():
            m = _COLLECTED_RE.search(line)
            if m:
                d = parse_date(line[m.end():])
                if d:
                    return d, line.strip()
    return None, None


# ----------------------------------------------------------------------------- labs

_VALUE_RE = re.compile(rf"(?P<cmp>[<>]=?)?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_REGEX})?", re.I)
_REF_RANGE_RE = re.compile(r"(?P<lo>\d+(?:\.\d+)?)\s*[-–]\s*(?P<hi>\d+(?:\.\d+)?)")
_REF_BOUND_RE = re.compile(r"(?P<op>[<>]|≤|≥|<=|>=)\s*(?P<v>\d+(?:\.\d+)?)")


def _labs_from_line(line: str, page_no: int, doc_date: date | None) -> list[Candidate]:
    out: list[Candidate] = []
    mentions = find_analytes(line)
    for idx, m in enumerate(mentions):
        end = mentions[idx + 1].start if idx + 1 < len(mentions) else len(line)
        rest = line[m.end:end]
        rest = re.sub(r"^\s*\(\s*[a-z]\s*\)", "", rest, flags=re.I)  # "Lipoprotein (a)" artefacts
        vm = _VALUE_RE.search(rest)
        if not vm or vm.start() > 40:
            continue
        a = analyte_index()[m.code]
        unit = normalize_unit(vm.group("unit")) if vm.group("unit") else None
        after = rest[vm.end():]
        flag = None
        fm = re.match(r"\s*\b(H|L|HIGH|LOW|A|ABNORMAL)\b", after, re.I)
        if fm:
            flag = fm.group(1).upper()[0]
            after = after[fm.end():]
        ref_low = ref_high = None
        ref_text = None
        rr = _REF_RANGE_RE.search(after)
        rb = _REF_BOUND_RE.search(after)
        if rr and (not rb or rr.start() <= rb.start()):
            ref_low, ref_high = float(rr.group("lo")), float(rr.group("hi"))
            ref_text = rr.group(0)
        elif rb:
            v = float(rb.group("v"))
            if rb.group("op") in ("<", "≤", "<="):
                ref_high = v
            else:
                ref_low = v
            ref_text = rb.group(0)
        warnings = []
        if unit is None:
            warnings.append("No unit found next to the value; please check the original report.")
        elif unit not in a.units:
            warnings.append(f"Unit '{unit}' is unusual for {a.label}; please check the original report.")
        if doc_date is None:
            warnings.append("No collection date found in the document; please add it.")
        if vm.group("cmp"):
            warnings.append(f"Value reported as '{vm.group('cmp')}{vm.group('val')}' (a bound, not an exact value).")
        out.append(Candidate(
            fact_type="lab",
            payload={
                "analyte": m.code, "display_name": a.label, "value_numeric": float(vm.group("val")),
                "value_text": f"{vm.group('cmp')}{vm.group('val')}" if vm.group("cmp") else None,
                "unit": unit, "reference_low": ref_low, "reference_high": ref_high, "reference_text": ref_text,
                "collected_on": doc_date.isoformat() if doc_date else None, "flag": flag,
            },
            page=page_no, excerpt=line.strip(), confidence=0.9 if unit and doc_date else 0.7, warnings=warnings))
    return out


# ----------------------------------------------------------------------------- concepts

_FAMILY_RE = re.compile(r"family history|\bfather\b|\bmother\b|\bbrother\b|\bsister\b|\bsibling|\bparent|"
                        r"grand(father|mother|parent)|\buncle\b|\baunt\b|\bcousin\b|\bson\b|\bdaughter\b|\bFHx\b", re.I)
_NEG_RE = re.compile(r"(\bno\b|\bdenies\b|\bdenied\b|negative for|\bwithout\b|no history of|no known|ruled out|"
                     r"\bnot\b|\bnever\b|free of|absence of)[^.;:]*$", re.I)
_PAST_RE = re.compile(r"discontinued|stopped|previously (took|on)|history of (taking|use)|\bformerly\b|\bpast\b", re.I)
_DOSE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(mg|mcg|g|units?)\b(\s*(daily|once daily|twice daily|bid|qd|qhs|weekly|"
                      r"every \d+ weeks))?", re.I)
_SECTION_RE = re.compile(r"^\s*(family history|social history|past medical history|medical history|medications?|"
                         r"current medications|allergies|assessment|plan|impression|diagnos[ie]s|problem list|"
                         r"history of present illness|hpi|procedures|surgical history|results|labs?)\s*:?", re.I)
_RS_RE = re.compile(r"\b(rs\d{4,})\b[^.\n]{0,60}?\b(detected|not detected|positive|negative|carrier|heterozygous|"
                    r"homozygous|present|absent)\b", re.I)
_GENE_RE = re.compile(r"\b(LPA|LDLR|APOB|PCSK9)\b[^.\n]{0,60}?\b(pathogenic|likely pathogenic|benign|variant of "
                      r"uncertain significance|vus|no pathogenic variant|negative|positive)\b", re.I)


def _sentences(line: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", line) if s.strip()]


def extract_candidates(pages: list[str]) -> ExtractionResult:
    doc_date, _date_line = collection_date(pages)
    candidates: list[Candidate] = []
    notes: list[str] = []
    seen: set[tuple] = set()
    for page_no, page in enumerate(pages, start=1):
        section = None
        for raw in page.splitlines():
            line = raw.strip()
            if not line:
                continue
            sm = _SECTION_RE.match(line)
            if sm:
                section = sm.group(1).lower()
            # labs
            for c in _labs_from_line(line, page_no, doc_date):
                key = ("lab", c.payload["analyte"], c.payload["value_numeric"], c.payload["unit"])
                if key not in seen:
                    seen.add(key)
                    candidates.append(c)
            if find_analytes(line) and _VALUE_RE.search(line):
                continue  # lab rows don't carry diagnoses
            # genetics
            for gm in list(_RS_RE.finditer(line)) + list(_GENE_RE.finditer(line)):
                key = ("bio", gm.group(1).upper(), gm.group(2).lower())
                if key not in seen:
                    seen.add(key)
                    candidates.append(Candidate("biomarker", {"name": gm.group(1), "result": gm.group(2),
                                                              "interpretation": None, "concept": None},
                                                page_no, line, confidence=0.75,
                                                warnings=["Genetic results should be confirmed with your clinician."]))
            for sent in _sentences(line):
                family = section == "family history" or bool(_FAMILY_RE.search(sent))
                for m in find_concepts(sent):
                    concept = get_concept(m.code)
                    if concept is None or concept.kind == "trait":
                        continue
                    if family:
                        note = f"Skipped a family-history mention of {concept.label.lower()} (page {page_no})."
                        if note not in notes:
                            notes.append(note)
                        continue
                    before = sent[:m.start]
                    negated = bool(_NEG_RE.search(before))
                    if concept.kind in ("drug", "drug_class"):
                        if section in ("allergies",):
                            continue
                        status = "not_current" if negated else ("past" if _PAST_RE.search(sent) else "current")
                        dose = _DOSE_RE.search(sent[m.end:m.end + 40])
                        key = ("med", m.code, status)
                        if key in seen:
                            continue
                        seen.add(key)
                        warnings = []
                        if status == "current" and section not in ("medications", "medication", "current medications",
                                                                    "plan"):
                            warnings.append("Mentioned outside a medication list; confirm you currently take it.")
                        if section == "plan":
                            warnings.append("Mentioned in the plan section; it may be a recommendation rather than a "
                                            "current medication.")
                        candidates.append(Candidate("medication", {
                            "concept": m.code, "name": m.text.strip().title() if concept.kind == "drug" else
                            (m.text.strip().title()), "status": status, "dose": dose.group(0) if dose else None},
                            page_no, sent.strip(), confidence=0.75 if not warnings else 0.6, warnings=warnings))
                    else:
                        fact_type = "procedure" if concept.kind == "procedure" else "condition"
                        assertion = "absent" if negated else "present"
                        key = (fact_type, m.code, assertion)
                        if key in seen:
                            continue
                        seen.add(key)
                        onset = parse_date(sent[m.end:m.end + 40]) if not negated else None
                        warnings = []
                        if negated:
                            warnings.append("Recorded as NOT present based on wording such as 'no history of'.")
                        candidates.append(Candidate(fact_type, {
                            "concept": m.code, "name": concept.label, "assertion": assertion,
                            ("performed_on" if fact_type == "procedure" else "onset_date"):
                                onset.isoformat() if onset else None},
                            page_no, sent.strip(), confidence=0.7, warnings=warnings))
    # contradictory candidates (present and absent for the same concept) -> flag both
    by_concept: dict[str, list[Candidate]] = {}
    for c in candidates:
        if c.fact_type in ("condition", "procedure"):
            by_concept.setdefault(c.payload["concept"], []).append(c)
    for _code, cs in by_concept.items():
        if {c.payload["assertion"] for c in cs} == {"present", "absent"}:
            for c in cs:
                c.warnings.append("This document mentions this both as present and as absent; review carefully.")
    status = "extracted" if any(p.strip() for p in pages) else "no_text"
    if status == "no_text":
        notes.append("No selectable text found (the PDF may be a scan). Please enter key values manually.")
    return ExtractionResult(pages, candidates, status, notes)


def merge_llm_candidates(rules: list[Candidate], llm: list[Candidate]) -> list[Candidate]:
    def key(c: Candidate):
        p = c.payload
        if c.fact_type == "lab":
            return ("lab", p.get("analyte"), p.get("value_numeric"), p.get("unit"))
        return (c.fact_type, p.get("concept") or p.get("name"), p.get("assertion") or p.get("status"))

    seen = {key(c) for c in rules}
    return rules + [c for c in llm if key(c) not in seen]
