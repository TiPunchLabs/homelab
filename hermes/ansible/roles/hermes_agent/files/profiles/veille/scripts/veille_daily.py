"""Cron entry point: daily brief collection (cron scripts take no arguments)."""

import sys

from veille_collect import run_daily

sys.stdout.write(run_daily() + "\n")
