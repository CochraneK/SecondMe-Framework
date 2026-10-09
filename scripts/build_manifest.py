#!/usr/bin/env python3
"""Maintainer-only: build release manifest and initial template lock from Git files.

Usage: python scripts/build_manifest.py 0.3.0
Never copy private data or history into the public framework repository.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SOURCE = "CochraneK/Secondme-Framework"
ALLOWED = ("framework/", "prompts/", "templates/")


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def main(args: list[str]) -> int:
    if len(args) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", args[0]):
        print("Usage: python scripts/build_manifest.py <major.minor.patch>", file=sys.stderr)
        return 2
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0")
    files = {}
    for name in sorted(filter(None, tracked)):
        if name.startswith(ALLOWED) and name.endswith(".md"):
            path = Path(name)
            if path.is_symlink() or not path.is_file():
                raise ValueError("Unsafe tracked framework path: " + name)
            files[name] = blob_sha(path.read_bytes())
    if not files:
        raise ValueError("No official Markdown files found")
    record = {"schema": 1, "source": SOURCE, "version": args[0], "files": files}
    encoded = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    dest = Path(".secondme")
    if dest.is_symlink():
        raise ValueError("Unsafe .secondme directory")
    dest.mkdir(exist_ok=True)
    (dest / "framework-manifest.json").write_text(encoded, encoding="utf-8")
    (dest / "framework-lock.json").write_text(encoded, encoding="utf-8")
    print(f"Prepared v{args[0]}: {len(files)} eligible files. Review the diff before pushing.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
