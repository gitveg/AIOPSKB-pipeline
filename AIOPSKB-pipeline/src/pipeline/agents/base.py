import os
import json
import time
import threading
from openai import OpenAI

# Per-provider concurrency limiter: max N concurrent API calls per provider
_provider_sema = {}
_provider_lock = threading.Lock()
MAX_CONCURRENT_PER_PROVIDER = 5


def _get_semaphore(base_url: str) -> threading.Semaphore:
    with _provider_lock:
        if base_url not in _provider_sema:
            _provider_sema[base_url] = threading.Semaphore(MAX_CONCURRENT_PER_PROVIDER)
        return _provider_sema[base_url]


def _is_rate_limit_error(e: Exception) -> bool:
    """Detect rate limit (429) or overload errors."""
    msg = str(e).lower()
    code = getattr(getattr(e, 'status_code', None), 'value', None)
    if code == 429:
        return True
    return any(kw in msg for kw in ('rate limit', 'rate_limit', 'too many requests',
                                      '429', 'quota', 'capacity', 'overloaded'))


def call_llm(agent_name: str, system_prompt: str, user_prompt: str, temperature: float = 0.3,
             max_tokens: int = 8192) -> str:
    from config import AGENT_MODELS
    cfg = AGENT_MODELS[agent_name]
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    # Kimi models only accept temperature=1
    if "kimi" in cfg.get("model", "") or "moonshot" in cfg.get("base_url", ""):
        temperature = 1.0

    sema = _get_semaphore(cfg["base_url"])
    last_exc = None

    for attempt in range(5):
        try:
            with sema:
                resp = client.chat.completions.create(
                    model=cfg["model"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=300.0,
                )
            return resp.choices[0].message.content
        except Exception as e:
            last_exc = e
            if _is_rate_limit_error(e):
                wait = min(30, 5 * (2 ** attempt))  # 5s, 10s, 20s, 30s, 30s
                print(f"  [call_llm] 限流({cfg['model']})，{wait}s后重试 ({attempt+1}/5)")
            else:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
                if attempt < 4:
                    print(f"  [call_llm] 第{attempt+1}次失败，{wait}s后重试: {type(e).__name__}")
            time.sleep(wait)
    raise last_exc
