import os


def ensure_data_dir(base_dir: str):
    os.makedirs(base_dir, exist_ok=True)


def write_kb_file(filepath: str, content: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, filepath)


def read_kb_file(filepath: str) -> str:
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    return ""
