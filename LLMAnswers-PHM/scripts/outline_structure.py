"""
Markdown 大纲层次结构抽取工具

用法：
  python outline_structure.py <file>              # 只抽取 ## 二级标题
  python outline_structure.py <file> --sub         # 抽取 ## 和 ### 层级
  python outline_structure.py <file> -o out.md     # 输出到文件
"""
import argparse
import re
import sys
from pathlib import Path


def extract_structure(filepath: str, level: int) -> str:
    text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    filename = Path(filepath).name

    if level == 2:
        tag = "二级标题一览"
        patterns = [r"^## .+"]
    else:
        tag = "二级 + 三级标题一览"
        patterns = [r"^## .+", r"^### .+"]

    combined = "|".join(f"({p})" for p in patterns)
    regex = re.compile(combined, re.MULTILINE)

    lines = [f"# {filename} — {tag}", ""]
    for line in text.splitlines():
        if regex.match(line):
            lines.append(line)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Markdown 大纲层次结构抽取")
    parser.add_argument("file", help="Markdown 文件路径")
    parser.add_argument("--sub", action="store_true", help="同时抽取 ### 三级标题")
    parser.add_argument("-o", "--output", help="输出到文件（默认输出到终端）")
    args = parser.parse_args()

    level = 3 if args.sub else 2
    result = extract_structure(args.file, level)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8", newline="\n")
        print(f"已输出到: {args.output}")
    else:
        sys.stdout.buffer.write(result.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
