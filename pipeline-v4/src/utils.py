"""Utility functions for the AIOps Knowledge Base Pipeline v4."""

import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PIPELINE_ROOT / "output"

# Load .env on import
_env_path = PIPELINE_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def save_output(content: str, relative_path: str) -> Path:
    full_path = OUTPUT_DIR / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return full_path


def read_output(relative_path: str) -> str:
    full_path = OUTPUT_DIR / relative_path
    if not full_path.exists():
        return ""
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def format_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Timer:
    def __init__(self, label: str = ""):
        self.label = label
        self.start = None
        self.elapsed = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed = time.time() - self.start


class TokenTracker:
    def __init__(self):
        self.records = []

    def add(self, model: str, stage: str, prompt_tokens: int, completion_tokens: int):
        self.records.append({
            "model": model,
            "stage": stage,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        })

    def summary(self) -> str:
        if not self.records:
            return "No API calls recorded."
        lines = ["=== Token Usage Summary ==="]
        total_prompt = 0
        total_completion = 0
        for r in self.records:
            lines.append(
                f"  [{r['stage']}] {r['model']}: "
                f"prompt={r['prompt_tokens']}, completion={r['completion_tokens']}, "
                f"total={r['total_tokens']}"
            )
            total_prompt += r["prompt_tokens"]
            total_completion += r["completion_tokens"]
        lines.append(
            f"  --- TOTAL: prompt={total_prompt}, completion={total_completion}, "
            f"grand_total={total_prompt + total_completion}"
        )
        return "\n".join(lines)
