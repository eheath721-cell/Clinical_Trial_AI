"""One-off provenance script: extract ClinicalTrials.gov records captured through the
ClinicalTrials.gov connector during development into a raw JSON file.

Why this exists: the development sandbox could not reach clinicaltrials.gov directly
(egress policy), but a ClinicalTrials.gov API v2 connector was available. This script
copies the connector's responses *verbatim* out of the session transcript / saved tool
result files so that no trial data is hand-transcribed. `build_snapshot.py` then
normalizes them into the application's snapshot format.

Usage:
    python scripts/extract_connector_snapshot.py <transcript.jsonl> <tool-results-dir> <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _iter_tool_results(transcript: Path):
    for line in transcript.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    for part in inner:
                        if isinstance(part, dict) and part.get("type") == "text":
                            yield part.get("text", "")
                elif isinstance(inner, str):
                    yield inner


def main() -> None:
    transcript, results_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    trials: dict[str, dict] = {}

    candidates = list(_iter_tool_results(transcript))
    candidates += [p.read_text() for p in results_dir.glob("mcp-Clinical_Trials-get_trial_details-*.txt")]

    for text in candidates:
        text = text.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        trial = data.get("trial") if isinstance(data, dict) else None
        if data.get("found") and isinstance(trial, dict) and trial.get("nct_id"):
            trials[trial["nct_id"]] = trial

    out.write_text(json.dumps({"source": "clinicaltrials.gov API v2 via connector", "trials": list(trials.values())}, indent=1, ensure_ascii=False))
    print(f"extracted {len(trials)} trials -> {out}")
    for nct in sorted(trials):
        t = trials[nct]
        print(f"  {nct} {t.get('status')} locations={len(t.get('locations') or [])}")


if __name__ == "__main__":
    main()
