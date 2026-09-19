"""Render plain text safely as Markdown."""
import html
import re


def escape(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value).replace("\n", " ")


def render_markdown(season, week, sections, *, preview=False):
    lines = ["# Fantasy League Intelligence", f"## Week {week} — {season}", ""]
    if preview:
        lines.extend(["**Python-only preview — email delivery disabled.**", ""])
    for section in sections:
        lines.extend(["### " + escape(section["title"]), ""])
        for paragraph in section["paragraphs"]:
            lines.extend([escape(paragraph), ""])
    return "\n".join(lines)
