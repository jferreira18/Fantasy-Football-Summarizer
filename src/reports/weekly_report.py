"""Resolve every narrative metric from the authoritative analysis JSON."""
import hashlib
import json
import math
import re

from src.llm.client import NarrativeError, generate_narrative
from src.llm.prompts import SECTIONS
from .html import render_html
from .markdown import render_markdown

REFERENCE = re.compile(r"\{\{(/[^{}]*)\}\}")
NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"half|quarter|double|triple|twice|dozen)\b", re.I)


def resolve_pointer(analysis, pointer):
    current = analysis
    for raw in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw):
            raise NarrativeError("Invalid JSON pointer escape")
        key = raw.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise ValueError()
                current = current[int(key)]
            elif isinstance(current, dict):
                current = current[key]
            else:
                raise ValueError()
        except (KeyError, IndexError, ValueError, TypeError):
            raise NarrativeError(f"Unknown metric reference: {pointer}") from None
    if current is None or isinstance(current, (dict, list, bool)):
        raise NarrativeError(f"Reference must identify a non-null scalar: {pointer}")
    if not isinstance(current, (str, int, float)) or (isinstance(current, float) and not math.isfinite(current)):
        raise NarrativeError(f"Unsupported metric value: {pointer}")
    return current


def render_template(template, analysis, references, location):
    if not isinstance(template, str) or not template.strip() or len(template) > 16000:
        raise NarrativeError("Invalid narrative paragraph")
    residual = REFERENCE.sub("", template)
    if "{{" in residual or "}}" in residual:
        raise NarrativeError("Malformed metric placeholder")
    if any(c.isnumeric() for c in residual) or NUMBER_WORDS.search(residual):
        raise NarrativeError("Narrative contains an unreferenced number; use metric placeholders")

    def substitute(match):
        pointer = match.group(1)
        value = resolve_pointer(analysis, pointer)
        rendered = str(value)
        references.append({"location": location, "pointer": pointer,
                           "value": value, "rendered": rendered})
        return rendered
    return REFERENCE.sub(substitute, template)


def audit_narrative(narrative, analysis, *, preview=False):
    if not isinstance(narrative, dict) or set(narrative) != {"sections"}:
        raise NarrativeError("Invalid report structure")
    sections = narrative["sections"]
    if not isinstance(sections, list) or not sections or len(sections) > len(SECTIONS):
        raise NarrativeError("Invalid report sections")
    result, references, titles = [], [], set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict) or set(section) != {"title", "paragraphs"}:
            raise NarrativeError("Invalid section structure")
        title, paragraphs = section["title"], section["paragraphs"]
        if title not in SECTIONS or title in titles:
            raise NarrativeError("Unknown or duplicate report heading")
        titles.add(title)
        if not isinstance(paragraphs, list) or not paragraphs or len(paragraphs) > 100:
            raise NarrativeError("Section must contain paragraphs")
        result.append({"title": title, "paragraphs": [
            render_template(p, analysis, references, f"sections/{index}/paragraphs/{i}")
            for i, p in enumerate(paragraphs)]})
    if "Week at a Glance" not in titles:
        raise NarrativeError("Missing week overview")
    for index, _ in enumerate(analysis.get("top_matchups", [])[:3]):
        title = SECTIONS[index + 1]
        matched = next((i for i, section in enumerate(sections) if section["title"] == title), None)
        if matched is None or not any(r["pointer"].startswith(f"/top_matchups/{index}/")
                                     and r["location"].startswith(f"sections/{matched}/") for r in references):
            raise NarrativeError("Missing Python-selected featured matchup")
    return result, references


def _scalar_paragraphs(value, path, prefix=""):
    """Deterministic fixture preview: labels and scalar references, no interpretation."""
    paragraphs = []
    if isinstance(value, dict):
        pairs = []
        for key, item in value.items():
            pointer = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            label = str(key).replace("_", " ")
            # Labels are Python-owned, but still go through the same numeric audit.
            if any(c.isnumeric() for c in label) or NUMBER_WORDS.search(label):
                label = "Metric"
            if isinstance(item, (dict, list)):
                paragraphs.extend(_scalar_paragraphs(item, pointer, prefix + label + ": "))
            elif item is not None and not isinstance(item, bool):
                pairs.append(label + ": {{" + pointer + "}}")
        if pairs:
            paragraphs.insert(0, prefix + "; ".join(pairs) + ".")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paragraphs.extend(_scalar_paragraphs(item, f"{path}/{index}", prefix))
    elif value is not None and not isinstance(value, bool):
        paragraphs.append(prefix + "{{" + path + "}}")
    return paragraphs[:100]


def preview_narrative(analysis):
    overview = _scalar_paragraphs(analysis.get("weekly_scoring", {}), "/weekly_scoring")
    sections = [{"title": SECTIONS[0], "paragraphs": overview or ["No scoring metrics are available."]}]
    for index, matchup in enumerate(analysis.get("top_matchups", [])[:3]):
        paragraphs = _scalar_paragraphs(matchup, f"/top_matchups/{index}")
        if paragraphs:
            sections.append({"title": SECTIONS[index + 1], "paragraphs": paragraphs})
    for title, key in [(SECTIONS[4], "transactions"), (SECTIONS[6], "standings"),
                       (SECTIONS[7], "team_trends"), (SECTIONS[8], "manager_analysis"),
                       (SECTIONS[9], "expected_wins"), (SECTIONS[11], "notable_events")]:
        paragraphs = _scalar_paragraphs(analysis.get(key), "/" + key)
        if paragraphs:
            sections.append({"title": title, "paragraphs": paragraphs})
    return {"sections": sections}


def grounded_fallback_narrative(analysis):
    sections = [{"title": "Week at a Glance", "paragraphs": [
        "{{/league_summary/league_name}} averaged {{/weekly_scoring/weekly_average_score}} points with a median of {{/weekly_scoring/weekly_median_score}}. The scoring range ran from {{/weekly_scoring/lowest_score}} to {{/weekly_scoring/highest_score}}.",
        "The highest combined matchup reached {{/weekly_scoring/highest_combined_score}}, while the lowest combined matchup reached {{/weekly_scoring/lowest_combined_score}}."
    ]}]
    titles = ["Matchup of the Week", "Second Featured Matchup", "Third Featured Matchup"]
    for index, _ in enumerate(analysis.get("top_matchups", [])[:3]):
        base = f"/top_matchups/{index}"
        sections.append({"title": titles[index], "paragraphs": [
            "{{" + base + "/winner}} beat {{" + base + "/loser}} by {{" + base + "/margin_of_victory}} in a matchup with {{" + base + "/combined_score}} combined points.",
            "Python selected this matchup with an interest score of {{" + base + "/interest_score}}. The winner ranked {{" + base + "/winner_weekly_score_rank}} in weekly scoring, while the losing side ranked {{" + base + "/loser_weekly_score_rank}}."
        ]})
    standing_paragraphs = []
    for index, row in enumerate(analysis.get("standings", [])[:6]):
        if row.get("current_rank") is None:
            continue
        base = f"/standings/{index}"
        standing_paragraphs.append("{{" + base + "/team}} sits at rank {{" + base + "/current_rank}} with a record of {{" + base + "/wins}}-{{" + base + "/losses}}-{{" + base + "/ties}} and {{" + base + "/points_for}} points for.")
    if standing_paragraphs:
        sections.append({"title": "Standings Movement", "paragraphs": standing_paragraphs})
    event_paragraphs = []
    for index, event in enumerate(analysis.get("notable_events", [])[:6]):
        if "team" in event:
            event_paragraphs.append("Notable event {{" + f"/notable_events/{index}/type" + "}} involved {{" + f"/notable_events/{index}/team" + "}}.")
    if event_paragraphs:
        sections.append({"title": "Other Notable Events", "paragraphs": event_paragraphs})
    return {"sections": sections}


def generate_report(analysis, *, api_key="", model="", no_llm=False,
                    provider="openai", ollama_url="http://127.0.0.1:11434"):
    if not isinstance(analysis.get("week"), int) or not isinstance(analysis.get("season"), int):
        raise NarrativeError("Report requires integer week and season")
    encoded = json.dumps(analysis, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    narrative = (preview_narrative(analysis) if no_llm else
                 generate_narrative(analysis, api_key=api_key, model=model,
                                    provider=provider, ollama_url=ollama_url))
    mode = "python_preview" if no_llm else provider
    fallback_reason = None
    try:
        sections, references = audit_narrative(narrative, analysis, preview=no_llm)
    except NarrativeError as exc:
        if no_llm or provider != "ollama":
            raise
        fallback_reason = str(exc)
        narrative = grounded_fallback_narrative(analysis)
        sections, references = audit_narrative(narrative, analysis)
        mode = "ollama_python_fallback"
    audit = {"schema_version": 1, "mode": mode,
             "email_eligible": not no_llm, "model": None if no_llm else model,
             "analysis_sha256": hashlib.sha256(encoded).hexdigest(),
             "templates": narrative, "references": references,
             "header_references": {"week": "/week", "season": "/season"}}
    if fallback_reason:
        audit["fallback_reason"] = fallback_reason
    return {"markdown": render_markdown(analysis["season"], analysis["week"], sections, preview=no_llm),
            "html": render_html(analysis["season"], analysis["week"], sections, preview=no_llm),
            "audit": audit}
