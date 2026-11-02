"""Trial data sources.

`TrialSource` is the extension point for additional registries (sponsor registries, hospital
research databases, WHO ICTRP, EU CTIS, ...). Each adapter must:
  * use official APIs or explicitly licensed data feeds only (no indiscriminate scraping),
  * honour rate limits and terms of use,
  * normalize into `TrialRecord` and list any fields it cannot supply in `field_gaps`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.modules.trials.geo import haversine_miles
from app.modules.trials.normalize import from_connector, from_ctgov_v2
from app.modules.trials.records import TrialRecord

log = logging.getLogger("trialcompass.trials")

ACTIVE_STATUSES = ["RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"]


@dataclass
class SearchQuery:
    condition_terms: list[str] = field(default_factory=list)  # OR-combined
    intervention_terms: list[str] = field(default_factory=list)  # OR-combined
    free_text: str | None = None
    statuses: list[str] = field(default_factory=lambda: list(ACTIVE_STATUSES))
    near: tuple[float, float] | None = None
    radius_miles: int | None = None
    max_results: int = 200


class SourceUnavailable(Exception):
    pass


class TrialSource(Protocol):
    name: str

    def search(self, q: SearchQuery) -> list[TrialRecord]: ...

    def get(self, nct_id: str) -> TrialRecord | None: ...


# ----------------------------------------------------------------------------- live API


class _RateLimiter:
    def __init__(self, per_minute: int):
        self.interval = 60.0 / max(per_minute, 1)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


def _or_expr(terms: list[str]) -> str:
    quoted = [f'"{t}"' if (" " in t or "(" in t) and not t.startswith('"') else t for t in terms]
    return " OR ".join(quoted)


class ClinicalTrialsGovSource:
    """ClinicalTrials.gov Data API v2 (https://clinicaltrials.gov/data-api/api).

    Notes on limitations (see docs/ARCHITECTURE.md):
      * No authentication; NLM asks clients to stay around <=50 requests/minute.
      * Search is keyword/Essie-expression based with registry synonym expansion; it is not
        semantic, so we expand patient terminology ourselves before querying.
      * Site-level recruitment status and contacts are sponsor-reported and can lag reality.
    """

    name = "clinicaltrials.gov"

    def __init__(self) -> None:
        s = get_settings()
        self.base = s.ctgov_base_url.rstrip("/")
        self.limiter = _RateLimiter(s.ctgov_requests_per_minute)
        self.client = httpx.Client(
            timeout=s.ctgov_timeout_seconds,
            headers={"User-Agent": f"{s.app_name}/0.1 (clinical trial discovery; contact via repository)"},
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        last_exc: Exception | None = None
        for attempt in range(4):
            self.limiter.wait()
            try:
                resp = self.client.get(f"{self.base}{path}", params=params)
            except (httpx.ConnectError, httpx.ProxyError) as exc:  # host unreachable / egress refused: fail fast
                last_exc = exc
                if attempt >= 1:
                    break
                time.sleep(0.5)
                continue
            except httpx.HTTPError as exc:  # timeouts and transient transport errors: back off
                last_exc = exc
                time.sleep(2**attempt)
                continue
            if resp.status_code == 404:
                return {}
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(2**attempt)
                last_exc = httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                continue
            if resp.status_code >= 400:
                raise SourceUnavailable(f"ClinicalTrials.gov returned HTTP {resp.status_code}")
            return resp.json()
        raise SourceUnavailable(f"ClinicalTrials.gov unreachable: {type(last_exc).__name__}")

    def search(self, q: SearchQuery) -> list[TrialRecord]:
        params: dict[str, str | int] = {"pageSize": min(q.max_results, 100), "format": "json"}
        if q.condition_terms:
            params["query.cond"] = _or_expr(q.condition_terms)
        if q.intervention_terms:
            params["query.intr"] = _or_expr(q.intervention_terms)
        if q.free_text:
            params["query.term"] = q.free_text
        if q.statuses:
            params["filter.overallStatus"] = ",".join(q.statuses)
        if q.near and q.radius_miles:
            params["filter.geo"] = f"distance({q.near[0]:.4f},{q.near[1]:.4f},{q.radius_miles}mi)"
        out: list[TrialRecord] = []
        today = date.today().isoformat()
        token = None
        while len(out) < q.max_results:
            if token:
                params["pageToken"] = token
            data = self._get("/studies", params)
            for st in data.get("studies", []) or []:
                out.append(from_ctgov_v2(st, retrieved_at=today))
            token = data.get("nextPageToken")
            if not token:
                break
        return out[: q.max_results]

    def get(self, nct_id: str) -> TrialRecord | None:
        data = self._get(f"/studies/{nct_id}", {"format": "json"})
        return from_ctgov_v2(data, retrieved_at=date.today().isoformat()) if data else None


# ----------------------------------------------------------------------------- snapshot


class SnapshotSource:
    """Real registry records captured earlier (see data/snapshots/*.json `meta`)."""

    name = "snapshot"

    def __init__(self, path=None) -> None:
        path = path or get_settings().snapshot_path
        raw = json.loads(open(path, encoding="utf-8").read())
        self.meta = raw.get("meta", {})
        retrieved = self.meta.get("retrieved_at", "unknown")
        self.records = {t["nct_id"]: from_connector(t, retrieved) for t in raw["trials"]}

    @staticmethod
    def _haystack(r: TrialRecord) -> str:
        parts = [r.brief_title, r.official_title or "", r.brief_summary or "", " ".join(r.conditions),
                 " ".join(r.keywords), " ".join(i.name for i in r.interventions)]
        return " ".join(parts).lower()

    def search(self, q: SearchQuery) -> list[TrialRecord]:
        results = []
        cond = [t.lower().strip('"') for t in q.condition_terms]
        intr = [t.lower().strip('"') for t in q.intervention_terms]
        free = (q.free_text or "").lower().split()
        for r in self.records.values():
            if q.statuses and r.overall_status not in q.statuses:
                continue
            hay = self._haystack(r)
            hit_c = any(t in hay for t in cond) if cond else False
            hit_i = any(t in hay for t in intr) if intr else False
            hit_f = all(w in hay for w in free) if free else False
            if not (hit_c or hit_i or hit_f):
                continue
            if q.near and q.radius_miles:
                pts = [(loc.latitude, loc.longitude) for loc in r.locations if loc.latitude is not None]
                if not pts or min(haversine_miles(q.near, p) for p in pts) > q.radius_miles:
                    continue
            results.append(r)
        return results[: q.max_results]

    def get(self, nct_id: str) -> TrialRecord | None:
        return self.records.get(nct_id)


# ----------------------------------------------------------------------------- factory


@dataclass
class SourceStatus:
    mode: str
    active: str
    live_reachable: bool | None
    snapshot_retrieved_at: str | None
    message: str


class TrialRepository:
    """Chooses live vs snapshot according to TRIAL_SOURCE (live | snapshot | auto)."""

    REPROBE_SECONDS = 600

    def __init__(self) -> None:
        self.mode = get_settings().trial_source
        self._live: ClinicalTrialsGovSource | None = None
        self._snapshot: SnapshotSource | None = None
        self.live_reachable: bool | None = None
        self._live_failed_at: float | None = None

    @property
    def snapshot(self) -> SnapshotSource:
        if self._snapshot is None:
            self._snapshot = SnapshotSource()
        return self._snapshot

    @property
    def live(self) -> ClinicalTrialsGovSource:
        if self._live is None:
            self._live = ClinicalTrialsGovSource()
        return self._live

    def _use_live(self) -> bool:
        if self.mode == "live":
            return True
        if self.mode != "auto":
            return False
        # in auto mode, retry the live API periodically after a failure
        return self._live_failed_at is None or time.monotonic() - self._live_failed_at > self.REPROBE_SECONDS

    def _mark_live(self, ok: bool) -> None:
        self.live_reachable = ok
        self._live_failed_at = None if ok else time.monotonic()

    def search(self, q: SearchQuery) -> tuple[list[TrialRecord], str]:
        if self._use_live():
            try:
                res = self.live.search(q)
                self._mark_live(True)
                return res, "live"
            except SourceUnavailable as exc:
                self._mark_live(False)
                log.warning("live trial source unavailable: %s", exc)
                if self.mode == "live":
                    raise
        return self.snapshot.search(q), "snapshot"

    def get(self, nct_id: str) -> tuple[TrialRecord | None, str]:
        if self._use_live():
            try:
                rec = self.live.get(nct_id)
                self._mark_live(True)
                return rec, "live"
            except SourceUnavailable:
                self._mark_live(False)
                if self.mode == "live":
                    raise
        return self.snapshot.get(nct_id), "snapshot"

    def status(self) -> SourceStatus:
        active = "live" if (self.mode == "live" or (self.mode == "auto" and self.live_reachable)) else "snapshot"
        snap_date = None
        try:
            snap_date = self.snapshot.meta.get("retrieved_at")
        except FileNotFoundError:
            pass
        if active == "snapshot":
            msg = (f"Showing an offline snapshot of real ClinicalTrials.gov records retrieved {snap_date}. "
                   "Recruitment status may have changed since then; always confirm on ClinicalTrials.gov.")
        else:
            msg = "Live data from the ClinicalTrials.gov API."
        return SourceStatus(self.mode, active, self.live_reachable, snap_date, msg)


@lru_cache
def get_repository() -> TrialRepository:
    return TrialRepository()
