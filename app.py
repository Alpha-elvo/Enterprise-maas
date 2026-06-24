"""
app.py — CLI Entry Point
=========================
Run the pipeline from the command line without the Streamlit UI.

Usage:
    python app.py                        # Run default 5-domain matrix
    python app.py --json output.json     # Save JSON output
    python app.py --pdf  report.pdf      # Save PDF report
    python app.py --tenant acme_corp     # Specify tenant
    python app.py --health               # API health check only
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import config
from core.logger import get_logger
from core.orchestrator import Orchestrator, DEFAULT_INPUT_MATRIX
from services.report_generator import ReportGenerator
from storage.database import Database

log = get_logger("cli")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enterprise Decision Intelligence Platform — CLI Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python app.py
  python app.py --json results.json --pdf report.pdf
  python app.py --tenant hospital_1 --threshold 6
  python app.py --health
        """,
    )
    parser.add_argument("--tenant",    default=config.DEFAULT_TENANT, help="Tenant ID")
    parser.add_argument("--threshold", type=int, default=config.HIGH_IMPACT_THRESHOLD,
                        help="Impact gate threshold (1-10)")
    parser.add_argument("--json",      metavar="FILE", help="Save full JSON output to file")
    parser.add_argument("--pdf",       metavar="FILE", help="Save PDF report to file")
    parser.add_argument("--health",    action="store_true", help="Run API health check and exit")
    return parser.parse_args()


def run_health_check() -> None:
    print("\n🔌 Testing Groq API connection…")
    from services.groq_client import get_client
    health = get_client().health_check()
    print(json.dumps(health, indent=2))
    status = "✅ HEALTHY" if health["status"] == "healthy" else "❌ UNHEALTHY"
    print(f"\n{status}")
    sys.exit(0 if health["status"] == "healthy" else 1)


def main() -> None:
    args = parse_args()

    # Validate configuration
    errors = config.validate()
    if errors:
        for err in errors:
            print(f"[CONFIG ERROR] {err}")
        if not config.is_api_configured():
            print("\nSet GROQ_API_KEY in your .env file or as an environment variable.")
            sys.exit(1)

    if args.health:
        run_health_check()

    # Apply CLI overrides
    config.HIGH_IMPACT_THRESHOLD = args.threshold

    print("=" * 72)
    print(f"  ENTERPRISE DECISION INTELLIGENCE PLATFORM  v{config.APP_VERSION}")
    print(f"  Model    : {config.MODEL_ID}")
    print(f"  Tenant   : {args.tenant}")
    print(f"  Gate     : Score >= {args.threshold}")
    print(f"  Records  : {len(DEFAULT_INPUT_MATRIX)}")
    print("=" * 72)

    def progress_cb(stage: str, pct: float, msg: str) -> None:
        bar_width  = 30
        filled     = int(bar_width * pct)
        bar        = "█" * filled + "░" * (bar_width - filled)
        print(f"\r  [{bar}] {int(pct*100):>3}%  {msg:<50}", end="", flush=True)

    db  = Database()
    orc = Orchestrator(tenant_id=args.tenant, db=db)

    run = orc.execute(
        records=DEFAULT_INPUT_MATRIX,
        progress_cb=progress_cb,
    )
    print()  # newline after progress bar

    # Print summary
    summary = run.summary
    print("\n" + "─" * 72)
    print("  STATUS SUMMARY")
    print("─" * 72)
    print(f"  Run ID              : {run.run_id}")
    print(f"  Records Processed   : {summary.get('total_records_processed', 0)}")
    print(f"  Escalated           : {summary.get('escalated_records', 0)}")
    print(f"  Below Threshold     : {summary.get('below_threshold_records', 0)}")
    print(f"  Errors              : {summary.get('errors_encountered', 0)}")
    print(f"  Tokens Used         : {summary.get('total_tokens_used', 0):,}")
    print(f"  Execution (ms)      : {summary.get('total_execution_ms', 0):,}")
    print(f"  Highest Impact      : {summary.get('highest_impact_record', '—')}")

    # Domain score index
    domain_idx = summary.get("domain_score_index", {})
    if domain_idx:
        print("\n  Domain Score Index:")
        for rid, meta in domain_idx.items():
            score  = meta.get("impact_score", 0)
            filled = "█" * score + "░" * (10 - score)
            print(
                f"    {rid:<12} | {meta.get('domain',''):<28} "
                f"| [{filled}] {score:>2}/10 | {meta.get('urgency','')}"
            )

    print("\n" + "─" * 72)
    print(f"  global_state.json committed to: {config.STORAGE_DIR}")

    # Optional exports
    rg = ReportGenerator()

    if args.json:
        json_path = Path(args.json)
        json_path.write_text(rg.to_json(run), encoding="utf-8")
        print(f"  JSON saved to: {json_path}")

    if args.pdf:
        try:
            from services.pdf_exporter import PDFExporter
            pdf_path  = Path(args.pdf)
            exporter  = PDFExporter()
            pdf_bytes = exporter.export_run(run)
            pdf_path.write_bytes(pdf_bytes)
            print(f"  PDF saved to: {pdf_path}  ({len(pdf_bytes):,} bytes)")
        except RuntimeError as exc:
            print(f"  PDF export skipped: {exc}")

    print("=" * 72)
    print("  MULTI-AGENT LOOP TERMINATED CLEANLY")
    print("=" * 72)


if __name__ == "__main__":
    main()
