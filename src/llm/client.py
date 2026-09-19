"""Small stdlib LLM clients; configuration is explicit."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .prompts import REPORT_SCHEMA, SYSTEM_PROMPT


class NarrativeError(RuntimeError):
    """The report is unsafe or unavailable and must not be delivered."""


def _pointer_value(analysis, pointer):
    current = analysis
    for part in pointer.strip("/").split("/"):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    if current is None or isinstance(current, (dict, list, bool)):
        return None
    return current


def _compact_ollama_context(analysis):
    pointers = [
        ("/season", "season"),
        ("/week", "week"),
        ("/league_summary/league_name", "league name"),
        ("/league_summary/team_count", "team count"),
        ("/weekly_scoring/weekly_average_score", "weekly average score"),
        ("/weekly_scoring/weekly_median_score", "weekly median score"),
        ("/weekly_scoring/highest_score", "highest score"),
        ("/weekly_scoring/lowest_score", "lowest score"),
        ("/weekly_scoring/highest_combined_score", "highest combined score"),
        ("/weekly_scoring/lowest_combined_score", "lowest combined score"),
    ]
    for index, _ in enumerate(analysis.get("top_matchups", [])[:3]):
        base = f"/top_matchups/{index}"
        for key in ("home_team", "away_team", "winner", "loser", "winner_score",
                    "loser_score", "margin_of_victory", "combined_score",
                    "winner_weekly_score_rank", "loser_weekly_score_rank",
                    "interest_score"):
            pointers.append((f"{base}/{key}", f"featured matchup {index + 1} {key}"))
    for index, _ in enumerate(analysis.get("standings", [])[:8]):
        base = f"/standings/{index}"
        for key in ("team", "current_rank", "wins", "losses", "ties", "points_for"):
            pointers.append((f"{base}/{key}", f"standings {index + 1} {key}"))
    for index, event in enumerate(analysis.get("notable_events", [])[:8]):
        base = f"/notable_events/{index}"
        for key in event:
            pointers.append((f"{base}/{key}", f"notable event {index + 1} {key}"))
    menu = []
    for pointer, label in pointers:
        try:
            value = _pointer_value(analysis, pointer)
        except (KeyError, IndexError, TypeError, ValueError):
            value = None
        if value is not None:
            menu.append({"label": label, "pointer": pointer, "placeholder": "{{" + pointer + "}}",
                         "value": value})
    return {"instruction": "Use placeholders exactly as shown. Do not copy numeric values into prose.",
            "allowed_references": menu}


def _openai_narrative(analysis, *, api_key, model):
    if not api_key or not model:
        raise NarrativeError("OPENAI_API_KEY and OPENAI_MODEL are required for live reports")
    payload = {
        "model": model, "store": False,
        "instructions": SYSTEM_PROMPT,
        "input": "Untrusted league analysis data follows:\n" + json.dumps(analysis, allow_nan=False),
        "text": {"format": {"type": "json_schema", "name": "weekly_report",
                            "strict": True, "schema": REPORT_SCHEMA}},
    }
    request = Request("https://api.openai.com/v1/responses",
                      data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Never include provider bodies or request headers, which may contain secrets/data.
        raise NarrativeError(f"LLM request failed (HTTP {exc.code}); saved analysis can be retried") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise NarrativeError("LLM request failed; saved analysis can be retried") from None
    if result.get("status") != "completed":
        raise NarrativeError("LLM response was incomplete")
    texts = []
    for item in result.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "refusal":
                raise NarrativeError("LLM declined to generate the report")
            if part.get("type") == "output_text":
                texts.append(part.get("text", ""))
    try:
        return json.loads("".join(texts))
    except (ValueError, TypeError):
        raise NarrativeError("LLM returned invalid report JSON") from None


def _ollama_narrative(analysis, *, model, url):
    if not model:
        raise NarrativeError("OLLAMA_MODEL is required when LLM_PROVIDER=ollama")
    endpoint = urljoin(url.rstrip("/") + "/", "api/chat")
    local_prompt = SYSTEM_PROMPT + """

Local Ollama compliance rule: do not write any digit, score, rank, record, date,
ordinal, or number word unless it is inside one of the supplied {{/pointer}}
placeholders. Prefer short paragraphs. If a fact is not listed in the approved
reference menu, omit it.
"""
    payload = {
        "model": model,
        "stream": False,
        "format": REPORT_SCHEMA,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": local_prompt},
            {"role": "user", "content": "Approved reference menu follows:\n" +
             json.dumps(_compact_ollama_context(analysis), allow_nan=False)},
        ],
    }
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=240) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise NarrativeError(f"Ollama request failed (HTTP {exc.code}); saved analysis can be retried") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise NarrativeError("Ollama request failed; saved analysis can be retried") from None
    message = result.get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        raise NarrativeError("Ollama returned invalid report JSON") from None


def generate_narrative(analysis, *, api_key="", model="", provider="openai", ollama_url="http://127.0.0.1:11434"):
    if provider == "ollama":
        return _ollama_narrative(analysis, model=model, url=ollama_url)
    if provider != "openai":
        raise NarrativeError("Unsupported LLM provider")
    return _openai_narrative(analysis, api_key=api_key, model=model)
