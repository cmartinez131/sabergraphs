# data_pipeline/ingest/cli.py
"""Command-line entry for the ingestion pipeline. Run from the repo root:

    python -m data_pipeline.ingest.cli chadwick
    python -m data_pipeline.ingest.cli statcast --start 2024-06-03 --end 2024-06-16
    python -m data_pipeline.ingest.cli statcast              # config seasons, resumable
    python -m data_pipeline.ingest.cli bat-tracking
    python -m data_pipeline.ingest.cli marts
    python -m data_pipeline.ingest.cli backfill-all          # the overnight command
    python -m data_pipeline.ingest.cli status [--source statcast_pitches]

Uses DATABASE_URL if set; defaults to the host-side compose URL
(postgresql+psycopg2://user:password@localhost:5432/baseball_db).
"""
import argparse
import logging
import sys
from datetime import date

from . import runner
from .build_marts import build_marts
from .config import load_config
from .db import get_engine

logger = logging.getLogger("ingest.cli")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _report(source: str, completed, failed) -> int:
    logger.info("%s: %d chunks completed, %d failed", source, len(completed), len(failed))
    if failed:
        logger.error("%s: FAILED chunks (rerun the same command to retry): %s", source, failed)
        return 1
    return 0


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    ap = argparse.ArgumentParser(
        prog="python -m data_pipeline.ingest.cli",
        description="Resumable, idempotent statcast ingestion pipeline",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_sc = sub.add_parser("statcast", help="backfill pitch-level statcast (weekly chunks)")
    p_sc.add_argument("--start", type=_parse_date, help="override window start (YYYY-MM-DD)")
    p_sc.add_argument("--end", type=_parse_date, help="override window end (YYYY-MM-DD)")
    p_sc.add_argument("--seasons", type=int, nargs="+", help="override config seasons")

    p_bt = sub.add_parser("bat-tracking", help="load Savant bat-tracking season leaderboards")
    p_bt.add_argument("--seasons", type=int, nargs="+", help="override config seasons")

    p_ch = sub.add_parser("chadwick", help="load the Chadwick MLBAM/FanGraphs/BBRef crosswalk")
    p_ch.add_argument("--refresh", action="store_true", help="re-fetch even if already loaded")

    sub.add_parser("marts", help="build/refresh mart tables from staging views")
    sub.add_parser("backfill-all", help="chadwick -> statcast -> bat-tracking -> marts")

    p_st = sub.add_parser("status", help="show watermark progress")
    p_st.add_argument("--source")

    args = ap.parse_args(argv)
    if args.cmd == "statcast" and bool(args.start) != bool(args.end):
        ap.error("--start and --end must be given together")

    cfg = load_config()
    engine = get_engine()
    code = 0

    if args.cmd == "statcast":
        completed, failed = runner.run_statcast(engine, cfg, args.start, args.end, args.seasons)
        code = _report("statcast", completed, failed)
    elif args.cmd == "bat-tracking":
        if args.seasons:
            cfg.bat_tracking.seasons = args.seasons
        completed, failed = runner.run_bat_tracking(engine, cfg)
        code = _report("bat_tracking", completed, failed)
    elif args.cmd == "chadwick":
        completed, failed = runner.run_chadwick(engine, cfg, refresh=args.refresh)
        code = _report("chadwick", completed, failed)
    elif args.cmd == "marts":
        build_marts(engine)
    elif args.cmd == "backfill-all":
        code = 0
        _, ch_failed = runner.run_chadwick(engine, cfg)
        code |= 1 if ch_failed else 0
        sc_completed, sc_failed = runner.run_statcast(engine, cfg)
        code |= _report("statcast", sc_completed, sc_failed)
        bt_completed, bt_failed = runner.run_bat_tracking(engine, cfg)
        code |= _report("bat_tracking", bt_completed, bt_failed)
        build_marts(engine)  # partial marts are fine; rerun refreshes
    elif args.cmd == "status":
        summary = runner.get_status(engine, args.source)
        print(f"chunks by status: {summary['chunks']}")
        print(f"rows in completed chunks: {summary['completed_row_count']}")
        for e in summary["entries"]:
            if e["status"] != "completed":
                print(f"  {e['source']} {e['chunk_key']}: {e['status']}"
                      f" (attempt {e['attempt']}) {e.get('error') or ''}")

    sys.exit(code)


if __name__ == "__main__":
    main()
