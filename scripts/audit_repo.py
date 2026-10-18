"""Audit tracked repository files for public-release risks."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".mpeg",
    ".mpg",
    ".flv",
    ".wmv",
    ".3gp",
    ".mxf",
    ".mts",
    ".m2ts",
    ".wav",
    ".mp3",
    ".aac",
    ".m4a",
    ".m4b",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".aiff",
    ".aif",
    ".aifc",
    ".wma",
    ".amr",
    ".caf",
    ".ac3",
    ".mid",
    ".midi",
}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".svg",
    ".heic",
    ".heif",
    ".ico",
}
DATASET_EXTENSIONS = {
    ".npz",
    ".npy",
    ".parquet",
    ".h5",
    ".hdf5",
    ".hdf",
    ".zip",
    ".tgz",
}
DATASET_DIRECTORIES = {"data", "datasets", "recordings"}
PRIVATE_KEY_PATTERN = re.compile(
    rb"-----BEGIN (?:[A-Z0-9]+(?: [A-Z0-9]+)* )?PRIVATE "
    rb"KEY-----"
    rb"|-----BEGIN PGP PRIVATE "
    rb"KEY BLOCK-----"
)
CREDENTIAL_PATTERNS = {
    "private-key material": PRIVATE_KEY_PATTERN,
    "AWS access-key ID": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
}


def _git_output(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def tracked_paths(repo: Path) -> list[PurePosixPath]:
    return [
        PurePosixPath(path.decode("utf-8", errors="surrogateescape"))
        for path in _git_output(repo, "ls-files", "-z").split(b"\0")
        if path
    ]


def history_media_and_datasets(repo: Path) -> list[tuple[PurePosixPath, str]]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--all",
            "--diff-filter=A",
            "--name-only",
            "--format=",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode and "does not have any commits yet" not in result.stderr:
        raise RuntimeError(result.stderr.strip() or "git log failed")

    paths = {
        PurePosixPath(line)
        for line in result.stdout.splitlines()
        if line
    }
    findings = []
    for path in sorted(paths, key=str):
        reasons = _history_reasons(path)
        if reasons:
            findings.append((path, ", ".join(reasons)))
    return findings


def _history_reasons(path: PurePosixPath) -> list[str]:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    reasons = []
    if any(suffix in MEDIA_EXTENSIONS or suffix in IMAGE_EXTENSIONS for suffix in suffixes):
        reasons.append("media")
    if any(suffix in DATASET_EXTENSIONS or suffix.startswith(".tar") for suffix in suffixes):
        reasons.append("dataset extension")
    if {part.lower() for part in path.parts} & DATASET_DIRECTORIES:
        reasons.append("dataset directory")
    return reasons


def _credential_findings(path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return []
    overlap = 256
    tail = b""
    findings: set[str] = set()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            data = tail + chunk
            findings.update(
                label
                for label, pattern in CREDENTIAL_PATTERNS.items()
                if pattern.search(data)
            )
            tail = data[-overlap:]
    return sorted(findings)


def inspect_file(repo: Path, relative_path: PurePosixPath) -> dict[str, Any]:
    path = repo.joinpath(*relative_path.parts)
    flags = []
    try:
        size = path.lstat().st_size
    except FileNotFoundError:
        return {"path": relative_path, "size": None, "flags": ["missing from worktree"]}

    suffixes = [suffix.lower() for suffix in relative_path.suffixes]
    name = relative_path.name.lower()
    path_parts = {part.lower() for part in relative_path.parts}
    if any(suffix in MEDIA_EXTENSIONS for suffix in suffixes):
        flags.append("video/audio extension")
    if (
        any(suffix in IMAGE_EXTENSIONS for suffix in suffixes)
        and size > 500 * 1024
    ):
        flags.append("image larger than 500 KB")
    if size > 1_000_000:
        flags.append("file larger than 1 MB")
    if any(suffix in DATASET_EXTENSIONS or suffix.startswith(".tar") for suffix in suffixes):
        flags.append("dataset/archive extension")
    if path_parts & DATASET_DIRECTORIES:
        flags.append("dataset/recording directory")
    if name.startswith(".env") and name != ".env.example":
        flags.append("environment file")
    flags.extend(_credential_findings(path))
    return {"path": relative_path, "size": size, "flags": flags}


def _allowlist(path: Path) -> dict[str, str]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = loaded.get("files", {})
    if not isinstance(entries, dict):
        raise ValueError("allowlist 'files' must be a mapping")
    result = {}
    for name, value in entries.items():
        if isinstance(value, dict):
            value = value.get("justification", "")
        if not isinstance(name, str) or not isinstance(value, str) or not value.strip():
            raise ValueError("every allowlist entry needs a path and justification")
        result[name] = value.strip()
    return result


def _display_path(path: PurePosixPath) -> str:
    return str(path).replace("|", "\\|").replace("\n", "\\n").replace("`", "\\`")


def build_report(
    rows: list[dict[str, Any]],
    history_findings: list[tuple[PurePosixPath, str]],
    allowlist: dict[str, str],
) -> tuple[str, list[str]]:
    unapproved = []
    for row in rows:
        row["justification"] = allowlist.get(str(row["path"]))
        if row["flags"] and not row["justification"]:
            unapproved.append(str(row["path"]))

    status = "PASS" if not unapproved else "FAIL"
    lines = [
        "# Public repository audit",
        "",
        "Generated by `scripts/audit_repo.py` from git-tracked files.",
        "",
        f"**Result: {status}**",
        "",
        f"- Tracked files scanned: {len(rows)}",
        f"- Files with audit flags: {sum(bool(row['flags']) for row in rows)}",
        f"- Unallowlisted flagged files: {len(unapproved)}",
        f"- Historical media/dataset paths: {len(history_findings)}",
        "",
        "## Tracked-file inventory",
        "",
        "| Path | Size (bytes) | Findings | Allowlist justification |",
        "|---|---:|---|---|",
    ]
    for row in rows:
        findings = ", ".join(row["flags"]) or "—"
        justification = row["justification"] or "—"
        justification = justification.replace("|", "\\|")
        size = row["size"] if row["size"] is not None else "missing"
        lines.append(
            f"| `{_display_path(row['path'])}` | {size} | {findings} | {justification} |"
        )
    lines.extend(["", "## Historical additions", ""])
    if history_findings:
        lines.extend(
            [
                "The following media or dataset paths were added in repository history. "
                "History was not rewritten.",
                "",
                "| Path | Finding |",
                "|---|---|",
            ]
        )
        lines.extend(
            f"| `{_display_path(path)}` | {reason} |" for path, reason in history_findings
        )
    else:
        lines.append(
            "No media or dataset paths were found in `git log --all "
            "--diff-filter=A --name-only`. History was not rewritten."
        )
    lines.extend(["", "## Review", ""])
    if unapproved:
        lines.append("Unallowlisted findings require review before this audit can pass:")
        lines.extend(f"- `{_display_path(PurePosixPath(path))}`" for path in unapproved)
    else:
        lines.append(
            "All current findings are justified by the allowlist; no unallowlisted "
            "private-key material, environment files, media, or datasets were found."
        )
    return "\n".join(lines) + "\n", unapproved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    allowlist_path = (args.allowlist or repo / "configs/public_audit_allowlist.yaml").resolve()
    report_path = (args.report or repo / "docs/evidence/f11/public-repo-audit.md").resolve()

    try:
        allowlist = _allowlist(allowlist_path)
        for _ in range(10):
            rows = [inspect_file(repo, path) for path in tracked_paths(repo)]
            history = history_media_and_datasets(repo)
            report, unapproved = build_report(rows, history, allowlist)
            current = (
                report_path.read_text(encoding="utf-8")
                if report_path.exists()
                else None
            )
            if current == report:
                break
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
        else:
            raise RuntimeError("generated report did not stabilize after 10 iterations")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Audit failed: {exc}")
        return 1

    print(
        f"Scanned {len(rows)} tracked files; {len(unapproved)} unallowlisted findings; "
        f"{len(history)} historical media/dataset paths."
    )
    return 1 if unapproved else 0


if __name__ == "__main__":
    raise SystemExit(main())
