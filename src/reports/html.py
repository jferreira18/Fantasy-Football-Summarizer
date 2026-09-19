"""Email-compatible, inline-styled HTML, never model-provided markup."""
from html import escape


def render_html(season, week, sections, *, preview=False):
    cards = []
    for section in sections:
        paragraphs = "".join('<p style="margin:12px 0;line-height:1.65;color:#26344b">'
                             + escape(p) + '</p>' for p in section["paragraphs"])
        cards.append('<tr><td style="padding:22px 24px;border-bottom:1px solid #e2e8f0">'
                     '<h2 style="margin:0;color:#0f766e;font-size:20px">'
                     + escape(section["title"]) + '</h2>' + paragraphs + '</td></tr>')
    banner = ('<p style="color:#fde68a">Python-only preview — email delivery disabled.</p>'
              if preview else '')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Fantasy League Intelligence</title></head>'
            '<body style="margin:0;background:#eef2f6;font-family:Arial,sans-serif">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            '<td align="center" style="padding:16px 8px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:680px;background:#fff;border-collapse:collapse;overflow-wrap:anywhere">'
            '<tr><td style="padding:28px 24px;background:#14283f;color:#fff">'
            '<p style="font-size:12px;letter-spacing:2px;color:#5eead4">THE WEEKLY LEAGUE REPORT</p>'
            '<h1 style="margin:8px 0;font-size:28px">Fantasy League Intelligence</h1>'
            f'<p style="margin:8px 0">Week {escape(str(week))} · {escape(str(season))} Season</p>'
            + banner + '</td></tr>' + ''.join(cards)
            + '<tr><td style="padding:20px 24px;color:#64748b;font-size:12px">'
            'Statistics calculated in Python. Narrative references are preserved in the report audit.'
            '</td></tr></table></td></tr></table></body></html>')
