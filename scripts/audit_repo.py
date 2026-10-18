"""Audit tracked repository files and history for public-release risks."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAX_HISTORY_BLOB_BYTES = 5 * 1024 * 1024
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
MODEL_WEIGHT_EXTENSIONS = {
    ".pkl",
    ".pickle",
    ".pt",
    ".pth",
    ".ckpt",
    ".onnx",
    ".safetensors",
    ".bin",
    ".h5",
    ".tflite",
}
DATASET_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".jsonl",
    ".ndjson",
    ".arrow",
    ".tfrecord",
    ".npz",
    ".npy",
    ".parquet",
    ".h5",
    ".hdf5",
    ".hdf",
    ".zip",
    ".tgz",
}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".tgz"}
RAW_MEDIA_EXTENSIONS = {".y4m", ".yuv", ".h264", ".h265", ".dng", ".raw"}
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
    "sk- API key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    "NVIDIA API key": re.compile(rb"\bnvapi-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    "Hugging Face token": re.compile(rb"\bhf_[A-Za-z0-9]{8,}\b", re.IGNORECASE),
}
API_KEY_ASSIGNMENT_PATTERN = re.compile(
    rb"\b(NEBIUS_API_KEY|api_key)[\"']?[ \t]*\]?[ \t]*(?:=|:)[ \t]*[\"']?"
    rb"([^\"'\s,;#}\]\)]+)",
    re.IGNORECASE,
)
YAML_KEY_ASSIGNMENT_PATTERN = re.compile(
    rb"(?m)^[ \t]*KEY\s*:\s*[\"']?([^\"'\s,;#}\]]+)"
)
PLACEHOLDER_VALUES = {
    "",
    "...",
    "changeme",
    "change-me",
    "example",
    "fake",
    "api_key",
    "key",
    "none",
    "null",
    "placeholder",
    "redacted",
    "replace-me",
    "your-api-key",
    "your-key-here",
    "dummy-key",
    "dummy-token",
    "example-key",
    "example-token",
    "fake-key",
    "fake-token",
    "placeholder-key",
    "placeholder-token",
    "replace-key",
    "replace-token",
}


def _git_output(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def tracked_paths(repo: Path) -> list[PurePosixPath]:
    return [
        PurePosixPath(path.decode("utf-8", errors="surrogateescape"))
        for path in _git_output(repo, "ls-files", "-z").split(b"\0")
        if path
    ]


def _is_archive(suffix: str) -> bool:
    return suffix in ARCHIVE_EXTENSIONS or suffix.startswith(".tar")


def _path_name_reasons(relative_path: PurePosixPath) -> list[str]:
    suffixes = [suffix.casefold() for suffix in relative_path.suffixes]
    name = relative_path.name.casefold()
    path_parts = {part.casefold() for part in relative_path.parts}
    reasons = []
    if any(suffix in MEDIA_EXTENSIONS for suffix in suffixes):
        reasons.append("video/audio extension")
    if any(suffix in RAW_MEDIA_EXTENSIONS for suffix in suffixes):
        reasons.append("raw video/image extension")
    if any(suffix in MODEL_WEIGHT_EXTENSIONS for suffix in suffixes):
        reasons.append("model-weight extension")
    if any(suffix in DATASET_EXTENSIONS for suffix in suffixes):
        reasons.append("dataset extension")
    if any(_is_archive(suffix) for suffix in suffixes):
        reasons.append("archive extension")
    if path_parts & DATASET_DIRECTORIES:
        reasons.append("dataset/recording directory")
    if (name.startswith(".env") and name != ".env.example") or name.endswith(".env"):
        reasons.append("environment file")
    return reasons


def _is_placeholder_value(value: bytes) -> bool:
    normalized = value.decode("ascii", errors="ignore").strip().casefold()
    placeholders = PLACEHOLDER_VALUES | {
        "not-a-real-key",
        "not-set",
        "sample",
        "token",
        "todo",
        "your_key_here",
        "your_api_key",
        "your-key-here",
        "str",
    }
    stripped = value.strip()
    if (
        stripped[:1].islower()
        and re.fullmatch(
            rb"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", stripped
        )
    ):
        return True
    return (
        normalized in placeholders
        or "http://" in normalized
        or "https://" in normalized
        or (normalized.startswith("<") and normalized.endswith(">"))
        or (len(normalized) >= 3 and set(normalized) == {"x"})
        or (len(normalized) >= 8 and set(normalized) <= {"*", "0"})
    )


def _credential_findings_bytes(data: bytes) -> set[str]:
    findings = {
        label for label, pattern in CREDENTIAL_PATTERNS.items() if pattern.search(data)
    }
    for match in API_KEY_ASSIGNMENT_PATTERN.finditer(data):
        if not _is_placeholder_value(match.group(2)):
            name = match.group(1).decode("ascii", errors="ignore").casefold()
            findings.add(f"{name} assignment")
    for match in YAML_KEY_ASSIGNMENT_PATTERN.finditer(data):
        if not _is_placeholder_value(match.group(1)):
            findings.add("key assignment")
    return findings


def _is_credential_finding(reason: str) -> bool:
    return (
        reason in CREDENTIAL_PATTERNS
        or reason.endswith(" assignment")
        or reason.startswith("credential pattern:")
    )


def _credential_findings(path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return []
    overlap = 512
    tail = b""
    findings: set[str] = set()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            data = tail + chunk
            findings.update(_credential_findings_bytes(data))
            tail = data[-overlap:]
    return sorted(findings)


def inspect_file(repo: Path, relative_path: PurePosixPath) -> dict[str, Any]:
    path = repo.joinpath(*relative_path.parts)
    try:
        size = path.lstat().st_size
    except FileNotFoundError:
        return {"path": relative_path, "size": None, "flags": ["missing from worktree"]}

    flags = _path_name_reasons(relative_path)
    suffixes = [suffix.casefold() for suffix in relative_path.suffixes]
    if any(suffix in IMAGE_EXTENSIONS for suffix in suffixes) and size > 500 * 1024:
        flags.append("image larger than 500 KB")
    if size > 1_000_000:
        flags.append("file larger than 1 MB")
    flags.extend(_credential_findings(path))
    return {"path": relative_path, "size": size, "flags": sorted(set(flags))}


def _history_paths(repo: Path) -> set[PurePosixPath]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--all", "--name-only", "--format="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode and "does not have any commits yet" not in result.stderr:
        raise RuntimeError(result.stderr.strip() or "git log failed")
    return {
        PurePosixPath(line)
        for line in result.stdout.splitlines()
        if line
    }


def _history_blob_records(
    repo: Path,
) -> tuple[
    list[tuple[str, PurePosixPath | None, int]],
    list[str],
    list[tuple[PurePosixPath, int]],
]:
    output = _git_output(repo, "rev-list", "--all", "--objects")
    object_paths: dict[str, PurePosixPath] = {}
    object_ids = []
    for line in output.splitlines():
        object_id, separator, path = line.partition(b" ")
        identifier = object_id.decode("ascii", errors="ignore")
        if not identifier:
            continue
        object_ids.append(identifier)
        if separator and path:
            object_paths.setdefault(
                identifier,
                PurePosixPath(path.decode("utf-8", errors="surrogateescape")),
            )
    if not object_ids:
        return [], [], []

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        input=("\n".join(object_ids) + "\n").encode("ascii"),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())

    blobs = []
    warnings = []
    oversized = []
    for line in result.stdout.splitlines():
        object_id, object_type, object_size = line.split()
        if object_type != b"blob":
            continue
        identifier = object_id.decode("ascii")
        size = int(object_size)
        path = object_paths.get(identifier)
        if size > MAX_HISTORY_BLOB_BYTES:
            label = str(path) if path else f"blob {identifier}"
            warnings.append(
                f"Skipped content scan for history blob over 5 MB: {label} ({size} bytes)."
            )
            oversized.append(
                (path or PurePosixPath(f"blob-{identifier}"), size)
            )
        else:
            blobs.append((identifier, path, size))
    return blobs, warnings, oversized


def _scan_history_blob_chunks(
    repo: Path,
    blobs: list[tuple[str, PurePosixPath | None, int]],
) -> dict[PurePosixPath, set[str]]:
    findings: dict[PurePosixPath, set[str]] = defaultdict(set)
    for start in range(0, len(blobs), 64):
        chunk = blobs[start : start + 64]
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            input=("".join(f"{object_id}\n" for object_id, _, _ in chunk)).encode("ascii"),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
        output = result.stdout
        cursor = 0
        for object_id, path, _ in chunk:
            header_end = output.find(b"\n", cursor)
            if header_end < 0:
                raise RuntimeError("git cat-file returned an incomplete history blob")
            header = output[cursor:header_end].split()
            if len(header) != 3 or header[1] != b"blob":
                raise RuntimeError("git cat-file returned an unexpected object")
            size = int(header[2])
            blob_start = header_end + 1
            blob_end = blob_start + size
            content_findings = _credential_findings_bytes(output[blob_start:blob_end])
            if content_findings:
                history_path = path or PurePosixPath(f"blob-{object_id}")
                findings[history_path].update(
                    f"credential pattern: {label}" for label in content_findings
                )
            cursor = blob_end + 1
    return findings


def history_findings(
    repo: Path,
) -> tuple[dict[PurePosixPath, set[str]], list[str]]:
    blobs, warnings, oversized = _history_blob_records(repo)
    blob_paths = [path for _, path, _ in blobs if path is not None]
    path_sizes: dict[PurePosixPath, int] = {}
    for _, path, size in blobs:
        if path is not None:
            path_sizes[path] = max(size, path_sizes.get(path, 0))
    for path, size in oversized:
        path_sizes[path] = max(size, path_sizes.get(path, 0))

    findings: dict[PurePosixPath, set[str]] = defaultdict(set)
    for path, _size in oversized:
        findings[path].add("oversized_blob")
    for path in _history_paths(repo) | set(blob_paths):
        reasons = _path_name_reasons(path)
        suffixes = [suffix.casefold() for suffix in path.suffixes]
        if any(suffix in IMAGE_EXTENSIONS for suffix in suffixes) and path_sizes.get(
            path, 0
        ) > 500 * 1024:
            reasons.append("image larger than 500 KB")
        if reasons:
            findings[path].update(reasons)

    for path, reasons in _scan_history_blob_chunks(repo, blobs).items():
        findings[path].update(reasons)
    return dict(findings), sorted(set(warnings))


def _allowlist(path: Path) -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = loaded.get("files", {})
    if not isinstance(entries, dict):
        raise ValueError("allowlist 'files' must be a mapping")
    result: dict[str, dict[str, Any]] = {}
    for name, value in entries.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("every allowlist entry must map a path to types and justification")
        justification = value.get("justification")
        types = value.get("types")
        if (
            not isinstance(justification, str)
            or not justification.strip()
            or not isinstance(types, list)
            or not types
            or any(not isinstance(reason, str) or not reason.strip() for reason in types)
        ):
            raise ValueError("every allowlist entry needs finding types and a justification")
        result[name] = {
            "types": set(types),
            "justification": justification.strip(),
        }
    return result


def _display_path(path: PurePosixPath) -> str:
    return str(path).replace("|", "\\|").replace("\n", "\\n").replace("`", "\\`")


def _display_justification(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _allowlist_description(entry: dict[str, Any] | None, waived: set[str]) -> str | None:
    if not entry or not waived:
        return None
    types = ", ".join(sorted(waived))
    return f"{types}: {entry['justification']}"


def build_report(
    rows: list[dict[str, Any]],
    history: dict[PurePosixPath, set[str]],
    history_warnings: list[str],
    allowlist: dict[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    unapproved = set()
    active_allowlist_paths = set()

    def waived_findings(path: str, reasons: set[str] | list[str]) -> set[str]:
        entry = allowlist.get(path)
        if not entry:
            return set()
        return {
            reason
            for reason in reasons
            if reason in entry["types"] and not _is_credential_finding(reason)
        }

    for row in rows:
        path = str(row["path"])
        flags = set(row["flags"])
        waived = waived_findings(path, flags)
        entry = allowlist.get(path)
        row["justification"] = _allowlist_description(entry, waived)
        if row["flags"]:
            if waived:
                active_allowlist_paths.add(path)
            if flags - waived:
                unapproved.add(path)

    history_justifications = {}
    for path, reasons in history.items():
        display_path = str(path)
        waived = waived_findings(display_path, reasons)
        entry = allowlist.get(display_path)
        justification = _allowlist_description(entry, waived)
        history_justifications[path] = justification
        if waived:
            active_allowlist_paths.add(display_path)
        if set(reasons) - waived:
            unapproved.add(display_path)

    stale_allowlist = sorted(set(allowlist) - active_allowlist_paths)
    status = "PASS" if not unapproved else "FAIL"
    lines = [
        "# Public repository audit",
        "",
        "Generated by `scripts/audit_repo.py` from git-tracked files and reachable Git history.",
        "",
        f"**Result: {status}**",
        "",
        f"- Tracked files scanned: {len(rows)}",
        f"- Files with audit flags: {sum(bool(row['flags']) for row in rows)}",
        f"- Unallowlisted findings: {len(unapproved)}",
        f"- Historical paths with findings: {len(history)}",
        f"- History blobs skipped above 5 MB: {len(history_warnings)}",
        "",
        "History detection checks file names for media, model-weight, dataset, archive, and "
        "environment-file indicators, and scans blob content for credential patterns. "
        "Blobs over 5 MB are reported as `oversized_blob`; their content scan is skipped and "
        "they require an explicit path-and-type allowlist entry. "
        "An allowlisted `oversized_blob` is not content-scanned and is covered only by CI "
        "gitleaks. "
        "CI also runs the `secrets` job's `gitleaks (full history)` step "
        "(`.github/workflows/ci.yml`).",
        "",
        "## Tracked-file inventory",
        "",
        "| Path | Size (bytes) | Findings | Allowlisted types and justification |",
        "|---|---:|---|---|",
    ]
    for row in rows:
        findings_text = ", ".join(row["flags"]) or "—"
        justification = row["justification"] or "—"
        size = row["size"] if row["size"] is not None else "missing"
        lines.append(
            f"| `{_display_path(row['path'])}` | {size} | {findings_text} | "
            f"{_display_justification(justification)} |"
        )

    lines.extend(["", "## Historical findings", ""])
    if history:
        lines.extend(
            [
                "Historical media, dataset, model-weight, environment-file, or credential "
                "hits require a justified allowlist entry. History was not rewritten.",
                "",
                "| Path | Findings | Allowlisted types and justification |",
                "|---|---|---|",
            ]
        )
        for path, reasons in sorted(history.items(), key=lambda item: str(item[0])):
            justification = history_justifications.get(path) or "—"
            lines.append(
                f"| `{_display_path(path)}` | {', '.join(sorted(reasons))} | "
                f"{_display_justification(justification)} |"
            )
    else:
        lines.append("No historical file-name or blob-content findings were detected.")

    lines.extend(["", "## History scan warnings", ""])
    if history_warnings:
        lines.extend(f"- {warning}" for warning in history_warnings)
    else:
        lines.append("No history blobs above 5 MB were skipped.")

    lines.extend(["", "## Stale allowlist entries", ""])
    if stale_allowlist:
        lines.extend(f"- `{_display_path(PurePosixPath(path))}`" for path in stale_allowlist)
    else:
        lines.append("No stale allowlist entries.")

    lines.extend(["", "## Review", ""])
    if unapproved:
        lines.append("Unallowlisted findings require review before this audit can pass:")
        lines.extend(
            f"- `{_display_path(PurePosixPath(path))}`" for path in sorted(unapproved)
        )
    else:
        lines.append(
            "All current and historical findings are justified by the allowlist. "
            "No unallowlisted private-key material, credentials, environment files, "
            "media, model weights, or datasets were found."
        )
    return "\n".join(lines) + "\n", sorted(unapproved)


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
        shallow = _git_output(repo, "rev-parse", "--is-shallow-repository").decode().strip()
        if shallow == "true":
            raise RuntimeError("refusing to audit a shallow clone; full Git history is required")
        allowlist = _allowlist(allowlist_path)
        for _ in range(10):
            rows = [inspect_file(repo, path) for path in tracked_paths(repo)]
            history, history_warnings = history_findings(repo)
            report, unapproved = build_report(rows, history, history_warnings, allowlist)
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
        f"{len(history)} historical paths with findings; "
        f"{len(history_warnings)} history blobs skipped above 5 MB."
    )
    return 1 if unapproved else 0


if __name__ == "__main__":
    raise SystemExit(main())
