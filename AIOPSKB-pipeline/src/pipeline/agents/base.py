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


def _is_content_filtered(e: Exception) -> bool:
    """检测 GLM 内容安全过滤（code 1301，石化故障描述易触发）。"""
    msg = str(e)
    return "1301" in msg or "敏感内容" in msg or "sensitive content" in msg.lower()


def call_llm(agent_name: str, system_prompt: str, user_prompt: str, temperature: float = 0.3,
             max_tokens: int = 8192) -> str:
    from config import AGENT_MODELS
    cfg = AGENT_MODELS[agent_name]

    # GLM 内容安全过滤(1301) → DeepSeek 兜底（仅 collector/judge_b，省配额：大部分 GLM 能跑，仅 1301 的用 DeepSeek）
    fallback_cfg = None
    if agent_name in ("collector", "judge_b"):
        ds = AGENT_MODELS.get("structure")
        if ds and ds.get("base_url") != cfg.get("base_url"):
            fallback_cfg = ds

    active_cfg = cfg
    used_fallback = False
    last_exc = None

    for attempt in range(5):
        # 按当前 active_cfg 构建客户端（fallback 切换时自动用新 cfg）
        client = OpenAI(api_key=active_cfg["api_key"], base_url=active_cfg["base_url"])
        sema = _get_semaphore(active_cfg["base_url"])
        temp = temperature
        if "kimi" in active_cfg.get("model", "") or "moonshot" in active_cfg.get("base_url", ""):
            temp = 1.0
        try:
            with sema:
                resp = client.chat.completions.create(
                    model=active_cfg["model"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temp,
                    max_tokens=max_tokens,
                    timeout=300.0,
                )
            return resp.choices[0].message.content
        except Exception as e:
            last_exc = e
            # GLM 内容安全过滤 → 切 DeepSeek 兜底（立即重试，不退避）
            if not used_fallback and fallback_cfg and _is_content_filtered(e):
                print(f"  [call_llm] GLM 内容安全过滤(1301)，切换 DeepSeek 兜底: {fallback_cfg['model']}")
                active_cfg = fallback_cfg
                used_fallback = True
                continue
            if _is_rate_limit_error(e):
                wait = min(30, 5 * (2 ** attempt))  # 5s, 10s, 20s, 30s, 30s
                print(f"  [call_llm] 限流({active_cfg['model']})，{wait}s后重试 ({attempt+1}/5)")
            else:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
                if attempt < 4:
                    print(f"  [call_llm] 第{attempt+1}次失败，{wait}s后重试: {type(e).__name__}")
            time.sleep(wait)
    raise last_exc
