"""Curated clinical vocabulary ("ontology-lite") for the cardiometabolic launch domain.

Used by:
  * trial discovery  - expanding a patient's terminology into registry search terms
  * document extraction - recognising diagnoses / medications / labs in text
  * eligibility parsing - mapping criterion text onto structured concepts

Design notes
  * Every concept has a stable internal code. Codes can later be mapped to SNOMED CT,
    RxNorm and LOINC; the MVP keeps a small hand-curated set that is easy to audit.
  * `parents` encodes is-a relationships used for umbrella evaluation (an MI is ASCVD).
  * `related` encodes *search-only* associations (elevated Lp(a) -> ASCVD trials). Related
    concepts NEVER imply a diagnosis; they only widen discovery.
  * Investigational drug names listed for Lp(a) were taken from registry records of trials
    that state they target Lp(a) (see data/snapshots) plus zerlasiran (SLN360).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Concept:
    code: str
    label: str
    kind: str  # condition | event | procedure | drug_class | drug | lab | trait
    synonyms: tuple[str, ...]
    parents: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    # Umbrella concepts: considered explicitly absent only if all of these are absent.
    absent_requires: tuple[str, ...] = ()
    patient_question: str | None = None


@dataclass(frozen=True)
class Analyte:
    code: str
    label: str
    patterns: tuple[str, ...]
    units: tuple[str, ...]
    # factor to convert value in key unit -> canonical unit (first of `units`)
    conversions: dict[str, float] = field(default_factory=dict)
    convertible: bool = True
    non_convertible_reason: str | None = None
    recency_days: int | None = None  # older results are flagged as possibly outdated
    stability_note: str | None = None


C = Concept

CONCEPTS: list[Concept] = [
    # --- Cardiovascular disease and events -----------------------------------------
    C("ascvd", "Atherosclerotic cardiovascular disease (ASCVD)", "condition",
      ("atherosclerotic cardiovascular disease", "ascvd", "established cardiovascular disease",
       "established cardiovascular (cv) disease", "established cv disease", "atherosclerotic disease",
       "cardiovascular disease", "cv disease"),
      related=("cad", "dyslipidemia"),
      search_terms=("atherosclerotic cardiovascular disease", "cardiovascular disease"),
      absent_requires=("mi", "cad", "stroke", "pad")),
    C("atherosclerosis", "Atherosclerosis", "condition",
      ("atherosclerosis", "atheroscleroses", "evidence of atherosclerosis", "atherosclerotic plaque"),
      parents=("ascvd",), search_terms=("atherosclerosis",)),
    C("cad", "Coronary artery disease", "condition",
      ("coronary artery disease", "coronary heart disease", "ischemic heart disease", "ischaemic heart disease",
       "cad", "chd", "premature coronary artery disease", "premature coronary heart disease"),
      parents=("ascvd", "atherosclerosis"), search_terms=("coronary artery disease",),
      patient_question="Have you been diagnosed with coronary artery disease (blockages in the heart arteries)?"),
    C("mi", "Heart attack (myocardial infarction)", "event",
      ("myocardial infarction", "heart attack", "mi", "stemi", "nstemi"),
      parents=("cad", "ascvd", "ascvd_event"), search_terms=("myocardial infarction",),
      patient_question="Have you ever had a heart attack?"),
    C("acs", "Acute coronary syndrome", "event", ("acute coronary syndrome", "acs", "unstable angina"),
      parents=("cad", "ascvd", "ascvd_event")),
    C("stroke", "Ischemic stroke", "event",
      ("ischemic stroke", "ischaemic stroke", "stroke", "cerebrovascular accident", "cva"),
      parents=("ascvd", "ascvd_event"), search_terms=("ischemic stroke",),
      patient_question="Have you ever had a stroke or mini-stroke (TIA)?"),
    C("hemorrhagic_stroke", "Hemorrhagic stroke", "event",
      ("hemorrhagic stroke", "haemorrhagic stroke", "intracranial hemorrhage", "intracranial haemorrhage",
       "intracranial or intraocular hemorrhage")),
    C("tia", "Transient ischemic attack (TIA)", "event", ("transient ischemic attack", "tia", "mini-stroke"),
      parents=("ascvd_event",)),
    C("pad", "Peripheral artery disease", "condition",
      ("peripheral artery disease", "peripheral arterial disease", "pad"),
      parents=("ascvd", "atherosclerosis"), search_terms=("peripheral artery disease",),
      patient_question="Have you been diagnosed with peripheral artery disease (narrowed leg arteries)?"),
    C("ali", "Acute limb ischemia", "event", ("acute limb ischemia", "acute limb ischaemia"),
      parents=("pad", "ascvd_event")),
    C("carotid_stenosis", "Carotid artery stenosis", "condition",
      ("carotid stenosis", "carotid artery stenosis", "carotid artery disease"), parents=("ascvd", "atherosclerosis")),
    C("ascvd_event", "Prior cardiovascular event (heart attack, stroke or artery procedure)", "event",
      ("ascvd event", "atherosclerotic cardiovascular disease (ascvd) event", "atherosclerotic cardiovascular event",
       "major cardiovascular event", "major adverse cardiovascular event", "cardiovascular event", "cv event",
       "atherothrombotic event", "acute ischemic cardiovascular event", "ischemic event",
       "major or unstable cardiovascular event", "heart events", "atherosclerotic cardiovascular disease event",
       "cv events"),
      absent_requires=("mi", "stroke", "revascularization")),
    C("heart_failure", "Heart failure", "condition",
      ("heart failure", "ventricular systolic dysfunction", "lvef <40%"),
      patient_question="Have you been diagnosed with heart failure?"),
    C("aortic_stenosis", "Aortic valve stenosis", "condition",
      ("calcific aortic valve stenosis", "aortic valve stenosis", "aortic stenosis", "calcific aortic valve disease"),
      search_terms=("aortic stenosis",)),
    C("arrhythmia", "Ventricular arrhythmia", "condition", ("ventricular arrhythmia", "prolonged corrected qt interval")),
    # --- Lipid disorders --------------------------------------------------------------
    C("elevated_lpa", "Elevated lipoprotein(a)", "trait",
      ("elevated lipoprotein(a)", "elevated lp(a)", "high lp(a)", "hyperlipoproteinemia(a)",
       "hyperlipoproteinemia (a)", "hyper-lp(a)-emia", "lipoprotein(a)", "lp(a)"),
      related=("ascvd", "cad", "aortic_stenosis", "dyslipidemia"),
      search_terms=("lipoprotein(a)", "Lp(a)", "hyperlipoproteinemia(a)", "elevated lipoprotein(a)")),
    C("dyslipidemia", "Dyslipidemia / lipid disorder", "condition",
      ("dyslipidemia", "dyslipidaemia", "dyslipidemias", "hyperlipidemia", "hyperlipidaemia", "mixed dyslipidemia",
       "mixed hyperlipidemia", "lipid disorder", "lipoprotein disorder"),
      search_terms=("dyslipidemia", "hyperlipidemia")),
    C("hypercholesterolemia", "High cholesterol (hypercholesterolemia)", "condition",
      ("hypercholesterolemia", "hypercholesterolaemia", "high cholesterol", "elevated ldl cholesterol"),
      parents=("dyslipidemia",), search_terms=("hypercholesterolemia",)),
    C("fh", "Familial hypercholesterolemia", "condition",
      ("familial hypercholesterolemia", "familial hypercholesteremia", "familial hypercholesterolaemia",
       "heterozygous familial hypercholesterolemia", "hefh", "fh"),
      parents=("hypercholesterolemia",), search_terms=("familial hypercholesterolemia",),
      patient_question="Have you been diagnosed with familial hypercholesterolemia (inherited high cholesterol)?"),
    C("hofh", "Homozygous / compound heterozygous FH", "condition",
      ("homozygous familial hypercholesterolemia", "hofh", "compound heterozygous fh", "double heterozygous fh",
       "homozygous fh"),
      parents=("fh",)),
    C("statin_intolerance", "Statin intolerance", "condition", ("statin intolerance", "statin intolerant")),
    # --- Metabolic / renal / hepatic ---------------------------------------------------
    C("diabetes", "Diabetes", "condition", ("diabetes mellitus", "diabetes", "diabetic"),
      patient_question="Have you been diagnosed with diabetes?"),
    C("t1d", "Type 1 diabetes", "condition", ("type 1 diabetes", "type i diabetes"), parents=("diabetes",)),
    C("t2d", "Type 2 diabetes", "condition", ("type 2 diabetes", "type ii diabetes", "type 2 diabetes mellitus"),
      parents=("diabetes",)),
    C("hypertension", "High blood pressure (hypertension)", "condition",
      ("hypertension", "high blood pressure"),
      patient_question="Have you been diagnosed with high blood pressure?"),
    C("ckd", "Chronic kidney disease / reduced kidney function", "condition",
      ("chronic kidney disease", "ckd", "renal insufficiency", "renal impairment", "renal dysfunction",
       "kidney impairment", "renal failure", "reduced kidney function", "kidney disease", "renal disease",
       "ongoing dialysis", "dialysis"),
      patient_question="Have you been diagnosed with kidney disease or reduced kidney function?"),
    C("nephrotic_syndrome", "Nephrotic syndrome", "condition", ("nephrotic syndrome",), parents=("ckd",)),
    C("liver_disease", "Liver disease", "condition",
      ("hepatobiliary disease", "hepatic disease", "liver disease", "chronic liver disease", "cirrhosis",
       "hepatitis"),
      patient_question="Have you been diagnosed with a liver disease?"),
    C("hepatitis_b", "Hepatitis B", "condition", ("hepatitis b virus infection", "hepatitis b", "hbsag"),
      parents=("liver_disease",)),
    C("hepatitis_c", "Hepatitis C", "condition", ("hepatitis c virus infection", "hepatitis c", "hcv"),
      parents=("liver_disease",)),
    C("hiv", "HIV infection", "condition", ("human immunodeficiency virus", "hiv")),
    C("hypothyroidism", "Hypothyroidism", "condition", ("hypothyroidism",)),
    C("cancer", "Cancer", "condition",
      ("malignant tumor", "malignant tumour", "malignant disease", "malignancy", "cancer"),
      patient_question="Have you been diagnosed with or treated for cancer in the last 5 years?"),
    C("bleeding_disorder", "Bleeding or clotting disorder", "condition",
      ("major bleeding disorder", "bleeding disorder", "bleeding or coagulation disorders", "coagulation disorder",
       "hereditary hemorrhagic disorder", "hemorrhagic disorder", "hemophilia", "von willebrand disease"),
      patient_question="Have you been diagnosed with a bleeding or clotting disorder?"),
    # --- Procedures ---------------------------------------------------------------------
    C("revascularization", "Artery-opening procedure (stent, bypass)", "procedure",
      ("arterial revascularization", "coronary revascularization", "peripheral revascularization",
       "revascularization", "revascularisation", "procedure to restore blood flow"),
      parents=("ascvd_event",),
      patient_question="Have you had a procedure to open or bypass an artery (stent, angioplasty or bypass surgery)?"),
    C("pci", "Coronary stent / angioplasty (PCI)", "procedure",
      ("percutaneous coronary intervention", "pci", "coronary stent", "angioplasty"), parents=("revascularization", "cad")),
    C("cabg", "Coronary artery bypass surgery (CABG)", "procedure",
      ("coronary artery bypass graft surgery", "coronary artery bypass graft", "cabg", "bypass surgery"),
      parents=("revascularization", "cad")),
    C("apheresis", "Lipoprotein apheresis", "procedure",
      ("lipoprotein apheresis", "apheresis", "procedure to remove cholesterol from the blood",
       "procedure to remove lipoproteins from the blood")),
    # --- Medications (classes first, then drugs) ------------------------------------------
    C("lipid_lowering", "Cholesterol-lowering (lipid-lowering) medication", "drug_class",
      ("lipid-lowering therapy", "lipid lowering therapy", "lipid-lowering drugs", "lipid-lowering medications",
       "lipid-lowering treatment", "lipid lowering medication", "cholesterol-lowering medication", "llt"),
      absent_requires=("statin", "ezetimibe", "pcsk9i", "niacin", "bempedoic_acid", "fibrate"),
      patient_question="Are you taking a cholesterol-lowering medication (for example a statin)?"),
    C("statin", "Statin", "drug_class",
      ("statin therapy", "statins", "statin", "hmg-coa reductase inhibitor", "atorvastatin", "rosuvastatin",
       "simvastatin", "pravastatin", "lovastatin", "fluvastatin", "pitavastatin"),
      parents=("lipid_lowering",)),
    C("ezetimibe", "Ezetimibe", "drug", ("ezetimibe",), parents=("lipid_lowering",)),
    C("pcsk9i", "PCSK9 inhibitor", "drug_class",
      ("pcsk9 inhibitors", "pcsk9 inhibitor", "evolocumab", "alirocumab", "inclisiran"), parents=("lipid_lowering",)),
    C("niacin", "Niacin", "drug", ("prescription strength niacin", "niacin", "nicotinic acid"), parents=("lipid_lowering",)),
    C("bempedoic_acid", "Bempedoic acid", "drug", ("bempedoic acid",), parents=("lipid_lowering",)),
    C("fibrate", "Fibrate", "drug_class", ("fibrates", "fibrate", "fenofibrate", "gemfibrozil", "bezafibrate"),
      parents=("lipid_lowering",)),
    C("lpa_targeted", "Lp(a)-targeted therapy", "drug_class",
      ("therapy specifically targeting lp(a)", "ribonucleic acid therapy specifically targeting lp(a)",
       "lp(a) inhibitor", "drugs affecting lp(a)", "pelacarsen", "olpasiran", "lepodisiran", "zerlasiran",
       "muvalaplin", "mk-7262", "azd4954", "sal0195", "syh2068", "hrs-5632", "hrs-5346", "bsa204", "tqj230",
       "ly3819469", "sln360"),
      search_terms=("pelacarsen", "olpasiran", "lepodisiran", "zerlasiran", "muvalaplin", "MK-7262", "AZD4954"),
      patient_question="Have you ever received an investigational Lp(a)-lowering therapy (for example in a clinical trial)?"),
    C("oligonucleotide", "siRNA or antisense oligonucleotide therapy", "drug_class",
      ("small interfering rna", "sirna", "antisense oligonucleotide", "oligonucleotide drugs", "oligonucleotide")),
    C("investigational_drug", "Another investigational drug or clinical trial", "drug_class",
      ("investigational drug", "investigational product", "clinical study treatment", "interventional clinical study",
       "investigational therapy", "other clinical study")),
    C("anticoagulant", "Blood thinner (anticoagulant)", "drug_class",
      ("anticoagulant", "anticoagulation", "warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban")),
    C("hormonal_contraceptive", "Hormonal contraceptive", "drug_class", ("hormonal contraceptives", "hormonal contraceptive")),
]

ANALYTES: list[Analyte] = [
    Analyte("lpa", "Lipoprotein(a) [Lp(a)]",
            (r"lipoprotein\s*\(\s*a\s*\)", r"\blp\s*\(\s*a\s*\)", r"lipoprotein\s+a\b", r"\blpa\b"),
            ("nmol/L", "mg/dL"),
            convertible=False,
            non_convertible_reason=("Lp(a) results in nmol/L and mg/dL measure different things (particle count vs. "
                                    "mass) and cannot be reliably converted, because the conversion depends on "
                                    "apolipoprotein(a) isoform size."),
            stability_note="Studies usually re-measure Lp(a) at screening."),
    Analyte("ldl_c", "LDL cholesterol (LDL-C)",
            (r"\bldl[-\s]?c\b", r"ldl\s+cholesterol", r"low[-\s]density\s+lipoprotein\s+cholesterol", r"\bldl\b"),
            ("mg/dL", "mmol/L"), conversions={"mmol/L": 38.67}, recency_days=365),
    Analyte("non_hdl_c", "Non-HDL cholesterol", (r"non[-\s]hdl[-\s]?c(holesterol)?",), ("mg/dL", "mmol/L"),
            conversions={"mmol/L": 38.67}, recency_days=365),
    Analyte("hdl_c", "HDL cholesterol (HDL-C)",
            (r"\bhdl[-\s]?c\b", r"hdl\s+cholesterol", r"high[-\s]density\s+lipoprotein\s+cholesterol"),
            ("mg/dL", "mmol/L"), conversions={"mmol/L": 38.67}, recency_days=365),
    Analyte("total_cholesterol", "Total cholesterol", (r"total\s+cholesterol", r"cholesterol,\s*total"),
            ("mg/dL", "mmol/L"), conversions={"mmol/L": 38.67}, recency_days=365),
    Analyte("triglycerides", "Triglycerides", (r"triglycerides?", r"\btg\b"),
            ("mg/dL", "mmol/L"), conversions={"mmol/L": 88.57}, recency_days=365),
    Analyte("apob", "Apolipoprotein B (ApoB)", (r"apolipoprotein\s+b\b", r"\bapo\s?b\b"), ("mg/dL", "g/L"),
            conversions={"g/L": 100.0}, recency_days=365),
    Analyte("hba1c", "Hemoglobin A1c (HbA1c)",
            (r"\bhba1c\b", r"hemoglobin\s+a1c", r"haemoglobin\s+a1c", r"glycated\s+ha?emoglobin", r"\ba1c\b"),
            ("%",), recency_days=180),
    Analyte("egfr", "eGFR (kidney function)",
            (r"\begfr\b", r"estimated\s+glomerular\s+(filtration\s+)?rate"), ("mL/min/1.73m2",), recency_days=365),
    Analyte("creatinine", "Creatinine", (r"\bcreatinine\b",), ("mg/dL", "umol/L"), conversions={"umol/L": 1 / 88.4},
            recency_days=365),
    Analyte("alt", "ALT", (r"alanine\s+aminotransferase", r"\balt\b"), ("U/L",), recency_days=180),
    Analyte("ast", "AST", (r"aspartate\s+aminotransferase", r"\bast\b"), ("U/L",), recency_days=180),
    Analyte("hscrp", "hs-CRP", (r"high[-\s]sensitivity\s+c[-\s]reactive\s+protein", r"\bhs[-\s]?crp\b"),
            ("mg/L",), recency_days=180),
    Analyte("bmi", "Body mass index (BMI)", (r"body\s+mass\s+index", r"\bbmi\b"), ("kg/m2",), recency_days=365),
    Analyte("cac_score", "Coronary artery calcium (CAC) score",
            (r"coronary\s+artery\s+calcium(\s+\(cac\))?(\s+score)?", r"\bcac\s+score\b"), ("Agatston",)),
    Analyte("plasminogen", "Plasminogen", (r"\bplasminogen\b",), ("%",)),
    Analyte("uacr", "Urine albumin-creatinine ratio", (r"urine\s+albumin[-\s]creatinine\s+ratio", r"\buacr\b"),
            ("mg/g",)),
]

UNIT_ALIASES = {
    "nmol/l": "nmol/L", "nanomoles per liter": "nmol/L", "nanomoles/l": "nmol/L", "nmol / l": "nmol/L",
    "mg/dl": "mg/dL", "milligrams per deciliter": "mg/dL", "mg / dl": "mg/dL",
    "mmol/l": "mmol/L", "mmol / l": "mmol/L",
    "mg/l": "mg/L", "g/l": "g/L", "umol/l": "umol/L", "µmol/l": "umol/L",
    "%": "%", "percent": "%",
    "ml/min/1.73m2": "mL/min/1.73m2", "ml/min/1.73 m2": "mL/min/1.73m2", "ml/min/1.73m²": "mL/min/1.73m2",
    "ml/min/1.73 m²": "mL/min/1.73m2", "milliliters per minute per 1.73 meters squared": "mL/min/1.73m2",
    "kg/m2": "kg/m2", "kg/m²": "kg/m2", "u/l": "U/L", "iu/l": "U/L", "mg/g": "mg/g",
}

UNIT_REGEX = (r"(nmol\s*/\s*l|nanomoles per liter|mg\s*/\s*dl|mmol\s*/\s*l|µmol\s*/\s*l|umol\s*/\s*l|mg\s*/\s*l|"
              r"g\s*/\s*l|ml/min/1\.73\s?m(?:2|²)|milliliters per minute per 1\.73 meters squared|kg/m(?:2|²)|"
              r"i?u/l|mg/g|%)")


def normalize_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = re.sub(r"\s+", " ", raw.strip().lower()).replace(" / ", "/")
    key2 = key.replace(" ", "")
    return UNIT_ALIASES.get(key) or UNIT_ALIASES.get(key2) or raw.strip()


@lru_cache
def concept_index() -> dict[str, Concept]:
    return {c.code: c for c in CONCEPTS}


@lru_cache
def analyte_index() -> dict[str, Analyte]:
    return {a.code: a for a in ANALYTES}


def get_concept(code: str) -> Concept | None:
    return concept_index().get(code)


def ancestors(code: str) -> set[str]:
    out: set[str] = set()
    stack = list(concept_index()[code].parents) if code in concept_index() else []
    while stack:
        c = stack.pop()
        if c not in out:
            out.add(c)
            stack.extend(concept_index()[c].parents if c in concept_index() else ())
    return out


def descendants(code: str) -> set[str]:
    return {c.code for c in CONCEPTS if code in ancestors(c.code)}


# ---------------------------------------------------------------------------- matching


@dataclass(frozen=True)
class Mention:
    code: str
    start: int
    end: int
    text: str


def _syn_pattern(s: str) -> str:
    esc = re.escape(s)
    # whole-word boundaries for alphanumeric edges
    left = r"(?<![a-z0-9])" if s[0].isalnum() else ""
    right = r"(?:s|es)?(?![a-z0-9])" if s[-1].isalnum() else (r"(?![a-z0-9])" if s[-1] == ")" else "")
    return left + esc + right


@lru_cache
def _compiled_synonyms(kinds: tuple[str, ...] | None) -> list[tuple[re.Pattern[str], str]]:
    pairs: list[tuple[str, str]] = []
    for c in CONCEPTS:
        if kinds and c.kind not in kinds:
            continue
        for s in c.synonyms:
            pairs.append((s.lower(), c.code))
    pairs.sort(key=lambda p: -len(p[0]))  # longest first
    return [(re.compile(_syn_pattern(s)), code) for s, code in pairs]


def find_concepts(text: str, kinds: tuple[str, ...] | None = None) -> list[Mention]:
    """Find concept mentions; longer matches win over contained shorter ones."""
    low = text.lower()
    taken: list[tuple[int, int]] = []
    found: list[Mention] = []
    for pat, code in _compiled_synonyms(kinds):
        for m in pat.finditer(low):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            found.append(Mention(code, s, e, text[s:e]))
    found.sort(key=lambda m: m.start)
    return found


@lru_cache
def _analyte_patterns() -> list[tuple[re.Pattern[str], str]]:
    out = []
    for a in ANALYTES:
        for p in a.patterns:
            out.append((re.compile(p, re.I), a.code))
    return out


def find_analytes(text: str) -> list[Mention]:
    taken: list[tuple[int, int]] = []
    found: list[Mention] = []
    for pat, code in _analyte_patterns():
        for m in pat.finditer(text):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            found.append(Mention(code, s, e, text[s:e]))
    found.sort(key=lambda m: m.start)
    return found


def convert(analyte: str, value: float, from_unit: str, to_unit: str) -> float | None:
    """Convert between units where a fixed factor exists. Returns None if not reliably convertible."""
    a = analyte_index().get(analyte)
    if a is None:
        return None
    if from_unit == to_unit:
        return value
    if not a.convertible:
        return None
    canonical = a.units[0]
    to_canon = 1.0 if from_unit == canonical else a.conversions.get(from_unit)
    if to_canon is None:
        return None
    v = value * to_canon
    if to_unit == canonical:
        return v
    from_canon = a.conversions.get(to_unit)
    return None if from_canon is None else v / from_canon
