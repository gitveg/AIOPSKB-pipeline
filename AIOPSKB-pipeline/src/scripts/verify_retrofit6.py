"""
改造6 离线链路验证脚本（一次性，验证完可删）

用 Token 测试输出的17列数据（token_test_output.md）验证：
1. md_to_json.parse_fault_table 能正确解析17列（5列有值）
2. validate_kb 校验17列（check_headers 匹配 fault_retrofit6，check_maintenance_confidence 通过）
3. validate_kb 向后兼容（12列旧数据仍能匹配 fault schema）
4. check_required_fields_fault 不误报5列为空

不联网、不调用 LLM，纯解析/校验链路验证。

运行：python src/scripts/verify_retrofit6.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    _SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    _PIPELINE = os.path.join(_SRC, "pipeline")
    for _p in (_SRC, _PIPELINE):
        if _p not in sys.path:
            sys.path.insert(0, _p)
except Exception:
    pass

from scripts.md_to_json import parse_fault_table, FAULT_COLUMNS  # noqa: E402
from scripts.validate_kb import (  # noqa: E402
    SCHEMA, parse_md_table, check_headers, check_maintenance_confidence,
    check_required_fields_fault, ValidationReport,
)

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_17COL = os.path.join(HERE, "token_test_output.md")  # 17列（改造6）
TEST_12COL = os.path.join(_SRC, "data", "power", "thermal", "condenser",
                          "冷却水系统", "进水室", "faults", "进水室.md")  # 12列（改造5，向后兼容）

PASS = "[OK]"
FAIL = "[FAIL]"
results = []


def check(label, cond, detail=""):
    tag = PASS if cond else FAIL
    line = f"  {tag} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    results.append(cond)


print("=" * 64)
print("改造6 离线链路验证")
print("=" * 64)

# ── 1. md_to_json 解析17列 ──
print("\n[1] md_to_json.parse_fault_table 解析17列（冷凝管）")
faults = parse_fault_table(TEST_17COL)
check("解析出故障条数", len(faults) >= 1, f"{len(faults)} 条")
if faults:
    f0 = faults[0]
    check("故障名称非空", bool(f0.get("故障名称")), f0.get("故障名称", "")[:20])
    check("故障类别非空", bool(f0.get("故障类别")), f0.get("故障类别", ""))
    check("D1_物理属性非空", bool(f0.get("D1_物理属性")), f0.get("D1_物理属性", ""))
    check("D5_故障特征参数非空", bool(f0.get("D5_故障特征参数")), "")
    # 关键：5列是否有值
    for col in ["D11_用工需求", "D12_工机具", "D13_备件用料", "D14_安全注意事项", "D15_验收标准"]:
        check(f"5列【{col}】有值", bool(f0.get(col)),
              (f0.get(col) or "")[:30])

# ── 2. validate_kb 校验17列 ──
print("\n[2] validate_kb 校验17列")
report17 = ValidationReport(target=TEST_17COL)
headers17, _ = parse_md_table(TEST_17COL)
col_count = len(headers17)
check("表头17列", col_count == 17, f"实际{col_count}列")
expected17 = SCHEMA[4]["headers"]["fault_retrofit6"]
check_headers(report17, TEST_17COL, expected17)
header_errors = [r for r in report17.results if r.level == "error" and r.check == "表头"]
check("check_headers 无ERROR（匹配 fault_retrofit6）", len(header_errors) == 0,
      f"{len(header_errors)} 个header错误")
if header_errors:
    for e in header_errors[:2]:
        print(f"        {e.message[:80]}")

check_required_fields_fault(report17, TEST_17COL)
req_errors = [r for r in report17.results if r.level == "error" and r.check == "必填字段"]
check("check_required_fields_fault 无ERROR（5列选填不误报）", len(req_errors) == 0,
      f"{len(req_errors)} 个必填错误")

check_maintenance_confidence(report17, TEST_17COL)
maint_results = [r for r in report17.results if r.check == "检维修置信标注"]
check("check_maintenance_confidence 触发", len(maint_results) >= 1,
      maint_results[0].message[:60] if maint_results else "(未触发)")
if maint_results:
    # 17列数据5列都有置信标注，应为 ok 或 warning（取决于LLM标注完整度）
    check("检维修置信标注无ERROR", all(r.level != "error" for r in maint_results), "")

# ── 3. 向后兼容：12列旧数据 ──
print("\n[3] 向后兼容：12列旧数据（进水室，改造5格式）")
if os.path.exists(TEST_12COL):
    report12 = ValidationReport(target=TEST_12COL)
    headers12, _ = parse_md_table(TEST_12COL)
    check("12列表头存在", len(headers12) >= 11, f"{len(headers12)}列")
    expected12 = SCHEMA[4]["headers"]["fault"]
    check_headers(report12, TEST_12COL, expected12)
    h12_errors = [r for r in report12.results if r.level == "error" and r.check == "表头"]
    check("12列匹配 fault schema（无ERROR）", len(h12_errors) == 0, f"{len(h12_errors)} 个错误")
    # check_maintenance_confidence 对12列应跳过（无5列）
    check_maintenance_confidence(report12, TEST_12COL)
    skip_check = len([r for r in report12.results if r.check == "检维修置信标注"]) == 0
    check("check_maintenance_confidence 对12列跳过（向后兼容）", skip_check, "")
else:
    print(f"  [SKIP] 12列测试文件不存在：{TEST_12COL}")

# ── 4. JSON/CSV 列定义一致性 ──
print("\n[4] JSON/CSV 列定义一致性")
from scripts.json_to_csv import COLUMNS, FAULT_DIMS, FAULT_MAINT_DIMS  # noqa: E402
check("COLUMNS 含5列", all(c in COLUMNS for c in FAULT_MAINT_DIMS), "")
check("FAULT_MAINT_DIMS = 5列", len(FAULT_MAINT_DIMS) == 5, str(FAULT_MAINT_DIMS))
# 5列在 D10 之后
d10_idx = COLUMNS.index("D10_易混淆故障")
maint_idx = [COLUMNS.index(c) for c in FAULT_MAINT_DIMS]
check("5列均在 D10 之后", all(i > d10_idx for i in maint_idx), f"D10@{d10_idx}, 5列@{maint_idx}")
check("FAULT_DIMS 仍只含D列（10个）", len(FAULT_DIMS) == 10, f"{len(FAULT_DIMS)}个")

# ── 5. schemas 一致性（D11-D15）──
print("\n[5] schemas 一致性（D11-D15 短编号 + 完整列名）")
from pipeline.schemas import (FAULT_MAINTENANCE_COLS, FAULT_MAINTENANCE_KEYS,
                              MAINTENANCE_SCHEMA)  # noqa: E402
check("FAULT_MAINTENANCE_COLS = 5列（完整列名 D编号_中文）",
      len(FAULT_MAINTENANCE_COLS) == 5, str(FAULT_MAINTENANCE_COLS))
check("FAULT_MAINTENANCE_KEYS = 5个短编号",
      FAULT_MAINTENANCE_KEYS == ["D11", "D12", "D13", "D14", "D15"], str(FAULT_MAINTENANCE_KEYS))
# 完整列名三处一致：schemas COLS == json_to_csv DIMS == md_to_json FAULT_COLUMNS 子集
check("完整列名三处一致（schemas/json/md_to_json）",
      set(FAULT_MAINTENANCE_COLS) == set(FAULT_MAINT_DIMS)
      and set(FAULT_MAINTENANCE_COLS).issubset(set(FAULT_COLUMNS)), "")
# 短编号两处一致：schemas KEYS == validate fault_retrofit6 的 D11-D15
check("短编号一致（schemas KEYS == validate D11-D15）",
      set(FAULT_MAINTENANCE_KEYS).issubset(set(SCHEMA[4]["headers"]["fault_retrofit6"])), "")
check("表头显示名含D编号（如 D11 用工需求）",
      all(f"D{n} " in " ".join(parse_md_table(TEST_17COL)[0]) for n in range(11, 16)), "")

# ── 汇总 ──
print("\n" + "=" * 64)
total = len(results)
passed = sum(results)
print(f"汇总：{passed}/{total} 项通过")
if passed == total:
    print(f"{PASS} 改造6 离线链路验证全部通过")
else:
    print(f"{FAIL} 有 {total - passed} 项未通过，请检查")
sys.exit(0 if passed == total else 1)
