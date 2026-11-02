"""Generate SYNTHETIC medical documents for demos and tests (no real patient data).

    python scripts/make_synthetic_docs.py  ->  data/synthetic/*.pdf
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic"

BANNER = "SYNTHETIC TEST DOCUMENT - NOT A REAL PATIENT - FOR SOFTWARE TESTING ONLY"


def _pdf() -> FPDF:
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 6, BANNER, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    return pdf


def lab_report(path: Path) -> None:
    pdf = _pdf()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Example Reference Laboratory - Lipid Panel", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in [
        "Patient: Synthetic Test Patient A      DOB: 03/02/2002",
        "Ordering clinician: Example Clinician, MD",
        "Collected: 09/14/2026      Reported: 09/16/2026",
        "",
        "Test                         Result     Flag   Reference range",
        "Lipoprotein (a)              185 nmol/L  H     <75 nmol/L",
        "Total Cholesterol            196 mg/dL         <200 mg/dL",
        "LDL Cholesterol Calc         118 mg/dL   H     0-99 mg/dL",
        "HDL Cholesterol              52 mg/dL          >39 mg/dL",
        "Triglycerides                128 mg/dL         0-149 mg/dL",
        "Hemoglobin A1c               5.2 %             4.8-5.6 %",
        "eGFR                         112 mL/min/1.73m2  >59 mL/min/1.73m2",
        "",
        "Comment: Lp(a) measured with an isoform-insensitive assay reported in nmol/L.",
    ]:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def physician_note(path: Path) -> None:
    pdf = _pdf()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Clinic Visit Note (synthetic)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in [
        "Date of service: 10/01/2026",
        "History of present illness: 24-year-old seen to discuss an elevated Lp(a) result.",
        "Past medical history: No history of coronary artery disease. No history of myocardial infarction.",
        "Denies diabetes. No known kidney disease.",
        "Family history: Father had a myocardial infarction at age 52. Mother with hypertension.",
        "Medications: No current medications. Not taking any lipid-lowering therapy.",
        "Allergies: No known drug allergies.",
        "Assessment: Elevated lipoprotein(a). Normal blood pressure today.",
        "Plan: Discussed lifestyle measures. Patient interested in learning about clinical trials.",
    ]:
        pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lab_report(OUT / "synthetic_lipid_panel.pdf")
    physician_note(OUT / "synthetic_clinic_note.pdf")
    print("wrote", sorted(p.name for p in OUT.glob("*.pdf")))


if __name__ == "__main__":
    main()
