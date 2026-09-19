"""Resumable data -> facts -> narrative -> email workflow."""
import argparse
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import uuid

from src.config import Config, ROOT
from src.storage.history import History, read_json, write_json, write_text
from src.email.sender import send_report, validate_email_config

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--week', type=int)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--no-llm', action='store_true', help='Deterministic preview; never emails')
    p.add_argument('--force', action='store_true', help='Regenerate artifacts; never resends a delivered email')
    p.add_argument('--resend-email', action='store_true', help='Explicitly authorize another/uncertain delivery attempt')
    p.add_argument('--retry-email', action='store_true', help='Use saved report without ESPN, analytics or LLM')
    p.add_argument('--fixture', type=Path, help='Offline normalized snapshot; never emails')
    p.add_argument('--output-dir', type=Path, default=ROOT)
    p.add_argument('--fetch-only', action='store_true', help=argparse.SUPPRESS)
    return p

def run(args, config=None, client=None, analyzer=None, reporter=None, sender=None):
    config = config or Config.load(args.output_dir)
    offline = args.fixture is not None
    if args.week is not None and args.week < 1:
        raise ValueError('Week must be positive')
    if args.retry_email and (args.force or args.fixture or args.no_llm or args.fetch_only):
        raise ValueError('--retry-email cannot combine with regeneration or offline flags')
    snapshot = read_json(args.fixture) if offline else None
    if offline:
        config.league_id, config.season = snapshot['league_id'], snapshot['season']
        if args.week is not None and args.week != snapshot['week']:
            raise ValueError('Fixture week does not match --week')
        week = snapshot['week']
    else:
        if not config.league_id:
            raise ValueError('Set ESPN_LEAGUE_ID in .env first')
        week = args.week
    store = History(config.root, config.league_id, config.season)
    with store.lock():
        if week is None:
            if args.retry_email:
                raise ValueError('--retry-email requires --week')
            if client is None:
                from src.espn.client import ESPNClient
                client = ESPNClient(config.league_id, config.season, config.espn_s2, config.swid)
            week = client.latest_completed_week()
            if week is None:
                logging.info('No completed scoring period available')
                return 'no_completed_week'
        state = store.state(week)
        delivered = state.get('email_sent', False)
        if delivered and not (args.force or args.resend_email or args.dry_run or args.no_llm or args.fetch_only):
            return 'already_delivered'
        if not args.retry_email:
            history_path = store.path('history', week)
            if snapshot is not None or args.force or not history_path.exists():
                if snapshot is None:
                    if client is None:
                        from src.espn.client import ESPNClient
                        client = ESPNClient(config.league_id, config.season, config.espn_s2, config.swid)
                    raw, snapshot = client.fetch_week(week)
                else:
                    raw = {'fixture': True, 'snapshot': snapshot}
                write_json(store.path('raw', week), raw)
                if not snapshot.get('completed'):
                    raise ValueError('Scoring period is not completed')
                if (snapshot['league_id'], snapshot['season'], snapshot['week']) != (config.league_id, config.season, week):
                    raise ValueError('Snapshot identity mismatch')
                write_json(history_path, snapshot)
                state.update(data_retrieved=True, analysis_complete=False, report_generated=False)
                store.save_state(week, state)
            else:
                snapshot = read_json(history_path)
            if args.fetch_only:
                return 'data_validated'
            if analyzer is None:
                from src.analytics.engine import analyze
                analyzer = analyze
            if not state.get('analysis_complete') or args.force:
                analysis = analyzer(snapshot, store.prior(week))
                from src.analytics.engine import validate_analysis
                validate_analysis(analysis)
                write_json(store.path('processed', week), analysis)
                state.update(analysis_complete=True, report_generated=False)
                store.save_state(week, state)
            else:
                analysis = read_json(store.path('processed', week))
                from src.analytics.engine import validate_analysis
                validate_analysis(analysis)
            preview = bool(args.no_llm or offline)
            if not state.get('report_generated') or args.force or state.get('report_preview') != preview:
                if reporter is None:
                    from src.reports.weekly_report import generate_report
                    reporter = generate_report
                model = config.ollama_model if config.llm_provider == 'ollama' else config.model
                report = reporter(analysis, api_key=config.api_key, model=model, no_llm=preview,
                                  provider=config.llm_provider, ollama_url=config.ollama_url)
                write_text(store.path('md', week), report['markdown'])
                write_text(store.path('html', week), report['html'])
                write_json(store.path('audit', week), report['audit'])
                state.update(report_generated=True, report_preview=preview)
                store.save_state(week, state)
        if args.dry_run or args.no_llm or offline:
            return 'preview_generated'
        if delivered and not args.resend_email:
            return 'regenerated_without_resend'
        if not state.get('report_generated') or state.get('report_preview'):
            raise ValueError('No saved LLM report eligible for email')
        if state.get('delivery_status') in ('sending', 'uncertain') and not args.resend_email:
            raise RuntimeError('Delivery is uncertain. Check SMTP provider logs; --resend-email explicitly allows another attempt.')
        validate_email_config(config)
        markdown = store.path('md', week).read_text(encoding='utf-8')
        html = store.path('html', week).read_text(encoding='utf-8')
        message_id = f'<fantasy-{config.league_id}-{config.season}-{week}-{uuid.uuid4().hex}@fantasy-agent.local>'
        state.update(delivery_status='sending', message_id=message_id)
        store.save_state(week, state)
        try:
            (sender or send_report)(config, week=week, markdown=markdown, html=html, message_id=message_id)
        except Exception:
            state['delivery_status'] = 'uncertain'
            store.save_state(week, state)
            raise
        state.update(email_sent=True, delivery_status='sent', completed_at=datetime.now(timezone.utc).isoformat())
        store.save_state(week, state)
        return 'email_sent'

def main(argv=None):
    args = parser().parse_args(argv)
    log_dir = args.output_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[RotatingFileHandler(log_dir / 'weekly_job.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8'), logging.StreamHandler()])
    try:
        logging.info('Job started')
        result = run(args)
        logging.info('Job result: %s', result)
        print(result)
        return 0
    except Exception as exc:
        # Do not log external exception text: SDK/HTTP exceptions can contain credentials.
        logging.error('Job failed (%s). Check configuration, saved artifacts and provider status.', type(exc).__name__)
        print(f'Job failed: {type(exc).__name__}; see logs/weekly_job.log and README troubleshooting.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
