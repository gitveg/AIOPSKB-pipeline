"""
LiteLLM DeepSeek API 测试脚本

用途：测试新的 LiteLLM 中转配置能否正常调用 DeepSeek 模型
运行：python src/scripts/test_litellm_deepseek.py

诊断逻辑（分层定位问题）：
  1. 配置完整性 → KEY/BASE_URL 是否填写
  2. 中转链路连通 → 服务是否可达、KEY 是否被识别
  3. 目标模型权限 → KEY 能否访问 deepseek
  当目标模型被拒时，自动用返回的"允许模型列表"做二次验证，
  从而区分"中转坏了"还是"模型权限不对"。
"""

import os
import re
import sys
import json

# Windows 终端 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# 确保 pipeline 包可 import
try:
    _SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
except Exception:
    pass

from dotenv import load_dotenv
from openai import OpenAI

# 加载 .env（与 config.py 同一路径处理）
ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(ENV_PATH)

# 读取配置（支持全大写和驼峰两种命名）
LITE_LLM_API_KEY = os.getenv("LITE_LLM_DEEPSEEK_API_KEY") or os.getenv("Lite_LLM_DEEPSEEK_API_KEY", "").strip('"')
LITE_LLM_BASE_URL = os.getenv("LITE_LLM_BASE_URL", "").strip('"')
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

TEST_PROMPT = """请用一句话回答：工业设备运维知识库的核心价值是什么？"""


def mask_key(k: str) -> str:
    if not k:
        return "(空)"
    return f"{k[:10]}...{k[-4:]}" if len(k) > 14 else "***"


def call_model(client, model, max_tokens=200):
    """单次调用，返回 (content, usage) 或抛出异常。"""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是工业设备运维专家，请简洁作答。"},
            {"role": "user", "content": TEST_PROMPT},
        ],
        temperature=0.3,
        max_tokens=max_tokens,
        timeout=30.0,
    )
    content = resp.choices[0].message.content
    usage = resp.usage
    return content, usage


def parse_allowed_models(err_msg: str):
    """从 403 错误信息中解析允许访问的模型列表。"""
    m = re.search(r"access models=\[([^\]]*)\]", err_msg)
    if not m:
        return []
    raw = m.group(1)
    return [s.strip().strip("'\"") for s in raw.split(",") if s.strip()]


def main():
    print("=" * 70)
    print("LiteLLM DeepSeek API 测试")
    print("=" * 70)
    print()
    print("【0】配置加载")
    print(f"    API_KEY : {mask_key(LITE_LLM_API_KEY)}")
    print(f"    BASE_URL: {LITE_LLM_BASE_URL}")
    print(f"    MODEL   : {DEEPSEEK_MODEL}")
    print()

    if not LITE_LLM_API_KEY:
        print("[FAIL] LITE_LLM_DEEPSEEK_API_KEY 未配置，请检查 .env")
        sys.exit(1)
    if not LITE_LLM_BASE_URL:
        print("[FAIL] LITE_LLM_BASE_URL 未配置，请检查 .env")
        sys.exit(1)

    client = OpenAI(api_key=LITE_LLM_API_KEY, base_url=LITE_LLM_BASE_URL)

    # ── 步骤1：测试目标模型（DeepSeek）──────────────────────
    print("【1】调用目标模型 (DeepSeek)")
    print("-" * 70)
    try:
        content, usage = call_model(client, DEEPSEEK_MODEL)
        print(f"    ✓ 调用成功 | in={usage.prompt_tokens} out={usage.completion_tokens} total={usage.total_tokens}")
        print()
        print("    响应内容：")
        for line in content.strip().split("\n"):
            print(f"      {line}")
        print()
        print("=" * 70)
        print("[SUCCESS] LiteLLM DeepSeek 中转配置完全可用")
        print("=" * 70)
        print(f"  • 中转服务可达: {LITE_LLM_BASE_URL}")
        print(f"  • KEY 有效: {mask_key(LITE_LLM_API_KEY)}")
        print(f"  • 模型可调用: {DEEPSEEK_MODEL}")
        sys.exit(0)

    except Exception as e:
        err_msg = str(e)
        print(f"    ✗ 调用失败: {type(e).__name__}")
        print(f"    错误: {err_msg[:200]}")
        print()

        # ── 步骤2：解析是否是模型权限问题 ──────────────────────
        allowed = parse_allowed_models(err_msg)
        if not allowed:
            # 不是权限问题 → 真正的链路/鉴权失败
            print("=" * 70)
            print("[FAIL] 中转链路或鉴权失败（非模型权限问题）")
            print("=" * 70)
            print("排查：")
            print(f"  1. 服务是否启动: curl {LITE_LLM_BASE_URL}/health 或浏览器打开")
            print(f"  2. 网络是否可达（内网 {LITE_LLM_BASE_URL} 需 VPN/同网段）")
            print("  3. 401/403(无模型列表) → KEY 无效或已撤销")
            print("  4. 连接超时 → 服务未启动 / 端口不通")
            sys.exit(1)

        # 是模型权限问题 → 用允许的模型做二次验证，确认链路本身是通的
        print("【2】诊断：目标模型被拒，KEY 仅允许访问以下模型：")
        for m in allowed:
            print(f"      - {m}")
        print()
        print("【3】用允许的模型做二次验证（确认中转链路本身是否正常）")
        print("-" * 70)
        probe_model = allowed[0]
        try:
            content2, usage2 = call_model(client, probe_model, max_tokens=100)
            print(f"    ✓ 二次验证成功 | model={probe_model} | out={usage2.completion_tokens} tokens")
            print(f"    响应: {content2.strip()[:80]}")
            print()
            print("=" * 70)
            print("[结论] 中转链路正常，但 KEY 无法访问 DeepSeek")
            print("=" * 70)
            print(f"  ✓ 中转服务可达: {LITE_LLM_BASE_URL}")
            print(f"  ✓ KEY 有效（能通过鉴权）: {mask_key(LITE_LLM_API_KEY)}")
            print(f"  ✗ 此 KEY 不能访问 {DEEPSEEK_MODEL}")
            print(f"    KEY 当前仅允许: {allowed}")
            print()
            print("建议：")
            print("  • 若要用此中转调 DeepSeek：需在 LiteLLM 服务端为该 KEY 授权 deepseek 模型")
            print("  • 或更换一个已授权 DeepSeek 的 KEY")
            print("  • 当前 KEY 可正常调用 GLM 系列（coder-glm-*）")
            sys.exit(2)

        except Exception as e2:
            print(f"    ✗ 二次验证也失败: {type(e2).__name__}: {str(e2)[:150]}")
            print()
            print("=" * 70)
            print("[FAIL] 中转链路本身有问题（连允许的模型也调不通）")
            print("=" * 70)
            print("排查：")
            print(f"  • 服务是否正常运行: {LITE_LLM_BASE_URL}")
            print("  • 该 KEY 是否已过期/被禁用")
            sys.exit(1)


if __name__ == "__main__":
    main()
