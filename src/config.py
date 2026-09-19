from dataclasses import dataclass, field
from pathlib import Path
import os
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not key.strip().replace('_', '').isalnum():
            raise ValueError('Invalid .env assignment')
        os.environ.setdefault(key.strip(), value.strip().strip('\"\''))

@dataclass
class Config:
    root: Path = ROOT
    league_id: int = 0
    season: int = 2026
    espn_s2: str = field(default='', repr=False)
    swid: str = field(default='', repr=False)
    llm_provider: str = 'openai'
    api_key: str = field(default='', repr=False)
    model: str = ''
    ollama_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = ''
    report_email: str = ''
    email_from: str = ''
    email_provider: str = 'smtp'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_user: str = ''
    smtp_password: str = field(default='', repr=False)
    smtp_security: str = 'starttls'
    timezone: str = 'America/Chicago'
    report_hour: int = 7

    @classmethod
    def load(cls, root=ROOT):
        root = Path(root).resolve()
        load_dotenv(root / '.env')
        e = os.environ
        config = cls(root=root, league_id=int(e.get('ESPN_LEAGUE_ID') or 0),
            season=int(e.get('ESPN_SEASON') or 2026), espn_s2=e.get('ESPN_S2',''),
            swid=e.get('ESPN_SWID',''), llm_provider=(e.get('LLM_PROVIDER') or 'openai').lower(),
            api_key=e.get('OPENAI_API_KEY',''), model=e.get('OPENAI_MODEL',''),
            ollama_url=e.get('OLLAMA_URL') or 'http://127.0.0.1:11434',
            ollama_model=e.get('OLLAMA_MODEL',''),
            report_email=e.get('REPORT_EMAIL',''), email_from=e.get('EMAIL_FROM',''),
            email_provider=e.get('EMAIL_PROVIDER') or 'smtp', smtp_host=e.get('SMTP_HOST',''),
            smtp_port=int(e.get('SMTP_PORT') or 587), smtp_user=e.get('SMTP_USER',''),
            smtp_password=e.get('SMTP_PASSWORD',''), smtp_security=e.get('SMTP_SECURITY') or 'starttls',
            timezone=e.get('TIMEZONE') or 'America/Chicago', report_hour=int(e.get('REPORT_HOUR') or 7))
        if not 0 <= config.report_hour <= 23:
            raise ValueError('REPORT_HOUR must be 0..23')
        if config.llm_provider not in ('openai', 'ollama'):
            raise ValueError('LLM_PROVIDER must be openai or ollama')
        return config
