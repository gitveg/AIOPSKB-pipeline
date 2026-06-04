"""AIOps Knowledge Base Pipeline — CLI entry point."""

import sys
import argparse
import logging
from pathlib import Path

# Ensure src/ is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.console import Console
from rich.panel import Panel

from pipeline import AIOpsPipeline
from utils import read_output, save_output, format_timestamp

console = Console()


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="AIOps Knowledge Base Pipeline — Automated Multi-Agent Outline Generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py --full              # Run Stage 1-3 (generate the final outline)
  python src/main.py --stage 1           # Run only Stage 1 (cold start)
  python src/main.py --stage 2           # Run only Stage 2 (reviews) — requires Stage 1 output
  python src/main.py --stage 3           # Run only Stage 3 (synthesis) — requires Stage 1+2 output
  python src/main.py --full --verbose    # Full run with debug logging
        """,
    )
    parser.add_argument("--full", action="store_true", help="Run Stage 1-3 (outline generation)")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], help="Run a specific stage")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose/debug logging")
    args = parser.parse_args()

    if not args.full and args.stage is None:
        parser.print_help()
        console.print("\n[bold red]Error:[/] Please specify --full or --stage <number>")
        sys.exit(1)

    setup_logging(args.verbose)

    console.print(Panel.fit(
        "[bold]AIOps Knowledge Base Pipeline[/]\n"
        f"Start time: {format_timestamp()}\n"
        f"Mode: {'Full Pipeline' if args.full else f'Stage {args.stage} only'}",
        title="[bold magenta]Pipeline Launcher[/]",
        border_style="magenta",
    ))

    pipeline = AIOpsPipeline()

    try:
        if args.full:
            pipeline.run_full()
        elif args.stage == 1:
            pipeline.run_stage1()
        elif args.stage == 2:
            v01 = read_output("stage1_v0.1_skeleton.md")
            if not v01:
                console.print("[bold red]Error:[/] Stage 1 output not found. Run --stage 1 first.")
                sys.exit(1)
            pipeline.run_stage2(v01)
        elif args.stage == 3:
            v01 = read_output("stage1_v0.1_skeleton.md")
            if not v01:
                console.print("[bold red]Error:[/] Stage 1 output not found. Run --stage 1 first.")
                sys.exit(1)
            from utils import OUTPUT_DIR
            import os
            review_files = {
                "expert_a": read_output("stage2_reviews/expert_a_review.md"),
                "expert_b": read_output("stage2_reviews/expert_b_review.md"),
                "expert_c": read_output("stage2_reviews/expert_c_review.md"),
                "expert_d": read_output("stage2_reviews/expert_d_arbitration.md"),
            }
            missing = [k for k, v in review_files.items() if not v]
            if missing:
                console.print(f"[bold red]Error:[/] Missing Stage 2 reviews: {missing}. Run --stage 2 first.")
                sys.exit(1)
            pipeline.run_stage3(v01, review_files)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Pipeline interrupted by user.[/]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Pipeline failed:[/] {e}")
        if args.verbose:
            console.print_exception()
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold green]Done![/] Completed at {format_timestamp()}",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
