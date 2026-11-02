"""Thin, guarded wrapper around the Anthropic Messages API (structured outputs).

Every LLM component in the product goes through here, which gives one place to enforce:
  * availability (LLM_ENABLED + ANTHROPIC_API_KEY),
  * the PHI gate - patient data is only sent when the profile is synthetic, or when the
    deployment explicitly allows real PHI AND a BAA with the vendor is in place, AND the
    user consented to AI processing,
  * structured outputs validated against Pydantic schemas,
  * refusal / error handling that degrades to the deterministic path (returns None),
  * logging that records event names only - never prompts or outputs.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import get_settings

log = logging.getLogger("trialcompass.llm")
T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    @property
    def available(self) -> bool:
        return self.settings.llm_available

    def _get(self):
        if self._client is None:
            import anthropic  # optional dependency

            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key.get_secret_value())
        return self._client

    def parse(self, *, system: str, user: str, schema: type[T], max_tokens: int = 8000, effort: str = "medium") -> T | None:
        if not self.available:
            return None
        import anthropic

        try:
            response = self._get().beta.messages.parse(
                model=self.settings.llm_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": effort},
                # Server-side refusal fallback: if a safety classifier declines, the API re-runs the
                # request on an appropriate fallback model within the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError:
            log.warning("llm_rate_limited")
            return None
        except anthropic.APIStatusError as exc:
            log.warning("llm_api_error status=%s", exc.status_code)
            return None
        except anthropic.APIConnectionError:
            log.warning("llm_connection_error")
            return None
        if response.stop_reason == "refusal":
            log.info("llm_refusal")
            return None
        if response.stop_reason == "max_tokens":
            log.info("llm_truncated")
            return None
        return response.parsed_output


def phi_allowed(profile, ai_consent: bool) -> tuple[bool, str]:
    """May this profile's health information be sent to the external LLM vendor?"""
    s = get_settings()
    if not s.llm_available:
        return False, "llm_disabled"
    if not ai_consent:
        return False, "no_ai_consent"
    if profile.is_synthetic:
        return True, "synthetic_profile"
    if s.allow_real_phi and s.llm_baa_in_place:
        return True, "baa_in_place"
    return False, "real_phi_blocked"


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
