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

# ── 分层专家角色 ──
# 根据 --layer 参数选择对应角色，init 时注入；缺省回退到 default_role。

LAYER_EXPERT_ROLES = {
    "equipment": {
        "deepseek": (
            "你是一位电力行业资深工程师，拥有30年火电、水电、风电等电力系统设计、"
            "建设和运维经验。你熟悉国内主要电力设备制造商、行业标准(DL、GB)和KKS编码体系。"
            "在本次评审中，你的职责是从工程实务角度审查设备清单的分类合理性——主设备/辅助设备/"
            "公用系统的三分类是否符合四维判定原则（服务对象、与能量转换核心的距离、故障的设备级"
            "影响、配置粒度）。你会关注设备边界是否清晰、现场实际配置是否被遗漏、分类是否便于"
            "检修班组划分。你的风格是：严谨、务实、不放过边界模糊的分类问题，但也不过度拆分。"
        ),
        "kimi": (
            "你是一位工业知识体系架构师，专注于工业设备分类体系和知识库构建方法论。"
            "你熟悉ISO 14224(设备可靠性数据分类)、KKS编码体系、各类工业分类标准。"
            "在本次评审中，你的职责是从知识工程角度审查设备清单——分类逻辑是否一致、层级是否"
            "清晰、跨行业可复用性如何、编码锚点（KKS/RDS-PP/IEC等）能否稳定归属。"
            "你的视角侧重于：分类方案是否有利于后续的知识检索、故障诊断和跨行业复用。"
        ),
    },
    "sub_equipment": {
        "deepseek": (
            "你是一位电力行业资深工程师，熟悉各类设备的主流技术路线、市场存量占比和演进趋势。"
            "在本次评审中，你的职责是审查子设备（技术路线/型式变体）的划分是否合理——"
            "是否覆盖了市场主流机型、是否过度细分了小众/试验性路线、是否遗漏了重要的技术分支。"
            "关键原则：市场份额极低、未规模化商用、试验性或已淘汰的机型不得单独成行，应剔除或合并——"
            "展开这类机型的完整知识纯属浪费且稀释主流机型质量。"
            "你会从工程实际出发判断：哪种粒度最便于运维知识组织。"
        ),
        "kimi": (
            "你是一位工业知识体系架构师，精通分类方法论。"
            "在本次评审中，你的职责是审查子设备划分的维度单一性和MECE性——"
            "是否按同一个维度切分（如技术路线），严禁混维度；各子设备是否互不重叠、"
            "合并起来能否覆盖主流型式；命名是否规范统一。"
            "你的视角侧重于：分类逻辑的严谨性和层级语义的清晰性。"
        ),
    },
    "structure": {
        "deepseek": (
            "你是一位检修/可靠性工程师，拥有20年工业设备检修和可靠性管理经验。"
            "你熟悉设备的功能分解、备件管理体系、检修规程和FMEA分析。"
            "在本次评审中，你的职责是审查设备的子系统/部件/零件三级结构——"
            "子系统划分是否与真实工程结构一致、部件是否拆到了合理的可维护单元粒度、"
            "零件是否聚焦于易损件和关键失效件、维护方法和报废方法是否挂载在正确的层级。"
            "你会关注：粒度是否适合故障诊断和备件管理，是否有过粗或过细的拆分。"
        ),
        "kimi": (
            "你是一位工业知识体系架构师，精通设备功能分解和知识建模方法论。"
            "在本次评审中，你的职责是审查子系统/部件/零件三级结构的知识组织质量——"
            "功能完备性（是否覆盖所有功能链）、层级语义一致性（子系统按功能分、部件按总成分）、"
            "失效独立性（每个部件应是独立失效/维护单元）、粒度一致性（同级粒度相当）。"
            "你的视角侧重于：结构是否有利于故障知识的系统化组织和精准检索。"
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

def call_api(expert_id, messages, temperature=0.3, max_tokens_override=None):
    import requests as req

    cfg = get_expert_config(expert_id)
    if not cfg or not cfg["api_key"]:
        raise ValueError(f"专家 {expert_id} 未配置 API Key (.env 中缺少对应变量)")

    # 推理模型（kimi-k2.6、deepseek-v4 等）需要更长超时和更多 token 完成推理
    model = cfg["model"]
    is_reasoning = model.startswith("kimi-k") or "deepseek-v4" in model
    # kimi 推理模型只允许 temperature=1；deepseek-v4 允许自定义温度
    if model.startswith("kimi-k"):
        temperature = 1.0
    # kimi 推理模型输出含 reasoning trace，结构树评审 JSON 输出量大，8192 易截断致解析失败，提到 16384
    if model.startswith("kimi-k"):
        max_tokens = max_tokens_override or 16384
    elif is_reasoning:
        max_tokens = max_tokens_override or 8192
    else:
        max_tokens = max_tokens_override or 4096
    # 推理模型生成慢（16k 输出可能 4-6 分钟），300s 边界不够，提到 600s
    timeout = 600 if is_reasoning else 120

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


def do_chat(expert_id, user_message, temperature=0.3, max_tokens_override=None):
    session = load_session(expert_id)
    if not session:
        raise ValueError(f"专家 {expert_id} 未初始化。请先运行 init 命令。")

    cfg = get_expert_config(expert_id)
    session["messages"].append({"role": "user", "content": user_message})
    print(f"  正在咨询 {session['expert_name']}...", file=sys.stderr)
    reply, usage = call_api(expert_id, session["messages"], temperature,
                            max_tokens_override=max_tokens_override)
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
    # 按层选择角色
    custom_roles = {}
    if args.layer and args.layer in LAYER_EXPERT_ROLES:
        custom_roles = LAYER_EXPERT_ROLES[args.layer]
    init_sessions(experts, topic, custom_roles=custom_roles)


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


# ── review 自动评审流程 ──

def record_round_usage(debate_log, round_num, expert_id, usage, model):
    """记录每轮每位专家的 token 用量到 debate_log。"""
    if not usage:
        return
    debate_log.append({
        "round": round_num,
        "expert": expert_id,
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "timestamp": datetime.now().isoformat(),
    })


def summarize_token_usage(debate_log):
    """汇总 debate_log 中的 token 用量。返回结构化摘要。"""
    summary = {"rounds": [], "by_expert": {}, "total_prompt": 0, "total_completion": 0, "total_tokens": 0}

    rounds_map = {}
    for entry in debate_log:
        rn = entry["round"]
        eid = entry["expert"]
        pt = entry["prompt_tokens"]
        ct = entry["completion_tokens"]
        tt = entry["total_tokens"]

        if rn not in rounds_map:
            rounds_map[rn] = {}
        rounds_map[rn][eid] = {"prompt": pt, "completion": ct, "total": tt}

        if eid not in summary["by_expert"]:
            summary["by_expert"][eid] = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}
        summary["by_expert"][eid]["prompt"] += pt
        summary["by_expert"][eid]["completion"] += ct
        summary["by_expert"][eid]["total"] += tt
        summary["by_expert"][eid]["calls"] += 1

        summary["total_prompt"] += pt
        summary["total_completion"] += ct
        summary["total_tokens"] += tt

    for rn in sorted(rounds_map.keys()):
        summary["rounds"].append({"round": rn, **rounds_map[rn]})

    return summary


def run_debate(layer, data, context, focus=None, max_rounds=3, temperature=0.3):
    """执行多轮专家辩论。

    Round 1：两位专家独立审查。
    Round 2+：各专家看到对方上一轮回复。

    Returns:
        (debate_log, final_responses)
        debate_log: list[dict] 每轮每专家 token 记录
        final_responses: {expert_id: parsed_json_or_raw_text}
    """
    # 延迟导入（避免循环依赖）
    sys.path.insert(0, str(SCRIPT_DIR))
    from prompt_builder import build_review_prompt
    from response_parser import parse_expert_response, ResponseParseError, validate_review_schema

    experts = list(EXPERT_PROFILES.keys())
    debate_log = []
    # previous_responses[expert_id] = 该专家上一轮的解析后 JSON（或原始文本）
    previous_responses = {eid: None for eid in experts}
    final_responses = {}

    for round_num in range(1, max_rounds + 1):
        round_label = f"R{round_num}/{max_rounds}"
        print(f"\n{'='*50}")
        print(f"  {round_label} 开始")
        print(f"{'='*50}")

        round_parsed = {}

        for eid in experts:
            profile = EXPERT_PROFILES[eid]
            cfg = get_expert_config(eid)
            if not cfg or not cfg["api_key"]:
                print(f"  {profile['name']}: API Key 缺失，跳过", file=sys.stderr)
                continue

            # 获取对方上一轮回复
            other_eid = [e for e in experts if e != eid][0]
            other_response = previous_responses.get(other_eid)

            # 构建 prompt
            prompt_text = build_review_prompt(
                layer=layer, data=data, expert_id=eid, context=context,
                round_num=round_num, max_rounds=max_rounds,
                other_expert_response=other_response if round_num > 1 else None,
                focus=focus,
            )

            # 获取或创建 session
            session = load_session(eid)
            if not session:
                # 自动初始化
                roles = LAYER_EXPERT_ROLES.get(layer, {})
                role = roles.get(eid, profile["default_role"])
                topic = f"{context.get('sub_industry', '')} {context.get('equipment', '')} {layer}评审"
                session = {
                    "expert_id": eid,
                    "expert_name": profile["name"],
                    "model": cfg["model"],
                    "topic": topic,
                    "created_at": datetime.now().isoformat(),
                    "messages": [
                        {"role": "system", "content": role},
                    ],
                }

            # 追加 user message
            session["messages"].append({"role": "user", "content": prompt_text})

            # 调用 API
            print(f"  正在咨询 {profile['name']} ({round_label})...", file=sys.stderr)
            try:
                reply, usage = call_api(eid, session["messages"], temperature=temperature)
            except Exception as e:
                print(f"  {profile['name']} API 调用失败: {e}", file=sys.stderr)
                round_parsed[eid] = {"error": str(e)}
                record_round_usage(debate_log, round_num, eid,
                                   {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                                   cfg["model"])
                continue

            # 记录回复到 session
            session["messages"].append({"role": "assistant", "content": reply})
            session["last_updated"] = datetime.now().isoformat()
            _record_usage(session, usage, cfg["model"])
            save_session(eid, session)

            # 记录 token
            record_round_usage(debate_log, round_num, eid, usage, cfg["model"])
            print(f"  {profile['name']}: {usage.get('total_tokens', 0):,} tokens", file=sys.stderr)

            # 解析 JSON
            try:
                parsed = parse_expert_response(reply)
                errors = validate_review_schema(parsed, layer)
                if errors:
                    print(f"  {profile['name']} schema 校验警告: {errors[:2]}", file=sys.stderr)
                    parsed["_validation_errors"] = errors
                round_parsed[eid] = parsed
                score = parsed.get("overall_score", "?")
                verdict = parsed.get("verdict", "?")
                print(f"  {profile['name']}: score={score}, verdict={verdict}")
            except ResponseParseError as e:
                print(f"  {profile['name']} JSON 解析失败: {e}", file=sys.stderr)
                # 尝试重发一次
                retry_prompt = "请重新输出你的评审结果。要求：只输出纯 JSON，不要添加任何其他文字或 markdown 代码块标记。"
                session["messages"].append({"role": "user", "content": retry_prompt})
                try:
                    reply2, usage2 = call_api(eid, session["messages"], temperature=temperature)
                    session["messages"].append({"role": "assistant", "content": reply2})
                    _record_usage(session, usage2, cfg["model"])
                    save_session(eid, session)
                    record_round_usage(debate_log, round_num, eid, usage2, cfg["model"])
                    parsed2 = parse_expert_response(reply2)
                    round_parsed[eid] = parsed2
                    print(f"  {profile['name']}: 重试解析成功", file=sys.stderr)
                except Exception:
                    round_parsed[eid] = {"raw_text": reply, "parse_error": True}
                    print(f"  {profile['name']}: 重试仍失败，保存原始文本", file=sys.stderr)

        # 更新 previous_responses
        for eid in experts:
            if eid in round_parsed:
                previous_responses[eid] = round_parsed[eid]
        final_responses = round_parsed

        # 检查提前终止条件
        scores = []
        verdicts = []
        for eid in experts:
            resp = round_parsed.get(eid, {})
            if isinstance(resp, dict) and "overall_score" in resp and "verdict" in resp:
                scores.append(resp["overall_score"])
                verdicts.append(resp["verdict"])

        if len(verdicts) == 2 and verdicts[0] == "通过" and verdicts[1] == "通过":
            print(f"\n  两方均判定'通过'，提前结束辩论（{round_label}）")
            break

        if len(scores) == 2 and abs(scores[0] - scores[1]) < 0.5 and verdicts[0] == verdicts[1]:
            print(f"\n  评分趋同且判定一致，提前结束辩论（{round_label}）")
            break

    return debate_log, final_responses


def cmd_review(args):
    """review 子命令：全自动评审流程。"""
    # 延迟导入
    sys.path.insert(0, str(SCRIPT_DIR))
    _pipeline_dir = str(SCRIPT_DIR.parent / "pipeline")
    if _pipeline_dir not in sys.path:
        sys.path.insert(0, _pipeline_dir)
    from loader import resolve_review_target, load_layer_data
    from report_generator import generate_report
    from slug_utils import slug_eq

    layer = args.layer
    industry = args.industry
    sub = args.sub
    equip = getattr(args, "equip", None)
    focus = getattr(args, "focus", "all")
    max_rounds = getattr(args, "rounds", 3)

    # 1. 参数校验
    if not sub:
        print("错误: --sub 参数为必填", file=sys.stderr)
        sys.exit(1)
    if layer in ("sub_equipment", "structure") and not equip:
        print(f"错误: --equip 在 {layer} 层评审中为必填", file=sys.stderr)
        sys.exit(1)

    # 2. 解析路径 + 加载数据
    try:
        base_dir, context = resolve_review_target(layer, industry, sub, equip)
    except (FileNotFoundError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"评审层级: {layer}")
    print(f"评审目标: {industry} / {sub}" + (f" / {equip}" if equip else ""))
    print(f"数据目录: {base_dir}")
    print(f"最大轮次: {max_rounds}")

    try:
        data = load_layer_data(layer, base_dir, focus=focus)
    except (FileNotFoundError, ValueError) as e:
        print(f"数据加载失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 简要统计
    if layer == "equipment":
        print(f"设备数: {len(data.get('items', []))}")
    elif layer == "sub_equipment":
        print(f"子设备数: {len(data.get('items', []))}")
    elif layer == "structure":
        ss_count = len(data.get("subsystems", []))
        comp_count = sum(len(ss.get("components", {})) for ss in data.get("subsystems", []))
        print(f"子系统: {ss_count}, 部件: {comp_count}")

    # 3. 初始化专家会话
    topic = f"{sub} {equip or ''} {layer}层评审"
    roles = LAYER_EXPERT_ROLES.get(layer, {})
    experts = list(EXPERT_PROFILES.keys())
    init_sessions(experts, topic, custom_roles=roles)

    # 4. 执行多轮辩论
    debate_log, final_responses = run_debate(
        layer=layer, data=data, context=context,
        focus=focus, max_rounds=max_rounds,
        temperature=args.temperature,
    )

    # 5. 生成报告
    token_summary = summarize_token_usage(debate_log)

    # 确定输出目录
    reviews_dir = SCRIPT_DIR / "reviews"
    if equip:
        slug_name = slug_eq(equip) if equip else sub
        dir_name = f"{slug_name}_{layer}"
    else:
        dir_name = f"{sub}_{layer}"
    output_dir = args.output_dir or str(reviews_dir / dir_name)

    try:
        generate_report(
            layer=layer, context=context, debate_log=debate_log,
            expert_responses=final_responses, token_summary=token_summary,
            output_dir=output_dir, focus=focus,
        )
    except Exception as e:
        print(f"\n报告生成失败: {e}", file=sys.stderr)
        # 至少保存原始数据
        import json as _json
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "debate_log.json"), "w", encoding="utf-8") as f:
            _json.dump(debate_log, f, indent=2, ensure_ascii=False)
        with open(os.path.join(output_dir, "expert_responses.json"), "w", encoding="utf-8") as f:
            _json.dump(final_responses, f, indent=2, ensure_ascii=False, default=str)
        print(f"原始数据已保存到: {output_dir}", file=sys.stderr)

    # 汇总输出
    print(f"\n{'='*50}")
    print(f"  评审完成")
    print(f"{'='*50}")
    print(f"  报告目录: {output_dir}")
    print(f"  总 token: {token_summary['total_tokens']:,}")
    print(f"  轮次: {len(token_summary['rounds'])}")
    for eid, stats in token_summary["by_expert"].items():
        name = EXPERT_PROFILES.get(eid, {}).get("name", eid)
        print(f"    {name}: {stats['total']:,} tokens ({stats['calls']} calls)")


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
    p.add_argument("--layer", choices=["equipment", "sub_equipment", "structure"],
                   default=None, help="评审层级（自动选择对应专家角色）")

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

    p = sub.add_parser("review", help="全自动层级评审")
    p.add_argument("--layer", required=True, choices=["equipment", "sub_equipment", "structure"],
                   help="评审层级")
    p.add_argument("--industry", default="电力", help="行业名称 (默认: 电力)")
    p.add_argument("--sub", "-s", required=True, help="子行业名称 (如: 火电)")
    p.add_argument("--equip", "-e", default=None, help="设备名称 (sub_equipment/structure 层必填)")
    p.add_argument("--focus", default="all",
                   choices=["all", "subsystem", "component", "part"],
                   help="structure 层聚焦模式 (默认: all)")
    p.add_argument("--rounds", type=int, default=3, help="最大辩论轮次 (默认: 3)")
    p.add_argument("--temperature", type=float, default=0.3, help="LLM temperature (默认: 0.3)")
    p.add_argument("--output-dir", "-o", default=None, help="报告输出目录")

    args = parser.parse_args()
    handlers = {
        "init": cmd_init, "broadcast": cmd_broadcast,
        "chat": cmd_chat, "history": cmd_history, "responses": cmd_responses,
        "reset": cmd_reset, "list": cmd_list, "stats": cmd_stats,
        "review": cmd_review,
    }
    h = handlers.get(args.command)
    if h:
        h(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
