#!/usr/bin/env python3
"""Diagnostic script: scan all fault .md files for data quality issues."""

import os
import re
from pathlib import Path

POWER_DIR = Path(__file__).resolve().parent.parent / "data" / "power"


def find_all_fault_files():
    faults = []
    for root, dirs, files in os.walk(POWER_DIR):
        if "faults" in root.split(os.sep):
            for f in files:
                if f.endswith(".md"):
                    faults.append(Path(root) / f)
    return sorted(faults)


def parse_fault_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    issues = []
    header_indices = []
    data_rows = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\|\s*故障名称\s*\|.*D1.*D9", stripped):
            header_indices.append(i + 1)
        elif re.match(r"^\|\s*:---", stripped):
            pass  # separator row, skip
        elif stripped.startswith("|"):
            data_rows.append((i + 1, stripped))

    # Issue 1: duplicate header
    if len(header_indices) > 1:
        issues.append("DUPLICATE_HEADER: lines " + str(header_indices))

    # Issue 2: no header
    if len(header_indices) == 0:
        issues.append("NO_HEADER")

    # Issue 3: contains search-unavailable text
    for lnum, content in data_rows:
        if "搜索不可用" in content:
            issues.append("SEARCH_UNAVAILABLE: line " + str(lnum))
            break

    # Issue 4: placeholder-only (all data cells are dash)
    has_valid = False
    for lnum, content in data_rows:
        cells = [c.strip() for c in content.split("|")[1:-1]]
        if len(cells) >= 2:
            d1 = cells[1] if len(cells) > 1 else ""
            if d1 and d1 not in ("—", "搜索不可用", "[搜索不可用]", ""):
                has_valid = True
                break
    if not has_valid and len(data_rows) > 0:
        issues.append("NO_VALID_DATA")

    return header_indices, data_rows, issues


def main():
    fault_files = find_all_fault_files()
    print("Scanning {} fault files...\n".format(len(fault_files)))

    stats = {
        "clean": 0,
        "duplicate_header": [],
        "search_unavailable": [],
        "no_valid_data": [],
        "other": [],
    }

    for fp in fault_files:
        rel = str(fp.relative_to(POWER_DIR.parent.parent))
        header_idx, data_rows, issues = parse_fault_file(fp)

        if not issues:
            stats["clean"] += 1
        else:
            for iss in issues:
                if iss.startswith("DUPLICATE_HEADER"):
                    stats["duplicate_header"].append((rel, iss))
                if iss.startswith("SEARCH_UNAVAILABLE"):
                    stats["search_unavailable"].append((rel, iss))
                if iss.startswith("NO_VALID_DATA"):
                    stats["no_valid_data"].append((rel, iss))

    print("=" * 70)
    print("CLEAN:  {}".format(stats["clean"]))
    print("ISSUES: {}".format(
        len(stats["duplicate_header"]) + len(stats["search_unavailable"]) + len(stats["no_valid_data"])))
    print("=" * 70)

    print("\n--- TYPE 1: SEARCH_UNAVAILABLE ({}) ---".format(len(stats["search_unavailable"])))
    for rel, iss in stats["search_unavailable"]:
        print("  {} | {}".format(rel, iss))

    print("\n--- TYPE 2: DUPLICATE_HEADER ({}) ---".format(len(stats["duplicate_header"])))
    for rel, iss in stats["duplicate_header"]:
        print("  {} | {}".format(rel, iss))

    print("\n--- TYPE 3: NO_VALID_DATA ({}) ---".format(len(stats["no_valid_data"])))
    for rel, iss in stats["no_valid_data"]:
        print("  {} | {}".format(rel, iss))

    # Summary counts
    print("\n--- SUMMARY ---")
    print("Total fault files: {}".format(len(fault_files)))
    print("Clean: {}".format(stats["clean"]))
    print("With search_unavailable: {}".format(len(stats["search_unavailable"])))
    print("With duplicate_header: {}".format(len(stats["duplicate_header"])))
    print("With no_valid_data: {}".format(len(stats["no_valid_data"])))


if __name__ == "__main__":
    main()
