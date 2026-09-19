"""Phase-one ESPN connection and normalization command."""
import sys
from src.jobs.weekly_job import main

if __name__ == '__main__':
    raise SystemExit(main([*sys.argv[1:], '--fetch-only']))
