"""Wrap verbatim connector records with provenance metadata to produce the offline snapshot.

    python scripts/build_snapshot.py <connector_raw.json> data/snapshots/ctgov_lpa_snapshot.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

META = {
    "description": (
        "Offline snapshot of real ClinicalTrials.gov records related to lipoprotein(a) and atherosclerotic "
        "cardiovascular disease. Used when the live API is unreachable (offline development, CI, demos)."
    ),
    "registry": "clinicaltrials.gov",
    "retrieved_at": "2026-11-02",
    "retrieval_method": (
        "ClinicalTrials.gov API v2 accessed through a ClinicalTrials.gov connector; responses copied verbatim "
        "by scripts/extract_connector_snapshot.py (no manual transcription)."
    ),
    "queries": [
        "condition=lipoprotein(a) OR \"Lp(a)\" OR hyperlipoproteinemia(a); status in recruiting/not yet/enrolling/active",
        "intervention=pelacarsen OR olpasiran OR lepodisiran OR zerlasiran OR muvalaplin OR MK-7262 ...",
        "condition=lipoprotein(a), location=Texas",
        "condition=ASCVD OR CAD OR hypercholesterolemia, location=Lubbock",
    ],
    "field_gaps": (
        "The connector format omits: last-update-posted date, site coordinates, contact phone numbers and email "
        "addresses, overall officials, keywords, and intervention types. The application labels these as "
        "unavailable instead of inventing them; the live API adapter populates all of them."
    ),
    "license_note": "ClinicalTrials.gov data are provided by the U.S. National Library of Medicine.",
}


def main() -> None:
    raw = json.loads(Path(sys.argv[1]).read_text())
    trials = sorted(raw["trials"], key=lambda t: t["nct_id"])
    Path(sys.argv[2]).write_text(json.dumps({"meta": META, "trials": trials}, indent=1, ensure_ascii=False))
    print(f"wrote {len(trials)} trials -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
