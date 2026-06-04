"""Industrial PHM Knowledge Base Pipeline v5 — CLI entry point."""

import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rich.console import Console
from rich.panel import Panel

from pipeline import IndustrialPHMPipeline
from utils import read_output, format_timestamp

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
        description=(
            "Industrial PHM Knowledge Base Pipeline v5 — "
            "multi-model outline for industrial equipment / OT (PHM-centric)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py --full              # Run Stage 1-3 (complete pipeline)
  python src/main.py --stage 1           # Generate 3 drafts with Gemini/ChatGPT/DeepSeek
  python src/main.py --stage 2           # Cross-review drafts with Kimi
  python src/main.py --stage 3           # Synthesize final outline with Gemini
  python src/main.py --full --verbose    # Full run with debug logging
  python src/main.py --full --skip-connectivity-check   # Skip pre-flight LLM probe

Setup:
  1. cp .env.example .env
  2. Fill in .env (e.g. CHAT_API_KEY + CHAT_BASE_URL for relay Gemini/ChatGPT)
  3. pip install -r requirements.txt
        """,
    )
    parser.add_argument("--full", action="store_true", help="Run Stage 1-3 (complete pipeline)")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], help="Run a specific stage")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--skip-connectivity-check",
        action="store_true",
        help="Skip pre-flight LLM connectivity probe (not recommended)",
    )
    args = parser.parse_args()

    if not args.full and args.stage is None:
        parser.print_help()
        console.print("\n[bold red]Error:[/] Specify --full or --stage <1|2|3>")
        sys.exit(1)

    setup_logging(args.verbose)

    console.print(Panel.fit(
        "[bold]Industrial PHM Knowledge Base Pipeline v5[/]\n"
        f"Start time: {format_timestamp()}\n"
        f"Mode: {'Full Pipeline (Stage 1-3)' if args.full else f'Stage {args.stage} only'}",
        title="[bold magenta]Pipeline v5[/]",
        border_style="magenta",
    ))

    pipeline = IndustrialPHMPipeline()

    if not args.skip_connectivity_check:
        console.print("\n[bold cyan]连接检查[/] 正在探测本次任务所需的 LLM 端点…")
        try:
            pipeline.client.verify_required_endpoints(
                full=args.full,
                stage=args.stage,
            )
            console.print("[bold green]  全部端点可用[/]\n")
        except RuntimeError as e:
            console.print(f"[bold red]{e}[/]")
            console.print(
                "[dim]如需跳过检查（不推荐）：python src/main.py ... --skip-connectivity-check[/]\n"
            )
            sys.exit(2)

    try:
        if args.full:
            pipeline.run_full()

        elif args.stage == 1:
            pipeline.run_stage1()

        elif args.stage == 2:
            drafts = {
                "gemini": read_output("stage1_draft_a_gemini.md"),
                "chatgpt": read_output("stage1_draft_b_chatgpt.md"),
                "deepseek": read_output("stage1_draft_c_deepseek.md"),
            }
            missing = [k for k, v in drafts.items() if not v]
            if missing:
                console.print(f"[bold red]Error:[/] Missing Stage 1 drafts: {missing}. Run --stage 1 first.")
                sys.exit(1)
            pipeline.run_stage2(drafts)

        elif args.stage == 3:
            drafts = {
                "gemini": read_output("stage1_draft_a_gemini.md"),
                "chatgpt": read_output("stage1_draft_b_chatgpt.md"),
                "deepseek": read_output("stage1_draft_c_deepseek.md"),
            }
            review = read_output("stage2_review_report.md")

            missing_drafts = [k for k, v in drafts.items() if not v]
            if missing_drafts:
                console.print(f"[bold red]Error:[/] Missing Stage 1 drafts: {missing_drafts}. Run --stage 1 first.")
                sys.exit(1)
            if not review:
                console.print("[bold red]Error:[/] Missing Stage 2 review report. Run --stage 2 first.")
                sys.exit(1)
            pipeline.run_stage3(drafts, review)

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
