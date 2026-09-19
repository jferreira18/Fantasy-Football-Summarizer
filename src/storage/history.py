"""Atomic JSON state and exclusive process lock, scoped to one league."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import tempfile

def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

class History:
    def __init__(self, root, league_id, season):
        self.root, self.league_id, self.season = Path(root), league_id, season

    def path(self, kind, week):
        if kind in ('md', 'html', 'audit'):
            suffix = 'audit.json' if kind == 'audit' else kind
            return self.root / 'reports' / str(self.season) / f'week_{week:02d}.{suffix}'
        suffix = '_analysis' if kind == 'processed' else ''
        return self.root / 'data' / kind / str(self.season) / f'week_{week:02d}{suffix}.json'

    def state(self, week):
        path = self.path('jobs', week)
        value = read_json(path) if path.exists() else {'league_id': self.league_id, 'season': self.season, 'week': week}
        if value['league_id'] != self.league_id:
            raise ValueError('This output directory belongs to a different league')
        return value

    def save_state(self, week, state):
        write_json(self.path('jobs', week), state)

    def prior(self, week):
        folder = self.root / 'data' / 'history' / str(self.season)
        snapshots = [read_json(p) for p in sorted(folder.glob('week_*.json'))]
        return [s for s in snapshots if s['week'] < week and s['season'] == self.season and s['league_id'] == self.league_id]

    @contextmanager
    def lock(self):
        path = self.root / 'data' / 'job.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError('Job lock exists. Confirm no job is running before removing data/job.lock.') from None
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(str(os.getpid()))
            identity = self.root / 'data' / 'league.json'
            if identity.exists() and read_json(identity)['league_id'] != self.league_id:
                raise ValueError('Use a separate output directory for each ESPN league')
            write_json(identity, {'league_id': self.league_id})
            yield
        finally:
            path.unlink(missing_ok=True)
