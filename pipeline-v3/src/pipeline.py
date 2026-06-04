"""AIOps Knowledge Base Pipeline — Stage execution logic."""

import re
import logging
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from api_client import AgentRouter, LLMClient
from utils import (
    load_prompt,
    save_output,
    read_output,
    format_timestamp,
    Timer,
    TokenTracker,
)

console = Console()
logger = logging.getLogger(__name__)


def _log_stage(stage: str, message: str):
    console.print(f"\n[bold blue][{stage}][/] {message}")


def _log_success(message: str):
    console.print(f"[bold green]  OK:[/] {message}")


def _log_warn(message: str):
    console.print(f"[bold yellow]  WARN:[/] {message}")


class AIOpsPipeline:
    """Orchestrates the 5-stage AIOps knowledge base generation pipeline."""

    def __init__(self):
        self.token_tracker = TokenTracker()
        self.client = LLMClient(token_tracker=self.token_tracker)
        self.router = AgentRouter(self.client)
        self.orchestrator_prompt = load_prompt("orchestrator.yaml")
        self.expert_a_prompt = load_prompt("expert_a.yaml")
        self.expert_b_prompt = load_prompt("expert_b.yaml")
        self.expert_c_prompt = load_prompt("expert_c.yaml")
        self.expert_d_prompt = load_prompt("expert_d.yaml")

    # ── Stage 1: Cold Start ────────────────────────────────────

    def run_stage1(self) -> str:
        _log_stage("Stage 1", "Generating V0.1 knowledge skeleton...")
        with Timer("Stage 1") as t:
            result = self.router.call_agent(
                agent="orchestrator",
                system_prompt=self.orchestrator_prompt["stage1_system"],
                user_prompt=self.orchestrator_prompt["stage1_user"],
                stage="stage1",
                temperature=0.7,
                max_tokens=16384,
            )
        path = save_output(result, "stage1_v0.1_skeleton.md")
        _log_success(f"V0.1 skeleton saved to {path} ({t.elapsed:.1f}s)")
        return result

    # ── Stage 2: Multi-Agent Review ────────────────────────────

    def run_stage2(self, v01_skeleton: str) -> dict:
        _log_stage("Stage 2", "Running 4-agent parallel review...")

        reviews = {}
        agents = [
            ("expert_a", self.expert_a_prompt, "stage2_review_a"),
            ("expert_b", self.expert_b_prompt, "stage2_review_b"),
            ("expert_c", self.expert_c_prompt, "stage2_review_c"),
        ]

        with Timer("Stage 2 (Reviews)") as t:
            for agent_name, prompt_config, stage_label in agents:
                _log_stage("Stage 2", f"Calling {agent_name}...")
                user_msg = prompt_config["user_prompt_template"].format(
                    v01_skeleton=v01_skeleton
                )
                result = self.router.call_agent(
                    agent=agent_name,
                    system_prompt=prompt_config["system_prompt"],
                    user_prompt=user_msg,
                    stage=stage_label,
                    temperature=0.5,
                    max_tokens=16384,
                )
                reviews[agent_name] = result
                filename = f"stage2_reviews/{agent_name}_review.md"
                save_output(result, filename)
                _log_success(f"{agent_name} review saved ({filename})")

        # Expert D: Arbitration
        _log_stage("Stage 2", "Running Expert D arbitration...")
        with Timer("Stage 2 (Arbitration)") as t2:
            arb_user = self.expert_d_prompt["user_prompt_template_stage2"].format(
                review_a=reviews["expert_a"],
                review_b=reviews["expert_b"],
                review_c=reviews["expert_c"],
                v01_skeleton=v01_skeleton,
            )
            arbitration = self.router.call_agent(
                agent="expert_d",
                system_prompt=self.expert_d_prompt["system_prompt_stage2"],
                user_prompt=arb_user,
                stage="stage2_arbitration",
                temperature=0.3,
                max_tokens=16384,
            )

        save_output(arbitration, "stage2_reviews/expert_d_arbitration.md")
        _log_success(f"Arbitration report saved ({t2.elapsed:.1f}s)")
        reviews["expert_d"] = arbitration

        console.print(f"\n[bold]Stage 2 complete[/] (total {t.elapsed:.1f}s)")
        return reviews

    # ── Stage 3: Synthesis & Convergence ───────────────────────

    def run_stage3(self, v01_skeleton: str, reviews: dict) -> str:
        _log_stage("Stage 3", "Generating V1.0 framework via synthesis...")

        max_iterations = 3
        for iteration in range(1, max_iterations + 1):
            _log_stage("Stage 3", f"Iteration {iteration}/{max_iterations}")

            with Timer(f"Stage 3 (Iteration {iteration})") as t:
                user_msg = self.orchestrator_prompt["stage3_user"].format(
                    v01_skeleton=v01_skeleton,
                    review_a=reviews["expert_a"],
                    review_b=reviews["expert_b"],
                    review_c=reviews["expert_c"],
                    arbitration_d=reviews["expert_d"],
                )
                v10_framework = self.router.call_agent(
                    agent="orchestrator",
                    system_prompt=self.orchestrator_prompt["stage3_system"],
                    user_prompt=user_msg,
                    stage=f"stage3_iter{iteration}",
                    temperature=0.5,
                    max_tokens=32768,
                )

            # Quality gate: Expert D review
            _log_stage("Stage 3", "Expert D quality gate...")
            qa_user = self.expert_d_prompt["user_prompt_template_stage3_qa"].format(
                v01_skeleton=v01_skeleton,
                v10_framework=v10_framework,
                arbitration_d=reviews["expert_d"],
            )
            qa_result = self.router.call_agent(
                agent="expert_d",
                system_prompt=self.expert_d_prompt["system_prompt_stage3_qa"],
                user_prompt=qa_user,
                stage=f"stage3_qa_iter{iteration}",
                temperature=0.2,
                max_tokens=8192,
            )

            passed = "**通过**" in qa_result or "通过" in qa_result.split("最终结论")[-1] if "最终结论" in qa_result else "**通过**" in qa_result

            save_output(qa_result, f"stage3_qa_iteration{iteration}.md")

            if passed:
                _log_success(f"V1.0 framework passed quality gate (iteration {iteration}, {t.elapsed:.1f}s)")
                path = save_output(v10_framework, "stage3_v1.0_framework.md")
                _log_success(f"V1.0 framework saved to {path}")
                return v10_framework
            else:
                _log_warn(f"V1.0 did not pass quality gate (iteration {iteration}). Refining...")
                # Feed back QA result for next iteration
                reviews["expert_d"] = qa_result

        _log_warn(f"Max iterations ({max_iterations}) reached. Saving last version.")
        path = save_output(v10_framework, "stage3_v1.0_framework.md")
        return v10_framework

    # ── Stage 4: Deep Dive ─────────────────────────────────────

    def run_stage4(self, v10_framework: str) -> list[dict]:
        _log_stage("Stage 4", "Extracting P0/P1 modules for deep dive...")

        modules = self._extract_modules(v10_framework)
        _log_success(f"Found {len(modules)} modules for deep dive")

        knowledge_pages = []
        total = len(modules)

        for idx, mod in enumerate(modules, 1):
            module_name = mod["name"]
            console.print(f"\n[bold cyan]  [{idx}/{total}] Processing: {module_name}[/]")

            # Step 1: Generate draft
            with Timer(f"Stage 4 [{module_name}] generate") as t:
                gen_user = self.orchestrator_prompt["stage4_generate_user"].format(
                    module_name=module_name,
                    parent_domain=mod.get("parent", ""),
                    priority=mod.get("priority", "P1"),
                    maturity_level=mod.get("maturity", "L2"),
                    framework_context=v10_framework[:8000],
                )
                draft = self.router.call_agent(
                    agent="orchestrator",
                    system_prompt=self.orchestrator_prompt["stage4_generate_system"],
                    user_prompt=gen_user,
                    stage=f"stage4_gen_{idx}",
                    temperature=0.7,
                    max_tokens=16384,
                )

            # Step 2: Expert B verification
            _log_stage("Stage 4", f"  Expert B verifying {module_name}...")
            verify_user = self.expert_b_prompt["stage4_verify_user"].format(
                module_name=module_name,
                draft_content=draft,
            )
            b_feedback = self.router.call_agent(
                agent="expert_b",
                system_prompt=self.expert_b_prompt["stage4_verify_system"],
                user_prompt=verify_user,
                stage=f"stage4_verify_{idx}",
                temperature=0.4,
                max_tokens=8192,
            )

            # Step 3: Refine
            _log_stage("Stage 4", f"  Refining {module_name}...")
            refine_user = self.orchestrator_prompt["stage4_refine_user"].format(
                draft_content=draft,
                expert_b_feedback=b_feedback,
            )
            refined = self.router.call_agent(
                agent="orchestrator",
                system_prompt=self.orchestrator_prompt["stage4_refine_system"],
                user_prompt=refine_user,
                stage=f"stage4_refine_{idx}",
                temperature=0.5,
                max_tokens=16384,
            )

            # Step 4: Expert D QA
            _log_stage("Stage 4", f"  Expert D quality check {module_name}...")
            qa_user = self.expert_d_prompt["user_prompt_template_stage4_qa"].format(
                module_name=module_name,
                priority=mod.get("priority", "P1"),
                maturity_level=mod.get("maturity", "L2"),
                knowledge_page=refined,
            )
            qa_result = self.router.call_agent(
                agent="expert_d",
                system_prompt=self.expert_d_prompt["system_prompt_stage4_qa"],
                user_prompt=qa_user,
                stage=f"stage4_qa_{idx}",
                temperature=0.2,
                max_tokens=4096,
            )

            passed = "**通过**" in qa_result or "通过" in qa_result.split("最终结论")[-1] if "最终结论" in qa_result else "**通过**" in qa_result

            # One retry if failed
            if not passed:
                _log_warn(f"  {module_name} QA failed, retrying refine...")
                refine_user2 = self.orchestrator_prompt["stage4_refine_user"].format(
                    draft_content=refined,
                    expert_b_feedback=qa_result,
                )
                refined = self.router.call_agent(
                    agent="orchestrator",
                    system_prompt=self.orchestrator_prompt["stage4_refine_system"],
                    user_prompt=refine_user2,
                    stage=f"stage4_refine2_{idx}",
                    temperature=0.5,
                    max_tokens=16384,
                )

            # Save
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', module_name)
            save_output(refined, f"stage4_deep_dive/{safe_name}.md")
            _log_success(f"  {module_name} complete ({t.elapsed:.1f}s)")

            knowledge_pages.append({
                "name": module_name,
                "content": refined,
                "priority": mod.get("priority", "P1"),
                "maturity": mod.get("maturity", "L2"),
            })

        return knowledge_pages

    def _extract_modules(self, framework: str) -> list[dict]:
        """Extract P0/P1 module names from V1.0 framework text."""
        modules = []
        lines = framework.split("\n")
        current_parent = ""

        for line in lines:
            # Track parent domain from ## headers
            h2_match = re.match(r'^##\s+(\d+\.?\s*.*)', line)
            if h2_match:
                current_parent = h2_match.group(1).strip()
                continue

            # Extract priority tags
            p_match = re.search(r'[Pp][012]\b', line)
            if not p_match:
                continue
            priority = p_match.group(0).upper()

            # Skip P2 modules
            if priority == "P2":
                continue

            # Extract maturity level
            m_match = re.search(r'[Ll][0-4]\b', line)
            maturity = m_match.group(0).upper() if m_match else "L2"

            # Clean module name
            name = re.sub(r'[Pp][012]\b', '', line)
            name = re.sub(r'[Ll][0-4]\b', '', name)
            name = re.sub(r'^[#\-*\s]+', '', name).strip()
            name = re.sub(r'\s*[\|│]\s*', ' ', name).strip()

            if len(name) > 3 and len(name) < 100:
                modules.append({
                    "name": name,
                    "parent": current_parent,
                    "priority": priority,
                    "maturity": maturity,
                })

        # Deduplicate by name
        seen = set()
        unique = []
        for m in modules:
            key = m["name"]
            if key not in seen:
                seen.add(key)
                unique.append(m)

        return unique

    # ── Stage 5: Final Assembly ────────────────────────────────

    def run_stage5(self, knowledge_pages: list[dict], v10_framework: str) -> dict:
        _log_stage("Stage 5", "Assembling final deliverables...")

        # Build concatenated knowledge pages summary
        pages_summary = ""
        for kp in knowledge_pages:
            pages_summary += f"\n### {kp['name']} (priority: {kp['priority']}, maturity: {kp['maturity']})\n"
            pages_summary += kp["content"][:2000] + "\n\n[...]\n\n"

        with Timer("Stage 5") as t:
            user_msg = self.orchestrator_prompt["stage5_user"].format(
                all_knowledge_pages=pages_summary,
            )
            final_output = self.router.call_agent(
                agent="orchestrator",
                system_prompt=self.orchestrator_prompt["stage5_system"],
                user_prompt=user_msg,
                stage="stage5",
                temperature=0.5,
                max_tokens=32768,
            )

        # Try to split the output into separate deliverables
        deliverables = self._split_final_output(final_output)

        for name, content in deliverables.items():
            path = save_output(content, f"stage5_final/{name}.md")
            _log_success(f"Deliverable saved: {path}")

        # Also copy individual knowledge pages into final output
        for kp in knowledge_pages:
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', kp["name"])
            save_output(kp["content"], f"stage5_final/knowledge_pages/{safe_name}.md")

        _log_success(f"Stage 5 complete ({t.elapsed:.1f}s)")
        return deliverables

    def _split_final_output(self, output: str) -> dict:
        """Split the LLM output into separate deliverable files."""
        deliverables = {
            "01_主知识库文档": "",
            "02_成熟度演进路径图": "",
            "03_工具全景对比矩阵": "",
            "04_快速决策速查卡": "",
        }

        sections = re.split(r'(?=##\s+\d+\.)', output)
        if len(sections) < 2:
            deliverables["01_主知识库文档"] = output
            return deliverables

        for section in sections:
            if not section.strip():
                continue
            lower = section[:200].lower()
            if "主知识库" in lower or "目录" in lower or "1." in lower[:10]:
                deliverables["01_主知识库文档"] = section
            elif "成熟度" in lower or "演进" in lower or "l0" in lower:
                deliverables["02_成熟度演进路径图"] = section
            elif "工具全景" in lower or "工具对比" in lower or "矩阵" in lower:
                deliverables["03_工具全景对比矩阵"] = section
            elif "决策" in lower or "速查" in lower:
                deliverables["04_快速决策速查卡"] = section
            else:
                deliverables["01_主知识库文档"] += "\n\n" + section

        return deliverables

    # ── Full Pipeline (Stage 1-3: Outline Generation) ──────────

    def run_full(self):
        console.print("\n[bold magenta]═══════════════════════════════════════════════════[/]")
        console.print("[bold magenta]  AIOps Knowledge Base Pipeline — Outline Generation[/]")
        console.print("[bold magenta]  (Stage 1-3: Cold Start → Review → Synthesis)[/]")
        console.print("[bold magenta]═══════════════════════════════════════════════════[/]\n")

        # Stage 1
        v01 = self.run_stage1()

        # Stage 2
        reviews = self.run_stage2(v01)

        # Stage 3
        v10 = self.run_stage3(v01, reviews)

        # Summary
        console.print("\n[bold magenta]═══════════════════════════════════════════════════[/]")
        console.print("[bold green]  Pipeline completed successfully![/]")
        console.print("[bold]  Final output: output/stage3_v1.0_framework.md[/]")
        console.print(self.token_tracker.summary())
        console.print("[bold magenta]═══════════════════════════════════════════════════[/]\n")

        return v10
