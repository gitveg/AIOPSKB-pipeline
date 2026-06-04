"""
AI_Expert.py - 多专家咨询模块

支持与 DeepSeek、Kimi 等AI专家进行多轮递进式讨论。
会话历史持久化到磁盘，跨调用保持上下文。
API配置从项目根目录 .env 文件读取。

用法:
  # 1. 初始化专家会话（设定讨论主题和角色）
  python src/ai_expert_review/AI_Expert.py init --topic "水电主设备分类评审"

  # 2. 向所有专家广播同一消息
  python src/ai_expert_review/AI_Expert.py broadcast --message "请审查以下方案..."
  python src/ai_expert_review/AI_Expert.py broadcast --file review_prompt.md --output responses.md

  # 3. 向指定专家提问（追问）
  python src/ai_expert_review/AI_Expert.py chat --expert deepseek --message "你提到的XX点，能否展开说明？"

  # 4. 查看某位专家的完整对话历史
  python src/ai_expert_review/AI_Expert.py history --expert deepseek

  # 5. 查看所有专家的最新一轮回复
  python src/ai_expert_review/AI_Expert.py responses

  # 6. 重置某位专家的会话
  python src/ai_expert_review/AI_Expert.py reset --expert deepseek

  # 7. 查看当前活跃专家列表及配置状态
  python src/ai_expert_review/AI_Expert.py list
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # src/ai_expert_review -> src -> project_root
ENV_FILE = PROJECT_ROOT / ".env"
SESSIONS_DIR = SCRIPT_DIR / "sessions"

# ── 专家定义 ──
# api_base/model 从 .env 读取，此处仅定义 env var 名称和 fallback

EXPERT_PROFILES = {
    "deepseek": {
        "name": "DeepSeek 专家",
        "env_key": "DEEPSEEK_API_KEY",
        "env_base_url": "DEEPSEEK_BASE_URL",
        "env_model": "DEEPSEEK_MODEL",
        "fallback_base_url": "https://api.deepseek.com/v1",
        "fallback_model": "deepseek-chat",
        "default_role": (
            "你是一位电力行业资深工程师和设备分类专家，拥有30年水电、火电、风电等"
            "电力系统设计、建设和运维经验。你熟悉国内主要电力设备制造商、行业标准"
            "(DL、GB)和KKS编码体系。你的评审风格是：严谨、务实、注重工程实际，"
            "不放过边界模糊的分类问题，但也不过度拆分。你会给出明确的判定意见和理由。"
        ),
    },
    "kimi": {
        "name": "Kimi 专家",
        "env_key": "KIMI_API_KEY",
        "env_base_url": "KIMI_BASE_URL",
        "env_model": "KIMI_MODEL",
        "fallback_base_url": "https://api.moonshot.cn/v1",
        "fallback_model": "moonshot-v1-auto",
        "default_role": (
            "你是一位工业知识体系架构师，专注于工业设备分类体系和知识库构建方法论。"
            "你熟悉ISO 14224(设备可靠性数据分类)、KKS编码体系、各类工业分类标准。"
            "你的评审视角侧重于：分类逻辑的一致性、层级的清晰性、跨行业可复用性。"
            "你会从知识工程的角度评估分类方案是否有利于后续的知识检索和故障诊断。"
        ),
    },
}


# ── .env 解析 ──

_env_cache = None

def load_env():
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    _env_cache = {}
    if not ENV_FILE.exists():
        return _env_cache
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"?([^"]*)"?', line)
            if m:
                _env_cache[m.group(1)] = m.group(2).strip()
    return _env_cache


def get_env(key, default=None):
    val = os.environ.get(key)
    if val:
        return val
    return load_env().get(key, default)


# ── 专家配置获取 ──

def get_expert_config(expert_id):
    profile = EXPERT_PROFILES.get(expert_id)
    if not profile:
        return None
    api_key = get_env(profile["env_key"])
    base_url = get_env(profile["env_base_url"], profile["fallback_base_url"])
    model = get_env(profile["env_model"], profile["fallback_model"])
    return {
        "api_key": api_key,
        "api_base": base_url.rstrip("/") + "/chat/completions",
        "model": model,
        "name": profile["name"],
    }


# ── 会话管理 ──

def get_session_path(expert_id):
    return SESSIONS_DIR / f"{expert_id}_session.json"


def load_session(expert_id):
    path = get_session_path(expert_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(expert_id, session):
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(get_session_path(expert_id), "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)


def init_sessions(experts, topic, custom_roles=None):
    custom_roles = custom_roles or {}
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    initialized = []
    for expert_id in experts:
        if expert_id not in EXPERT_PROFILES:
            print(f"  未知专家: {expert_id}", file=sys.stderr)
            continue
        profile = EXPERT_PROFILES[expert_id]
        cfg = get_expert_config(expert_id)
        if not cfg["api_key"]:
            print(f"  {profile['name']}: .env 中未找到 {profile['env_key']}，跳过", file=sys.stderr)
            continue
        role = custom_roles.get(expert_id, profile["default_role"])
        session = {
            "expert_id": expert_id,
            "expert_name": profile["name"],
            "model": cfg["model"],
            "topic": topic,
            "created_at": datetime.now().isoformat(),
            "messages": [
                {"role": "system", "content": role},
                {"role": "system", "content": f"讨论主题: {topic}\n\n请基于你的专业视角，对后续提出的方案进行独立审查。给出明确的判定意见，如果不同意请说明理由和替代建议。"},
            ],
        }
        save_session(expert_id, session)
        initialized.append(expert_id)
        print(f"  {profile['name']} ({cfg['model']}) 会话已初始化")
    print(f"\n已初始化 {len(initialized)} 位专家会话。")


# ── API 调用 ──

def call_api(expert_id, messages, temperature=0.3):
    import requests as req

    cfg = get_expert_config(expert_id)
    if not cfg or not cfg["api_key"]:
        raise ValueError(f"专家 {expert_id} 未配置 API Key (.env 中缺少对应变量)")

    # 推理模型（如 kimi-k2.6）只允许 temperature=1，且需要更长超时和更多token
    model = cfg["model"]
    is_reasoning = model.startswith("kimi-k")
    if is_reasoning:
        temperature = 1.0
    max_tokens = 8192 if is_reasoning else 4096
    timeout = 300 if is_reasoning else 120

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = req.post(cfg["api_base"], headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage


def _record_usage(session, usage, model):
    """将API调用的token用量记录到session中（由do_chat统一调用）。"""
    if not usage:
        return
    if "token_usage" not in session:
        session["token_usage"] = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": []
        }
    session["token_usage"]["prompt_tokens"] += usage.get("prompt_tokens", 0)
    session["token_usage"]["completion_tokens"] += usage.get("completion_tokens", 0)
    session["token_usage"]["total_tokens"] += usage.get("total_tokens", 0)
    session["token_usage"]["calls"].append({
        "timestamp": datetime.now().isoformat(),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "model": model,
    })


def do_chat(expert_id, user_message, temperature=0.3):
    session = load_session(expert_id)
    if not session:
        raise ValueError(f"专家 {expert_id} 未初始化。请先运行 init 命令。")

    cfg = get_expert_config(expert_id)
    session["messages"].append({"role": "user", "content": user_message})
    print(f"  正在咨询 {session['expert_name']}...", file=sys.stderr)
    reply, usage = call_api(expert_id, session["messages"], temperature)
    session["messages"].append({"role": "assistant", "content": reply})
    session["last_updated"] = datetime.now().isoformat()
    _record_usage(session, usage, cfg["model"])
    save_session(expert_id, session)
    return reply


def do_broadcast(message, experts=None, temperature=0.3):
    if experts is None:
        experts = list(EXPERT_PROFILES.keys())
    results = {}
    for eid in experts:
        if eid not in EXPERT_PROFILES:
            continue
        try:
            reply = do_chat(eid, message, temperature)
            results[eid] = reply
        except Exception as e:
            results[eid] = f"[调用失败: {e}]"
    return results


# ── 输出格式化 ──

def format_response(expert_id, reply):
    name = EXPERT_PROFILES.get(expert_id, {}).get("name", expert_id)
    return f"{'='*60}\n {name} 回复:\n{'='*60}\n{reply}\n"


def format_history(session):
    lines = [
        f"专家: {session['expert_name']}",
        f"模型: {session.get('model', 'unknown')}",
        f"主题: {session['topic']}",
        f"创建: {session['created_at']}",
        f"消息数: {len(session['messages'])}",
        "=" * 60,
    ]
    for i, msg in enumerate(session["messages"]):
        role = msg["role"]
        if role == "system":
            tag = "[系统]"
        elif role == "user":
            tag = "[提问]"
        else:
            tag = "[回复]"
        lines.append(f"\n--- {tag} (消息 {i+1}) ---")
        lines.append(msg["content"][:8000])
    return "\n".join(lines)


# ── CLI 命令 ──

def cmd_init(args):
    experts = args.experts.split(",") if args.experts else list(EXPERT_PROFILES.keys())
    topic = args.topic or "未命名讨论"
    init_sessions(experts, topic)


def cmd_broadcast(args):
    message = args.message
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            message = f.read()
    if not message:
        print("错误: 请通过 --message 或 --file 提供消息内容", file=sys.stderr)
        sys.exit(1)
    experts = args.experts.split(",") if args.experts else None
    results = do_broadcast(message, experts, temperature=args.temperature)
    output = ""
    for eid, reply in results.items():
        output += format_response(eid, reply) + "\n"
    print(output)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"已保存到: {args.output}", file=sys.stderr)


def cmd_chat(args):
    message = args.message
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            message = f.read()
    if not message:
        print("错误: 请通过 --message 或 --file 提供消息内容", file=sys.stderr)
        sys.exit(1)
    try:
        reply = do_chat(args.expert, message, temperature=args.temperature)
        print(format_response(args.expert, reply))
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_history(args):
    session = load_session(args.expert)
    if not session:
        print(f"专家 {args.expert} 未初始化。", file=sys.stderr)
        sys.exit(1)
    print(format_history(session))


def cmd_responses(args):
    experts = args.experts.split(",") if args.experts else list(EXPERT_PROFILES.keys())
    for eid in experts:
        session = load_session(eid)
        if not session:
            continue
        msgs = session["messages"]
        if len(msgs) >= 2 and msgs[-1]["role"] == "assistant":
            print(format_response(eid, msgs[-1]["content"]))
        else:
            name = EXPERT_PROFILES.get(eid, {}).get("name", eid)
            print(f"  {name}: 尚无回复")


def cmd_reset(args):
    path = get_session_path(args.expert)
    if path.exists():
        path.unlink()
        print(f"  已重置 {args.expert} 会话")
    else:
        print(f"  会话不存在: {args.expert}", file=sys.stderr)


def cmd_list(args):
    print(f".env 路径: {ENV_FILE}")
    print(f"会话目录: {SESSIONS_DIR}\n")
    print("可用专家:")
    for eid, profile in EXPERT_PROFILES.items():
        cfg = get_expert_config(eid)
        has_key = cfg and cfg["api_key"]
        has_session = get_session_path(eid).exists()
        model = cfg["model"] if cfg else "?"
        key_st = f"Key OK" if has_key else f"Key缺失(.env:{profile['env_key']})"
        sess_st = " | 会话活跃" if has_session else ""
        # 显示累计token
        token_st = ""
        if has_session:
            session = load_session(eid)
            tu = session.get("token_usage", {})
            total = tu.get("total_tokens", 0)
            if total:
                token_st = f" | {total:,} tokens"
        print(f"  {eid:12s}  {profile['name']:10s}  model={model:20s}  {key_st}{sess_st}{token_st}")
    print()


def cmd_stats(args):
    experts = args.experts.split(",") if args.experts else list(EXPERT_PROFILES.keys())
    total_all = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}

    for eid in experts:
        session = load_session(eid)
        if not session:
            print(f"  {eid}: 未初始化")
            continue

        tu = session.get("token_usage", {})
        if not tu:
            print(f"  {eid}: 无token记录（会话创建于token记录功能上线前）")
            continue

        name = session.get("expert_name", eid)
        model = session.get("model", "?")
        prompt_t = tu.get("prompt_tokens", 0)
        comp_t = tu.get("completion_tokens", 0)
        total_t = tu.get("total_tokens", 0)
        calls = tu.get("calls", [])

        print(f"{'='*50}")
        print(f"  {name} ({model})")
        print(f"{'='*50}")
        print(f"  调用次数:    {len(calls)}")
        print(f"  输入tokens:  {prompt_t:>10,}")
        print(f"  输出tokens:  {comp_t:>10,}")
        print(f"  总计tokens:  {total_t:>10,}")

        if calls:
            print(f"\n  逐次明细:")
            for i, c in enumerate(calls):
                ts = c.get("timestamp", "?")
                pt = c.get("prompt_tokens", 0)
                ct = c.get("completion_tokens", 0)
                tt = c.get("total_tokens", 0)
                print(f"    #{i+1}  {ts[:19]}  input={pt:,}  output={ct:,}  total={tt:,}")

        total_all["prompt"] += prompt_t
        total_all["completion"] += comp_t
        total_all["total"] += total_t
        total_all["calls"] += len(calls)
        print()

    if total_all["calls"] > 0:
        print(f"{'='*50}")
        print(f"  汇总: {total_all['calls']} 次调用 | "
              f"输入 {total_all['prompt']:,} | 输出 {total_all['completion']:,} | "
              f"总计 {total_all['total']:,} tokens")
        print(f"{'='*50}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AI专家咨询模块 - 多专家多轮递进式讨论")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="初始化专家会话")
    p.add_argument("--experts", default="deepseek,kimi", help="专家列表(逗号分隔)")
    p.add_argument("--topic", required=True, help="讨论主题")

    p = sub.add_parser("broadcast", help="向所有专家广播消息")
    p.add_argument("--message", "-m", help="消息内容")
    p.add_argument("--file", "-f", help="从文件读取消息")
    p.add_argument("--experts", help="指定专家(逗号分隔)")
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--output", "-o", help="保存回复到文件")

    p = sub.add_parser("chat", help="与指定专家对话")
    p.add_argument("--expert", "-e", required=True)
    p.add_argument("--message", "-m", help="消息内容")
    p.add_argument("--file", "-f", help="从文件读取消息")
    p.add_argument("--temperature", type=float, default=0.3)

    p = sub.add_parser("history", help="查看对话历史")
    p.add_argument("--expert", "-e", required=True)

    p = sub.add_parser("responses", help="查看所有专家最新回复")
    p.add_argument("--experts", help="指定专家(逗号分隔)")

    p = sub.add_parser("reset", help="重置专家会话")
    p.add_argument("--expert", "-e", required=True)

    sub.add_parser("list", help="列出可用专家及配置状态")

    p = sub.add_parser("stats", help="查看token用量统计")
    p.add_argument("--experts", help="指定专家(逗号分隔，默认全部)")

    args = parser.parse_args()
    handlers = {
        "init": cmd_init, "broadcast": cmd_broadcast,
        "chat": cmd_chat, "history": cmd_history, "responses": cmd_responses,
        "reset": cmd_reset, "list": cmd_list, "stats": cmd_stats,
    }
    h = handlers.get(args.command)
    if h:
        h(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
