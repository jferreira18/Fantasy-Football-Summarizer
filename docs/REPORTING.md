# Reporting agent

Python owns all facts, calculations, classifications and matchup selections. The reporting
agent calls the OpenAI Responses API with a strict JSON schema for sections and paragraph
templates. Configure `OPENAI_API_KEY` and `OPENAI_MODEL` later; there is no default model
or live API call during fixture tests. The configured model must support Structured Outputs.
API shape follows the [official Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

The model must write `{{/weekly_scoring/average}}`, never a literal number, for numerical
facts. This applies to spelled-out numbers and numeric names too. Python resolves references
to scalar fields in the saved analysis. Invalid references, nulls, containers, unreferenced
digits, common number words, omitted selected matchups, invalid sections, API refusals and
incomplete responses all stop reporting before delivery. Values are rendered as stored:
the reporter cannot round, compute a percentage or perform arithmetic in a template.

The audit contains original templates, each reference's JSON pointer and resolved value,
paragraph location, model and the SHA-256 of canonical analysis JSON. Header week and season
are taken directly from analysis. Save this audit beside the Markdown and HTML outputs.
The audit makes numerical sources inspectable; it does not prove that qualitative prose
correctly interprets a metric. Inspect initial live dry runs for semantics and units.

League and player names are untrusted data. Prompts explicitly reject instructions in
those fields. Rendering escapes every string; the model cannot provide HTML, scripts,
links or email addresses as active markup. Reports use fluid email tables and inline CSS
without JavaScript or externally loaded images.

`--no-llm` produces a deterministic Python-only preview with `audit.email_eligible=false`.
It lists available metrics and selected matchups so the complete fixture pipeline can
be inspected without credentials. The job must never email this preview. Live failures
raise `NarrativeError`; retry generation from saved analysis, never silently replace the
requested narrative with a preview and send it.
