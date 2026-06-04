"""
将归档的通用部件和故障数据复制到各子设备目录作为基础数据。

对每个含 _archive/ 的设备目录：
1. 读取子设备名称列表
2. 将 _archive/components.md 复制到每个子设备目录
3. 将 _archive/faults/ 复制到每个子设备目录
4. 幂等：已有数据的子设备目录跳过

这样每个子设备都有完整的基础数据，后续可用 --force 单独精炼特定子设备。

用法:
  python src/scripts/restore_sub_equipment_data.py                 # 默认扫描 src/data/power
  python src/scripts/restore_sub_equipment_data.py src/data/power  # 指定目录
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
    """将子设备名称转为安全的目录名。"""
    return name.replace("/", "／").replace("\\", "＼").strip()


def restore_equipment_dir(eq_dir: str) -> bool:
    """将归档数据恢复到各子设备目录。返回 True 表示执行了操作。"""
    archive_dir = os.path.join(eq_dir, "_archive")
    if not os.path.isdir(archive_dir):
        return False

    sub_eq_path = os.path.join(eq_dir, "sub_equipment.md")
    sub_eq_names = parse_sub_equipment_names(sub_eq_path)
    if not sub_eq_names:
        return False

    archived_comp = os.path.join(archive_dir, "components.md")
    archived_faults = os.path.join(archive_dir, "faults")

    if not os.path.exists(archived_comp) and not os.path.isdir(archived_faults):
        return False

    eq_name = os.path.basename(eq_dir)
    restored = 0
    skipped = 0

    for se_name in sub_eq_names:
        se_dirname = sanitize_dirname(se_name)
        se_dir = os.path.join(eq_dir, se_dirname)
        if not os.path.isdir(se_dir):
            continue

        comp_dest = os.path.join(se_dir, "components.md")
        faults_dest = os.path.join(se_dir, "faults")

        # 检查是否已有数据（非空 components.md）
        if os.path.exists(comp_dest):
            with open(comp_dest, "r", encoding="utf-8") as f:
                if f.read().strip():
                    skipped += 1
                    continue

        # 复制 components.md
        if os.path.exists(archived_comp):
            shutil.copy2(archived_comp, comp_dest)

        # 复制 faults/ 目录内容
        if os.path.isdir(archived_faults):
            os.makedirs(faults_dest, exist_ok=True)
            for fname in os.listdir(archived_faults):
                if not fname.endswith(".md"):
                    continue
                src_file = os.path.join(archived_faults, fname)
                dst_file = os.path.join(faults_dest, fname)
                if not os.path.exists(dst_file):
                    shutil.copy2(src_file, dst_file)

        restored += 1

    if restored > 0 or skipped > 0:
        print(f"  {eq_name}: {restored} copied, {skipped} skipped (already have data)")
    return restored > 0


def scan_and_restore(base_dir: str):
    """扫描目录下所有含 _archive/ 的设备目录并恢复数据。"""
    print(f"\nScanning: {base_dir}\n")

    total_restored = 0
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ("_archive", "kb_exports", "__pycache__")]
        if "_archive" in os.listdir(root):
            if restore_equipment_dir(root):
                total_restored += 1

    print(f"\nDone. Restored data for {total_restored} equipment directories.\n")


def main():
    if len(sys.argv) > 1:
        base_dir = sys.argv[1]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "power"))

    base_dir = os.path.normpath(base_dir)
    if not os.path.isdir(base_dir):
        print(f"Directory not found: {base_dir}", file=sys.stderr)
        sys.exit(1)

    scan_and_restore(base_dir)


if __name__ == "__main__":
    main()
