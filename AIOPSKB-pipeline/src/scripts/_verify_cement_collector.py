"""临时验证：collector.py 水泥行业 prompt 分支是否真实生效（实质验证，非表面）。

验证点：
1. industry="水泥" 时 fault prompt 含水泥行业 anchor（JC/T 733 / GB/T 26583 等）
2. d8_std 被正确注入为 "JC/T 系列、GB/T 26583"
3. 分支互斥：钢铁/石化/火电(else) 不走到水泥分支
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))          # src/scripts
sys.path.insert(0, os.path.join(ROOT, "..", "pipeline"))   # 让 agents/search/config 裸 import 可用

from agents.collector import _build_prompt  # noqa: E402


def build(industry, equip="回转窑", comp="筒体"):
    ctx = {"industry": industry, "equipment": equip, "component": comp}
    return _build_prompt("fault", ctx, "测试搜索文本")


# 1. 水泥分支内容
r = build("水泥")
checks = {
    "含水泥anchor": "水泥行业专属要求" in r,
    "含JC/T 733(回转窑)": "JC/T 733" in r,
    "含GB/T 26583(水泥回转窑)": "GB/T 26583" in r,
    "d8_std正确注入": "JC/T 系列、GB/T 26583检修工艺导则" in r,
    "列禁用火电标准": "禁用火电标准" in r,
    "列禁用石化专用标准": "禁用石化专用标准" in r,
    "列禁用钢铁专用标准": "禁用钢铁专用标准" in r,
    "含水泥工况词(两磨一烧)": "两磨一烧" in r,
    "含水泥粉尘防护(D14)": "粉尘防护" in r,
}
print("=== 水泥分支内容 ===")
for k, v in checks.items():
    print(f"  [{'OK' if v else 'FAIL'}] {k}")

# 2. 分支互斥
r_steel = build("钢铁")
r_petro = build("石化")
r_thermal = build("电力")
print("\n=== 分支互斥 ===")
print(f"  [{'OK' if '水泥行业专属要求' not in r_steel else 'FAIL'}] 钢铁 不含水泥anchor")
print(f"  [{'OK' if '钢铁行业专属要求' in r_steel else 'FAIL'}] 钢铁 含钢铁anchor")
print(f"  [{'OK' if '水泥行业专属要求' not in r_petro else 'FAIL'}] 石化 不含水泥anchor")
print(f"  [{'OK' if '石化行业专属要求' in r_petro else 'FAIL'}] 石化 含石化anchor")
print(f"  [{'OK' if 'DL/T 869、GB/T 12243检修工艺导则' in r_thermal else 'FAIL'}] 火电 走else默认d8_std")
print(f"  [{'OK' if '水泥行业专属要求' not in r_thermal else 'FAIL'}] 火电 不含水泥anchor")

allok = (
    all(checks.values())
    and "水泥行业专属要求" not in r_steel
    and "钢铁行业专属要求" in r_steel
    and "水泥行业专属要求" not in r_petro
    and "石化行业专属要求" in r_petro
    and "水泥行业专属要求" not in r_thermal
    and "DL/T 869、GB/T 12243检修工艺导则" in r_thermal
)
print("\n总体:", "PASS ✅ 水泥分支真实生效" if allok else "FAIL ❌ 有断言未通过")
sys.exit(0 if allok else 1)
