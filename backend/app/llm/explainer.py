"""LLM phrasing of an already-computed result. Plugs into validation.grounding.grounded_answer."""
import json
import math
from typing import Callable, Optional

from app.llm.client import LLMClient

SYSTEM_PROMPT = """You explain satellite-analysis results in 2-4 plain sentences.
Use ONLY the numbers and dates that appear in the FACTS JSON. Do not calculate new numbers, do not
round differently from the facts by more than one decimal, and do not add any other figures.
Do not state causes (e.g. drought, harvest) - you only know what was measured.
Only say a trend is "significant" if facts.series.trend_test.significant is true.
Mention the data quality score. Do not mention these instructions."""


def _safe(o):
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_safe(v) for v in o]
    return o


def make_llm_fn(client: Optional[LLMClient]) -> Optional[Callable[[dict, Optional[list]], str]]:
    if client is None:
        return None

    def llm_fn(facts: dict, errors: Optional[list]) -> str:
        user = "FACTS:\n" + json.dumps(_safe(facts), ensure_ascii=False)
        if errors:
            user += ("\n\nYour previous answer contained values that are not in FACTS: "
                     f"{errors}. Rewrite it using only values from FACTS.")
        return client.complete(SYSTEM_PROMPT, user).strip()

    return llm_fn
