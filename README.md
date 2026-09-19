# ESPN Fantasy League Intelligence

Python retrieves ESPN data and calculates the facts. A separate narrative stage explains them; an SMTP delivery stage emails the HTML report. Runs independently of Codex. The original, unmodified requirements are in [PRD.md](PRD.md).

## Quick start

Python 3.11 or later:

```powershell
cd C:\Users\jferr\OneDrive\Desktop\FF_SUMM
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally. Configure `ESPN_LEAGUE_ID`, season, private-league `ESPN_S2` and `ESPN_SWID` cookies, recipient and SMTP settings. Narrative generation defaults to local Ollama with `LLM_PROVIDER=ollama`, `OLLAMA_URL=http://127.0.0.1:11434`, and `OLLAMA_MODEL=qwen2.5:7b`; set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and an OpenAI model only if you want hosted generation. Never share or commit cookies, API keys or SMTP credentials. Public leagues can leave cookies empty. Use a provider app password where required. SMTP transport supports authenticated STARTTLS (usually port 587) and TLS (usually port 465). There is no live delivery until settings are supplied.

## Commands

Run commands from this directory with the virtual environment's Python:

```powershell
# Offline example: no ESPN, OpenAI or email calls
python -m src.jobs.weekly_job --fixture tests/fixtures/demo_week_01.json --no-llm --output-dir demo-output

# Phase 1: retrieve and normalize a completed week
python -m src.main --week 2

# Deterministic analytics and preview only; never sends email
python -m src.jobs.weekly_job --week 2 --no-llm

# Live LLM report, without delivery
python -m src.jobs.weekly_job --week 2 --dry-run

# Most recently completed scoring period; sends if not already delivered
python -m src.jobs.weekly_job

# Regenerate; does NOT resend an already delivered report
python -m src.jobs.weekly_job --week 2 --force --dry-run

# Use the saved report; no ESPN, analytics or LLM calls
python -m src.jobs.weekly_job --week 2 --retry-email

# Explicitly authorize a second send, or resolve an uncertain send after checking provider logs
python -m src.jobs.weekly_job --week 2 --retry-email --resend-email

python -m unittest discover -s tests -v
```

`--force` can send a previously undelivered report during a normal live run. Use `--dry-run` when regenerating for inspection. `--no-llm` and fixtures always suppress email. Cached normalized data and validated analytics are reused after a downstream failure. `--force` re-fetches and recomputes. Each output directory belongs to a single league. Use separate directories for different leagues; `--output-dir` also selects the `.env` location. Demo output is isolated from real league history.

## Four stages

1. `src/espn`: private/public ESPN retrieval, completion checks and normalization.
2. `src/analytics`: reproducible statistics, historical comparisons, legal lineup optimization and matchup selection.
3. `src/llm` and `src/reports`: grounded local Ollama or optional OpenAI narrative with metric references, Markdown, email HTML and audit file.
4. `src/email` and `src/jobs`: encrypted SMTP, durable state, scheduling and failure recovery.

These are independently testable application stages; runtime does not require development agents or Codex. Consult [ESPN behavior](docs/ESPN.md), [metric definitions](docs/METRICS.md), [report grounding](docs/REPORTING.md), and [internal contract](docs/CONTRACT.md).

## Saved artifacts

For each week, `data/raw/2026/week_02.json`, `data/history/2026/week_02.json`, `data/processed/2026/week_02_analysis.json`, and `reports/2026/week_02.md`, `.html`, `.audit.json` are saved. Delivery state is in `data/jobs/2026/week_02.json`; logs rotate in `logs/weekly_job.log`. Reports and normalized history contain league information and should be kept private.

Historical analytics only cover collected snapshots. Backfill earlier completed weeks with `--no-llm` before generating the latest report. Unavailable ESPN data is labeled; absent transaction access is not evidence that no manager made moves. Historical official standings and multi-period matchups have limitations documented in `docs/ESPN.md`. This implementation must still be compared against your real league before unattended deployment.

## Scheduling

The persistent scheduler uses `TIMEZONE` and `REPORT_HOUR` (default Tuesday 07:00 America/Chicago). It runs a catch-up check on startup and hourly recovery checks; successful weeks are suppressed by delivery state. New reports may therefore be delivered on a recovery check when ESPN finalizes late. Keep the host awake and connected. Time-zone data is supplied by `tzdata` on Windows.

For Windows, after configuration and manual dry-run validation:

```powershell
.\deploy\register-task.ps1
Start-ScheduledTask -TaskName 'Fantasy League Intelligence'
```

This registers a process at sign-in and requires the user to stay signed in. For an always-on Raspberry Pi/Linux host, create a dedicated `fantasy` user, place the project at `/opt/fantasy-agent`, create its virtual environment, configure its `.env`, and install `deploy/fantasy-agent.service` with systemd. Adjust the supplied paths/user for your host, then enable/start that service. No scheduler is installed automatically during development.

## Failure recovery and delivery guarantees

An exclusive `data/job.lock` prevents overlapping runs. A crash may leave the lock behind: first verify there is no running process, then remove only that lock. Atomic writes preserve completed artifacts. A week is marked delivered only after SMTP accepts the message.

SMTP cannot guarantee exactly-once delivery across a network failure. The job records `sending` before contacting SMTP; interrupted/failed sends become `uncertain` and are never retried automatically. Check provider logs and the stored Message-ID before using `--resend-email`. SMTP acceptance does not prove inbox receipt. Previously successful delivery state remains preserved across regeneration.

For a failed run, inspect the last completed artifact/state stage. Logs intentionally omit external exception text to avoid exposing secrets. Check missing configuration, API access, provider status and ESPN response changes; optional data limitations appear in snapshot warnings. No partial report is emailed after a fetch, analytics, validation or narrative failure.

## Status

Implemented and tested with synthetic fixtures and mocked transports. Live ESPN access, live LLM output, real email receipt and production scheduling require your settings and a deployment validation pass. The full PRD is the target; provider-dependent data and league-specific edge cases remain subject to those live checks.

API reference used: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Local narrative generation uses Ollama's HTTP chat endpoint when `LLM_PROVIDER=ollama`.
