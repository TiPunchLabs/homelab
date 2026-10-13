"""Cron entry point: weekly synthesis material (cron scripts take no arguments)."""

import sys

from tech_watch_collect import run_weekly

sys.stdout.write(run_weekly() + "\n")
