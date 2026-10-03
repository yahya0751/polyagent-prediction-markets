"""Resolution rule reader.

`read(market)` returns a `RuleAnalysis` with:
  * resolution_clarity in [0, 1]
  * deadline (parsed if possible)
  * official source guess
  * list of ambiguity flags

Default implementation is a transparent rule-based heuristic — no LLM
call, no token cost, no external dependency. Replace with an LLM-backed
implementation by passing `llm_caller` to RuleReader. The interface is
the seam.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional

from ..types import Market

LLMCaller = Callable[[str], Awaitable[str]]


@dataclass
class RuleAnalysis:
    resolution_clarity: float    # [0, 1]
    deadline: Optional[datetime]
    official_source: str
    ambiguity_flags: list[str] = field(default_factory=list)


# Words/phrases historically associated with disputed resolutions.
AMBIGUITY_TERMS = [
    "subjective", "may include", "may exclude", "at the discretion",
    "any reasonable", "if applicable", "where possible", "approximately",
    "expected to", "anticipated", "potentially", "likely",
    "if not resolved", "fallback", "manually resolved",
    "at admin discretion", "no official", "various sources",
]

# Phrases that suggest a clear, single official source.
GOOD_SOURCE_TERMS = [
    "official statement from", "press release from", "filing with",
    "results published by", "as reported by reuters", "as reported by ap",
    "official website", "government website", "court document",
]


class RuleReader:
    def __init__(self, llm_caller: Optional[LLMCaller] = None):
        self._llm = llm_caller

    async def read(self, market: Market) -> RuleAnalysis:
        text = (market.rules_text or market.description or "").strip()
        if not text:
            return RuleAnalysis(
                resolution_clarity=0.30,
                deadline=market.close_time,
                official_source=market.resolution_source or "",
                ambiguity_flags=["empty rules text"],
            )

        # If an LLM caller is configured, prefer it.
        if self._llm is not None:
            return await self._llm_read(market, text)

        return self._heuristic_read(market, text)

    @staticmethod
    def _heuristic_read(market: Market, text: str) -> RuleAnalysis:
        lower = text.lower()
        ambiguity = [t for t in AMBIGUITY_TERMS if t in lower]
        good_source_hits = sum(1 for t in GOOD_SOURCE_TERMS if t in lower)

        # Base clarity. Long, structured rules with few weasel words and
        # a named source clear. Short or weasel-heavy rules don't.
        words = len(lower.split())
        length_score = min(1.0, words / 80.0)
        ambiguity_penalty = min(0.6, 0.12 * len(ambiguity))
        source_bonus = min(0.2, 0.10 * good_source_hits)
        if market.resolution_source:
            source_bonus += 0.10

        clarity = max(0.0, min(1.0, 0.35 + 0.5 * length_score - ambiguity_penalty + source_bonus))

        return RuleAnalysis(
            resolution_clarity=clarity,
            deadline=market.close_time,
            official_source=market.resolution_source or "",
            ambiguity_flags=ambiguity,
        )

    async def _llm_read(self, market: Market, text: str) -> RuleAnalysis:
        # Prompt the LLM for a structured judgement, keep it short to
        # control tokens. Caller of RuleReader provides the LLM function.
        prompt = (
            "You are evaluating a prediction-market resolution rule. "
            "Reply ONLY with one line in this exact format:\n"
            "CLARITY=<0.0-1.0> | SOURCE=<one short phrase> | "
            "AMBIGUITY=<comma-separated flags or 'none'>\n\n"
            f"Question: {market.question}\nRules:\n{text[:2000]}"
        )
        try:
            raw = await self._llm(prompt)
        except Exception:
            return self._heuristic_read(market, text)

        clarity = 0.5
        source = market.resolution_source or ""
        flags: list[str] = []
        m = re.search(r"CLARITY\s*=\s*([0-9.]+)", raw)
        if m:
            try:
                clarity = max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass
        m = re.search(r"SOURCE\s*=\s*([^|]+)", raw)
        if m:
            source = m.group(1).strip()
        m = re.search(r"AMBIGUITY\s*=\s*([^|]+)", raw)
        if m:
            raw_flags = m.group(1).strip()
            if raw_flags and raw_flags.lower() != "none":
                flags = [f.strip() for f in raw_flags.split(",") if f.strip()]

        return RuleAnalysis(
            resolution_clarity=clarity,
            deadline=market.close_time,
            official_source=source,
            ambiguity_flags=flags,
        )
