#!/usr/bin/env python3
"""SecondMe safe updater: only public Markdown framework files are eligible.

No dependency beyond the Python standard library.
No user files are uploaded. Run locally or by the optional GitHub workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM = "CochraneK/Secondme-Framework"
MANIFEST_PATH = ".secondme/framework-manifest.json"
LOCK_PATH = ".secondme/framework-lock.json"
NOTICE_PATH = ".secondme/UPDATE_NOTICE.md"
MAX_FILES = 200
MAX_FILE_BYTES = 300_000
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ALLOWED_DIRS = frozenset(("framework", "prompts", "templates"))


class UpdateError(Exception):
    pass


def git_blob_sha(content: bytes) -> str:
    """Match the SHA Git uses for a blob."""
    header = b"blob " + str(len(content)).encode("ascii") + b"\0"
    return hashlib.sha1(header + content).hexdigest()


def allowed_path(name: str) -> bool:
    if not isinstance(name, str) or "\\" in name or "\x00" in name:
        return False
    pieces = name.split("/")
    return (
        len(pieces) >= 2
        and pieces[0] in ALLOWED_DIRS
        and all(p not in (".", "..") and SEGMENT_RE.fullmatch(p) for p in pieces)
        and name.endswith(".md")
        and not any(p.startswith(".") for p in pieces[1:])
    )


def safe_destination(root: Path, rel: str) -> Path:
    if not allowed_path(rel):
        raise UpdateError("Disallowed upstream file path: " + repr(rel))
    dest = root / rel
    parent = dest.parent
    while parent != root:
        if parent.is_symlink():
            raise UpdateError("Refusing symlink directory: " + rel)
        parent = parent.parent
    if dest.is_symlink() or (dest.exists() and not dest.is_file()):
        raise UpdateError("Refusing nonregular file: " + rel)
    return dest


def load_record(path: Path, *, remote: bool = False) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise UpdateError("Cannot read valid JSON in " + str(path)) from exc
    return validate_record(obj, remote=remote)


def validate_record(obj: object, *, remote: bool) -> dict:
    label = "release manifest" if remote else "local framework lock"
    if not isinstance(obj, dict) or obj.get("schema") != 1:
        raise UpdateError("Unsupported " + label + " schema")
    if obj.get("source") != UPSTREAM:
        raise UpdateError("Unexpected " + label + " upstream")
    version = obj.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise UpdateError("Invalid " + label + " version")
    files = obj.get("files")
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise UpdateError("Invalid " + label + " file map")
    for name, sha in files.items():
        if not allowed_path(name) or not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise UpdateError("Unsafe file entry in " + label + ": " + repr(name))
    return obj


def fetch_bytes(url: str, limit: int = MAX_FILE_BYTES) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "secondme-framework-updater/0.2"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Upstream fetch failed; nothing should be applied") from exc
    if len(body) > limit:
        raise UpdateError("Remote response exceeds size limit")
    return body


def fetch_release() -> dict:
    url = "https://raw.githubusercontent.com/" + UPSTREAM + "/main/" + MANIFEST_PATH
    try:
        manifest = json.loads(fetch_bytes(url, MAX_FILE_BYTES).decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise UpdateError("Invalid upstream manifest") from exc
    return validate_record(manifest, remote=True)


def fetch_official_file(name: str, expected_sha: str) -> bytes:
    from urllib.parse import quote

    url = "https://raw.githubusercontent.com/" + UPSTREAM + "/main/" + quote(name)
    body = fetch_bytes(url)
    if git_blob_sha(body) != expected_sha:
        raise UpdateError(
            "Upstream content/hash mismatch for " + name +
            ". Release manifest may be out of sync; stopped safely."
        )
    return body


def version_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))


def produce_update(
    root: Path,
    current: dict,
    upstream: dict,
    retrieve=fetch_official_file,
    *,
    apply: bool,
) -> dict:
    """Compute the complete update in memory; write only allowed files on --apply.

    A locally modified file is NEVER overwritten. Deleted upstream files stay.
    """
    root = root.resolve()
    local_files = current["files"]
    remote_files = upstream["files"]
    if version_tuple(upstream["version"]) < version_tuple(current["version"]):
        raise UpdateError("Refusing an upstream downgrade")
    if (
        upstream["version"] == current["version"]
        and remote_files != local_files
    ):
        raise UpdateError("Release content changed without a version bump")
    if (
        upstream["version"] == current["version"]
        and remote_files == local_files
    ):
        return {
            "from": current["version"], "to": upstream["version"],
            "modified": [], "reconciled": [], "conflicts": [],
            "upstream_removed": [], "unchanged_count": len(local_files),
            "applied": apply, "stage_paths": []
        }
    modified: dict[str, bytes] = {}
    reconciled: dict[str, str] = {}
    conflicts: list[str] = []
    removed: list[str] = []
    unchanged: list[str] = []
    for name, target_sha in sorted(remote_files.items()):
        path = safe_destination(root, name)
        baseline = local_files.get(name)
        if path.exists():
            try:
                observed = git_blob_sha(path.read_bytes())
            except OSError as exc:
                raise UpdateError("Cannot inspect local file " + name) from exc
            if observed == target_sha:
                if baseline != target_sha:
                    reconciled[name] = target_sha
                else:
                    unchanged.append(name)
            elif baseline is None or observed != baseline:
                conflicts.append(name)
            else:
                modified[name] = retrieve(name, target_sha)
                reconciled[name] = target_sha
        elif baseline is not None:
            # Local deletion is a user change; do not silently re-create it.
            conflicts.append(name)
        else:
            modified[name] = retrieve(name, target_sha)
            reconciled[name] = target_sha

    for name in sorted(set(local_files) - set(remote_files)):
        removed.append(name)  # Never delete a local file because upstream removed it.

    result = {
        "from": current["version"], "to": upstream["version"],
        "modified": sorted(modified), "reconciled": sorted(reconciled),
        "conflicts": conflicts, "upstream_removed": removed,
        "unchanged_count": len(unchanged), "applied": False
    }

    if not apply:
        return result

    # Everything fetched and verified before any local write.
    for name, content in modified.items():
        path = safe_destination(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    new_lock = dict(current)
    new_lock["files"] = {**local_files, **reconciled}
    if not conflicts and not removed:
        new_lock["version"] = upstream["version"]

    changed = bool(reconciled or (new_lock["version"] != current["version"]))
    if changed:
        lock_path = root / LOCK_PATH
        if lock_path.is_symlink() or not lock_path.is_file():
            raise UpdateError("Unsafe or missing framework lock")
        lock_path.write_text(
            json.dumps(new_lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if changed or conflicts or removed:
        notice = [
            "# SecondMe 框架更新报告", "",
            "**仅针对公开框架文件。未读取、上传或改动个人资料目录。**", "",
            "- 原版本：" + current["version"],
            "- 检查到上游版本：" + upstream["version"],
            "- 可自动升级：" + str(len(modified)) + " 个文件",
            "- 已与目标版本一致：" + str(len(reconciled) - len(modified)) + " 个文件",
            "- 需人工处理：" + str(len(conflicts)) + " 个文件", "",
        ]
        if conflicts:
            notice.extend([
                "## 请人工比较（以下文件未覆盖）", "",
                *("- `" + name + "`" for name in conflicts), "",
                "这些路径上的文件已被使用者改动、删除或与官方版本冲突。",
                "保留使用者原文件；不要用升级功能强制覆盖。", "",
            ])
        if removed:
            notice.extend([
                "## 上游不再列出的文件（本地未删除）", "",
                *("- `" + name + "`" for name in removed), "",
            ])
        notice.append(
            "若仍有冲突，锁文件的整体版本不会标为已完整升级。"
        )
        notice_path = root / NOTICE_PATH
        if notice_path.is_symlink():
            raise UpdateError("Unsafe update notice symlink")
        notice_path.parent.mkdir(parents=True, exist_ok=True)
        notice_path.write_text("\n".join(notice) + "\n", encoding="utf-8")
    result["applied"] = True
    result["stage_paths"] = (
        sorted(modified)
        + ([LOCK_PATH] if changed else [])
        + ([NOTICE_PATH] if (changed or conflicts or removed) else [])
    )
    return result


def render_pr_body(result: dict) -> str:
    lines = [
        "## SecondMe Framework 更新建议", "",
        "仅同步 `framework/`、`prompts/`、`templates/` 中的官方 Markdown 文件。",
        "用户自己的私人资料、配置、原始记忆不在更新范围内。", "",
        "- 本地版本：" + result["from"],
        "- 上游版本：" + result["to"],
        "- 自动更新的文件：" + str(len(result["modified"])),
        "- 需要人工比较：" + str(len(result["conflicts"])),
        "- 上游删除但本地保留：" + str(len(result["upstream_removed"])),
        "",
    ]
    if result["conflicts"]:
        lines += [
            "### ⚠ 有自定义修改，以下文件未被覆盖", "",
            *("- `" + name + "`" for name in result["conflicts"]), "",
            "请人工比较后决定是否采用更新；不要直接覆盖。", "",
        ]
    if result["upstream_removed"]:
        lines += [
            "### 上游已移除的路径（仍在私有仓库保留）", "",
            *("- `" + name + "`" for name in result["upstream_removed"]), "",
        ]
    lines += [
        "### 合并前检查", "",
        "- [ ] 查看 Diff，确认没有改动个人资料或个性化设置",
        "- [ ] 阅读新增的官方提示词与理论边界",
        "- [ ] 如有冲突，决定是否手动合并用户定制内容",
        "- [ ] 如有数据格式升级，先做好备份并单独迁移",
        "",
        "> 更新器不会执行上游代码、删除私有数据或自动合并 PR。"
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Privacy-first SecondMe updater")
    parser.add_argument("--apply", action="store_true", help="Apply allowlisted updates")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--report", help="Write a PR description file")
    parser.add_argument("--stage-paths", help="Write NUL-delimited allowlisted paths to stage")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if (root / ".secondme").is_symlink():
            raise UpdateError("Refusing symlink state directory")
        lock = load_record(root / LOCK_PATH)
        release = fetch_release()
        result = produce_update(root, lock, release, apply=args.apply)
        if args.report:
            Path(args.report).write_text(render_pr_body(result), encoding="utf-8")
        if args.stage_paths:
            with Path(args.stage_paths).open("wb") as out:
                for path in result.get("stage_paths", []):
                    out.write(path.encode("utf-8") + b"\0")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["conflicts"] or result["upstream_removed"]:
            print("Manual review required; conflicting paths were not overwritten.", file=sys.stderr)
        return 0
    except UpdateError as exc:
        print("SecondMe updater stopped safely: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
