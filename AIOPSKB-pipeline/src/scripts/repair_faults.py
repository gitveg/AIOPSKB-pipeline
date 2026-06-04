#!/usr/bin/env python3
"""Repair script: fix duplicate header rows and search-fallback rows in fault .md files.

Strategy for DUPLICATE_HEADER files:
  - These files have pattern: header → fallback/placeholder row → blank → header again → real data
  - Keep everything from the SECOND header onward (discard first header section)

Strategy for SEARCH_UNAVAILABLE files (without duplicate header):
  - These need manual review, log them for attention
"""

import os
import re
from pathlib import Path

POWER_DIR = Path(__file__).resolve().parent.parent / "data" / "power"
HEADER_PAT = re.compile(r"^\|\s*故障名称\s*\|.*D1.*D9")


def find_all_fault_files():
    faults = []
    for root, dirs, files in os.walk(POWER_DIR):
        if "faults" in root.split(os.sep):
            for f in files:
                if f.endswith(".md"):
                    faults.append(Path(root) / f)
    return sorted(faults)


def analyze_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header_lines = []
    data_start = 0
    has_search = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if HEADER_PAT.match(stripped):
            header_lines.append(i)
        if "搜索不可用" in stripped:
            has_search = True
        # First line that looks like real data (not header, not :---, not blank)
        if (stripped.startswith("|") and not HEADER_PAT.match(stripped)
                and not stripped.startswith("| :---")):
            if data_start == 0:
                data_start = i

    return {
        "lines": lines,
        "header_indices": header_lines,
        "has_search": has_search,
        "data_start": data_start,
    }


def has_real_data_after(lines, header_idx):
    """Check if there's real data after a header line (not just blanks)."""
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if HEADER_PAT.match(stripped):
            return False
        if stripped.startswith("| :---") or stripped.startswith("|---|---"):
            continue
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) >= 2 and cells[1] not in ("—", "搜索不可用", "[搜索不可用]", ""):
                return True
            elif len(cells) >= 2 and cells[1] in ("—", "搜索不可用", "[搜索不可用]"):
                continue  # might be a fallback row, keep looking
    return False


def repair_duplicate_header(filepath, info):
    """Fix duplicate headers. Backup original as .bak."""
    lines = info["lines"]
    headers = info["header_indices"]

    if len(headers) < 2:
        return False

    first_header = headers[0]
    second_header = headers[1]

    # Case A: second header has real data after it, but first header doesn't
    #   → Keep from second header onward (first header section is fallback/empty)
    if has_real_data_after(lines, second_header) and not has_real_data_after(lines, first_header):
        new_lines = lines[second_header:]
        if len(new_lines) <= 1:
            return False

        bak_path = str(filepath) + ".bak"
        with open(bak_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True

    # Case B: first header has real data, second header is a trailing duplicate with no data
    #   → Remove the trailing header and blanks before it
    if has_real_data_after(lines, first_header) and not has_real_data_after(lines, second_header):
        # Remove from second header to end
        new_lines = lines[:second_header]

        # Also strip trailing blank lines
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()

        if len(new_lines) < 2:
            return False

        bak_path = str(filepath) + ".bak"
        with open(bak_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True

    # Case C: both headers have data — don't touch, needs manual review
    return False


def clean_search_fallback(filepath, info):
    """Remove lines containing search fallback if real data exists after."""
    lines = info["lines"]
    has_valid = any(
        line.strip().startswith("|")
        and "搜索不可用" not in line
        and not HEADER_PAT.match(line.strip())
        and not line.strip().startswith("| :---")
        and "—" not in line.split("|")[2] if len(line.split("|")) > 2 else True
        for line in lines
    )

    if not has_valid:
        return False  # no real data to keep, skip

    new_lines = []
    removed = False
    for line in lines:
        stripped = line.strip()
        if "搜索不可用" in stripped and stripped.startswith("|"):
            removed = True
            continue  # skip this fallback line
        new_lines.append(line)

    if not removed:
        return False

    bak_path = str(filepath) + ".bak"
    with open(bak_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return True


def main():
    fault_files = find_all_fault_files()
    print("Scanning {} fault files...".format(len(fault_files)))

    fixed_dup = 0
    fixed_search = 0
    skipped_no_data = 0
    manual_needed = []

    for fp in fault_files:
        info = analyze_file(fp)
        lines = info["lines"]
        headers = info["header_indices"]

        # Priority 1: Fix duplicate headers
        if len(headers) > 1:
            if repair_duplicate_header(fp, info):
                fixed_dup += 1
                # Re-analyze after fix
                info = analyze_file(fp)

        # Priority 2: Clean search fallback lines (if real data exists)
        if info["has_search"] and info["header_indices"]:
            if clean_search_fallback(fp, info):
                fixed_search += 1
                info = analyze_file(fp)

        # After fixes, check if file still has no valid data
        has_real = False
        for line in info["lines"]:
            stripped = line.strip()
            if not stripped.startswith("|") or HEADER_PAT.match(stripped):
                continue
            if stripped.startswith("| :---"):
                continue
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if len(cells) >= 2 and cells[1] not in ("—", "搜索不可用", "[搜索不可用]", ""):
                has_real = True
                break

        if not has_real:
            rel = str(fp.relative_to(POWER_DIR.parent.parent))
            skipped_no_data += 1
            manual_needed.append(rel)

    print("\n=== Repair Results ===")
    print("Duplicate headers fixed: {}".format(fixed_dup))
    print("Search fallback lines cleaned: {}".format(fixed_search))
    print("Files still needing manual content: {}".format(skipped_no_data))

    if manual_needed:
        print("\n--- Files with NO valid data (need fault knowledge) ---")
        for f in manual_needed:
            print("  " + f)

    # Clean up .bak files
    print("\nBackup files (.bak) preserved for review. Delete after verification.")


if __name__ == "__main__":
    main()
