"""PHI-safe logging.

Rule: application logs may contain identifiers (UUIDs, NCT IDs), event names, durations and
status codes - never clinical values, free text, names, emails, filenames or request bodies.

`PhiScrubFilter` is a defence-in-depth backstop that redacts common identifier patterns if a
developer accidentally interpolates them into a log message.
"""

from __future__ import annotations

import json
import logging
import re
import sys

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[phone]"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[date]"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "[date]"),
    (re.compile(r"\b\d+(\.\d+)?\s?(nmol/L|mg/dL|mmol/L|mg/L|%)", re.I), "[value]"),
]


def scrub(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class PhiScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg = scrub(message)
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("event", "request_id", "status", "duration_ms", "path"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(PhiScrubFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn's access log prints full query strings; ours (middleware) logs path templates only.
    logging.getLogger("uvicorn.access").disabled = True
    # HTTP client libraries log full URLs, which for registry searches contain terms derived from a
    # patient's conditions. Keep them at WARNING.
    for name in ("httpx", "httpx2", "httpcore", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)


log = logging.getLogger("trialcompass")
