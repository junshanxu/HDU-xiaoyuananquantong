#!/usr/bin/env python3
"""Provision or verify a local clone of the HDU safety tool without credentials."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPOSITORY = "https://github.com/yuaiccc/HDU-xiaoyuananquantong.git"
REQUIRED_FILES = ("server.py", "xy_auto.py", "xy_bank.json")


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def valid_tool_dir(target: Path) -> bool:
    return target.is_dir() and all((target / name).is_file() for name in REQUIRED_FILES)


def question_count(bank_path: Path) -> int:
    with bank_path.open(encoding="utf-8") as handle:
        bank = json.load(handle)
    if not isinstance(bank, (dict, list)) or not bank:
        raise ValueError("题库不是非空 JSON 对象或数组")
    return len(bank)


def main() -> int:
    parser = argparse.ArgumentParser(description="准备本地 HDU 安全教育工具及题库")
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="工具克隆目录；目录不存在时才会创建并克隆",
    )
    args = parser.parse_args()
    target = args.target.expanduser().resolve()

    if target.exists() and not valid_tool_dir(target):
        print(f"目标目录已存在但不是完整工具目录：{target}", file=sys.stderr)
        return 2
    if not target.exists():
        if not target.parent.exists():
            print(f"父目录不存在：{target.parent}", file=sys.stderr)
            return 2
        try:
            run("git", "clone", "--depth", "1", REPOSITORY, str(target))
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"无法克隆工具仓库：{error}", file=sys.stderr)
            return 1

    try:
        count = question_count(target / "xy_bank.json")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"题库校验失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps({"toolPath": str(target), "questionCount": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
