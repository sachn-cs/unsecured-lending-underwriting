"""Semantic versioning bump script.

Item 80 from production roadmap.

Usage:
    python scripts/bump_version.py patch
    python scripts/bump_version.py minor
    python scripts/bump_version.py major
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _read_version(pyproject_path: Path) -> tuple[str, str]:
    content = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("version not found in pyproject.toml")
    return content, match.group(0)


def _bump(version: str, part: str) -> str:
    prefix, rest = version.split('"', 1)
    major, minor, patch = map(int, rest.rstrip('"').split("."))
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f'{prefix}"{major}.{minor}.{patch}"'


def bump(pyproject_path: Path, part: str) -> str:
    content, old_line = _read_version(pyproject_path)
    new_line = _bump(old_line, part)
    new_content = content.replace(old_line, new_line, 1)
    pyproject_path.write_text(new_content, encoding="utf-8")
    new_version = new_line.split('"')[1]
    return new_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump semantic version in pyproject.toml")
    parser.add_argument("part", choices=["patch", "minor", "major"], help="version part to bump")
    parser.add_argument("--path", type=Path, default=Path("pyproject.toml"), help="path to pyproject.toml")
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"file not found: {args.path}", file=sys.stderr)
        return 1

    new_version = bump(args.path, args.part)
    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
