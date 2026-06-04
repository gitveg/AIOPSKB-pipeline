"""
一次性迁移脚本：将子设备从元数据标注升级为目录层级。

对每个含 sub_equipment.md 的设备目录：
1. 解析 sub_equipment.md 获取子设备名称列表
2. 创建各子设备目录（中文名）及空 faults/ 子目录
3. 将现有 components.md 和 faults/ 移入 _archive/ 归档
4. 幂等：重复运行不报错

用法:
  python src/scripts/migrate_sub_equipment.py                 # 默认扫描 src/data/power
  python src/scripts/migrate_sub_equipment.py src/data/power  # 指定目录
"""

import os
import re
import shutil
import sys


def parse_sub_equipment_names(sub_eq_path: str) -> list[str]:
    """解析 sub_equipment.md，返回子设备名称列表。"""
    if not os.path.exists(sub_eq_path):
        return []
    with open(sub_eq_path, "r", encoding="utf-8") as f:
        content = f.read()
    names = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
        if cells and cells[0] not in ("子设备名称", ""):
            names.append(cells[0])
    return names


def sanitize_dirname(name: str) -> str:
    """将子设备名称转为安全的目录名（去除文件系统不允许的字符）。"""
    # 替换不安全字符，保留中文、字母、数字、括号、下划线、连字符、空格
    name = name.replace("/", "／").replace("\\", "＼").replace(":", "：")
    name = name.replace("*", "").replace("?", "").replace('"', "")
    name = name.replace("<", "").replace(">", "").replace("|", "")
    # 去除首尾空白
    return name.strip()


def migrate_equipment_dir(eq_dir: str, dry_run: bool = False) -> bool:
    """迁移单个设备目录。返回 True 表示执行了迁移，False 表示跳过。"""
    sub_eq_path = os.path.join(eq_dir, "sub_equipment.md")
    if not os.path.exists(sub_eq_path):
        return False

    sub_eq_names = parse_sub_equipment_names(sub_eq_path)
    if not sub_eq_names:
        print(f"  [!] {eq_dir}: sub_equipment.md 无有效条目，跳过")
        return False

    # 检查是否已迁移：已有子设备目录且已有 _archive
    archive_dir = os.path.join(eq_dir, "_archive")
    existing_sub_dirs = [
        sanitize_dirname(n) for n in sub_eq_names
        if os.path.isdir(os.path.join(eq_dir, sanitize_dirname(n)))
    ]
    if existing_sub_dirs and os.path.isdir(archive_dir):
        print(f"  [skip] {eq_dir}: 已迁移（{len(existing_sub_dirs)} 个子设备目录已存在）")
        return False

    print(f"  [OK] {eq_dir}: 发现 {len(sub_eq_names)} 个子设备")
    for n in sub_eq_names:
        print(f"       - {n}")

    if dry_run:
        print(f"       (dry run，不执行)")
        return False

    # 创建 _archive 并归档旧数据
    os.makedirs(archive_dir, exist_ok=True)

    comp_path = os.path.join(eq_dir, "components.md")
    if os.path.exists(comp_path):
        dest = os.path.join(archive_dir, "components.md")
        if not os.path.exists(dest):
            shutil.move(comp_path, dest)
            print(f"       归档 components.md → _archive/")

    faults_dir = os.path.join(eq_dir, "faults")
    if os.path.isdir(faults_dir):
        dest = os.path.join(archive_dir, "faults")
        if not os.path.exists(dest):
            shutil.move(faults_dir, dest)
            print(f"       归档 faults/ → _archive/")

    # 创建子设备目录
    for name in sub_eq_names:
        dirname = sanitize_dirname(name)
        sub_dir = os.path.join(eq_dir, dirname)
        os.makedirs(sub_dir, exist_ok=True)
        os.makedirs(os.path.join(sub_dir, "faults"), exist_ok=True)
        print(f"       创建目录: {dirname}/")

    return True


def scan_and_migrate(base_dir: str, dry_run: bool = False):
    """扫描目录下所有含 sub_equipment.md 的设备目录并迁移。"""
    print(f"\n扫描目录: {base_dir}")
    if dry_run:
        print("(dry run 模式)\n")

    migrated = 0
    skipped = 0

    for root, dirs, files in os.walk(base_dir):
        # 跳过 _archive 和 kb_exports
        dirs[:] = [d for d in dirs if d not in ("_archive", "kb_exports", "__pycache__")]

        if "sub_equipment.md" in files:
            eq_dir = root
            if migrate_equipment_dir(eq_dir, dry_run):
                migrated += 1
            else:
                skipped += 1

    print(f"\n{'='*50}")
    if dry_run:
        print(f"  Dry run 完成")
    else:
        print(f"  迁移完成")
    print(f"  已迁移: {migrated} 个设备")
    print(f"  已跳过: {skipped} 个设备")
    print(f"{'='*50}\n")


def main():
    if len(sys.argv) > 1:
        base_dir = sys.argv[1]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "power"))

    base_dir = os.path.normpath(base_dir)
    if not os.path.isdir(base_dir):
        print(f"目录不存在: {base_dir}", file=sys.stderr)
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    scan_and_migrate(base_dir, dry_run)


if __name__ == "__main__":
    main()
