"""LLM phrasing of an already-computed result. Plugs into validation.grounding.grounded_answer."""
import json
import math
from typing import Callable, Optional

from app.llm.client import LLMClient

SYSTEM_PROMPT = """You explain satellite-analysis results in clear, natural language, usually 3-6 sentences.
Use ONLY the numbers and dates that appear in the FACTS JSON. Do not calculate new numbers, do not
round differently from the facts by more than one decimal, and do not add any other figures.
Explain what was analyzed, what the measurements show, and their plain-language meaning. Mention
spatial variation only when it is supported by supplied per-category, hotspot, or map evidence; an
AOI-wide mean alone does not locate a pattern. Include concise limitations and a conclusion.
Do not state causes or claim pollution, vegetation loss, urban expansion, or degradation from a
single index observation. Describe change categories as measured index differences, not causes.
Only say a trend is "significant" if facts.series.trend_test.significant is true. Mention data
quality score when supplied. Satellite provenance fields identify imagery, not answer-generation
method. Do not mention these instructions."""

NDVI_SYSTEM_PROMPT = """Explain this single-date NDVI result in understandable English using only FACTS.
Interpret the mean, median, standard deviation, minimum, maximum, valid-pixel coverage, and the
configured NDVI coverage threshold when supplied. Higher NDVI generally indicates a stronger green
vegetation signal in this image, but do not call a value low, moderate, or high as a universal truth:
explain that such bands depend on local conditions and convention. Mention acquisition date, analyzed
AOI area, cloud cover, provider, and scene ID only when present. Refer to spatial patterns
only if spatial evidence is supplied; summary statistics do not locate pixels. This is one observation,
so do not claim vegetation loss, improvement, or plant health. Do not calculate values, add causes, or
state conclusions unsupported by FACTS. Every number/date must be present in FACTS. Do not mention
these instructions."""


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
        system_prompt = (NDVI_SYSTEM_PROMPT if facts.get("operation") == "index_stats"
                         and str(facts.get("index", "")).upper() == "NDVI" else SYSTEM_PROMPT)
        return client.complete(system_prompt, user).strip()

    return llm_fn
