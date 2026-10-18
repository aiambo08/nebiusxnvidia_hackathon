"""Generate and validate the installed dependency licence inventory."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import tomllib
from collections import deque
from pathlib import Path
from typing import Any

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LICENSE_DOCUMENT = ROOT / "docs/third-party-licenses.md"
BEGIN_MARKER = "<!-- BEGIN GENERATED DEPENDENCY LICENSES -->"
END_MARKER = "<!-- END GENERATED DEPENDENCY LICENSES -->"
LICENSE_OVERRIDES: dict[str, dict[str, str]] = {}
MARKER_TARGET = {
    "implementation_name": "cpython",
    "os_name": "posix",
    "platform_python_implementation": "CPython",
    "platform_system": "Linux",
    "python_full_version": "3.11.0",
    "python_version": "3.11",
    "sys_platform": "linux",
}
UNKNOWN_VALUES = {
    "",
    "unknown",
    "unknown license",
    "n/a",
    "none",
    "see license",
    "see license file",
}
COPYLEFT_PATTERN = re.compile(
    r"\b(?:AGPL|GPL|LGPL|MPL|EPL|CDDL|EUPL|OSL)(?:[- .]|v?\d|$)", re.IGNORECASE
)
NONCOMMERCIAL_PATTERN = re.compile(
    r"\b(?:NON[- ]?COMMERCIAL|CC[- ]?BY[- ]?NC|BUSL|COMMONS CLAUSE)\b",
    re.IGNORECASE,
)


def _marker_environment() -> dict[str, str]:
    return {**default_environment(), **MARKER_TARGET, "extra": ""}


def _marker_matches(requirement: Requirement, extras: set[str] | None = None) -> bool:
    if requirement.marker is None:
        return True
    environment = _marker_environment()
    values = extras or {""}
    return any(
        requirement.marker.evaluate({**environment, "extra": extra}) for extra in values
    )


def resolve_dependencies() -> tuple[dict[str, dict[str, Any]], list[str]]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    groups = {"runtime": project.get("dependencies", [])}
    groups.update(project.get("optional-dependencies", {}))
    installed = {
        canonicalize_name(distribution.metadata.get("Name", "")): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    records: dict[str, dict[str, Any]] = {}
    errors = []
    environment = _marker_environment()

    for group, roots in groups.items():
        queue: deque[tuple[Requirement, set[str]]] = deque()
        for text in roots:
            try:
                requirement = Requirement(text)
            except InvalidRequirement as exc:
                errors.append(f"Invalid {group} requirement {text!r}: {exc}")
                continue
            marker_extra = "" if group == "runtime" else group
            if requirement.marker and not requirement.marker.evaluate(
                {**environment, "extra": marker_extra}
            ):
                continue
            queue.append((requirement, set(requirement.extras)))

        visited: set[tuple[str, tuple[str, ...]]] = set()
        while queue:
            requirement, requested_extras = queue.popleft()
            name = canonicalize_name(requirement.name)
            state = (name, tuple(sorted(requested_extras)))
            if state in visited:
                continue
            visited.add(state)
            distribution = installed.get(name)
            if distribution is None:
                errors.append(
                    f"{group} dependency {requirement.name!r} is not installed"
                )
                continue

            record = records.setdefault(
                name,
                {
                    "distribution": distribution,
                    "groups": set(),
                },
            )
            record["groups"].add(group)
            marker_extras = requested_extras | {""}
            for dependency_text in distribution.requires or []:
                try:
                    dependency = Requirement(dependency_text)
                except InvalidRequirement as exc:
                    errors.append(
                        f"Invalid dependency metadata for "
                        f"{distribution.metadata.get('Name')}: {dependency_text!r}: {exc}"
                    )
                    continue
                if _marker_matches(dependency, marker_extras):
                    queue.append((dependency, set(dependency.extras)))

    return records, errors


def _metadata_licence(distribution: importlib.metadata.Distribution) -> str:
    metadata = distribution.metadata
    for field in ("License-Expression", "License"):
        value = (metadata.get(field) or "").strip()
        if value.lower() not in UNKNOWN_VALUES:
            return value
    classifiers = sorted(
        classifier.split("::", maxsplit=1)[-1].strip()
        for classifier in metadata.get_all("Classifier", [])
        if classifier.lower().startswith("license ::")
    )
    if classifiers:
        return "; ".join(classifiers)
    override = LICENSE_OVERRIDES.get(
        canonicalize_name(metadata.get("Name", ""))
    )
    return override["license"] if override else "UNKNOWN"


def _homepage(distribution: importlib.metadata.Distribution) -> str:
    metadata = distribution.metadata
    if metadata.get("Home-page"):
        return metadata.get("Home-page", "").strip()
    urls = metadata.get_all("Project-URL", [])
    for preferred in ("homepage", "home", "repository", "source"):
        for entry in urls:
            label, separator, url = entry.partition(",")
            if separator and label.strip().lower() == preferred:
                return url.strip()
    for entry in urls:
        _, separator, url = entry.partition(",")
        if separator:
            return url.strip()
    return ""


def _display(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _review_flags(records: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    flags = []
    for name, record in sorted(records.items()):
        licence = _metadata_licence(record["distribution"])
        categories = []
        if COPYLEFT_PATTERN.search(licence):
            categories.append("copyleft")
        if NONCOMMERCIAL_PATTERN.search(licence):
            categories.append("non-commercial or restricted")
        if categories:
            flags.append(
                (
                    record["distribution"].metadata.get("Name", name),
                    licence,
                    ", ".join(categories),
                )
            )
    return flags


def render_generated_section(
    records: dict[str, dict[str, Any]],
    errors: list[str],
) -> str:
    rows = []
    unknown = []
    for name, record in sorted(records.items()):
        distribution = record["distribution"]
        licence = _metadata_licence(distribution)
        if licence == "UNKNOWN":
            unknown.append(distribution.metadata.get("Name", name))
        rows.append(
            "| "
            + " | ".join(
                (
                    f"`{_display(distribution.metadata.get('Name', name))}`",
                    _display(distribution.version),
                    _display(licence),
                    _display(_homepage(distribution)) or "—",
                    _display(", ".join(sorted(record["groups"]))),
                )
            )
            + " |"
        )

    flags = _review_flags(records)
    lines = [
        BEGIN_MARKER,
        "## Installed runtime and optional dependency distributions",
        "",
        "Generated from `pyproject.toml` and installed distribution metadata. "
        "Transitive requirements are included.",
        "",
        "Requirement markers use a Python 3.11/Linux target. Versions and metadata "
        "reflect this installed environment.",
        "",
        "| Name | Version | Licence | Homepage | Pulled in by |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "### Licence review flags",
        "",
    ]
    if flags:
        lines.extend(
            f"- `{name}` — `{licence}` ({category})"
            for name, licence, category in flags
        )
    else:
        lines.append("No copyleft or non-commercial/restricted licences detected.")

    if LICENSE_OVERRIDES:
        lines.extend(["", "### Manual licence overrides", ""])
        for name, override in sorted(LICENSE_OVERRIDES.items()):
            lines.append(
                f"- `{name}` — `{override['license']}`; source: "
                f"`{_display(override['source'])}`"
            )
    else:
        lines.extend(["", "No manual licence overrides were needed."])

    if errors:
        lines.extend(["", "### Resolution errors", ""])
        lines.extend(f"- {_display(error)}" for error in errors)
    if unknown:
        lines.extend(["", "### Unknown licences", ""])
        lines.extend(f"- `{_display(name)}`" for name in unknown)
    lines.append(END_MARKER)
    return "\n".join(lines)


def update_document(document: str, generated: str) -> str:
    has_begin = BEGIN_MARKER in document
    has_end = END_MARKER in document
    if has_begin != has_end:
        raise ValueError("generated licence markers are incomplete")
    if has_begin:
        start = document.index(BEGIN_MARKER)
        end = document.index(END_MARKER, start) + len(END_MARKER)
        suffix = document[end:].strip()
        return (
            document[:start].rstrip()
            + "\n\n"
            + generated
            + (f"\n\n{suffix}" if suffix else "\n")
        )
    return document.rstrip() + "\n\n" + generated + "\n"


def _document_rows(document: str) -> dict[str, str]:
    if BEGIN_MARKER not in document or END_MARKER not in document:
        return {}
    start = document.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end = document.index(END_MARKER, start)
    rows = {}
    for line in document[start:end].splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] != "Name":
            rows[canonicalize_name(cells[0].strip("`"))] = cells[2]
    return rows


def check_document(
    document: str,
    records: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[str]:
    rows = _document_rows(document)
    failures = list(errors)
    if not rows:
        failures.append("generated dependency table is missing from the document")
    for name, record in sorted(records.items()):
        distribution = record["distribution"]
        display_name = distribution.metadata.get("Name", name)
        licence = _metadata_licence(distribution)
        if licence.upper() == "UNKNOWN" or not licence.strip():
            failures.append(f"{display_name} has an empty or UNKNOWN licence")
        documented = rows.get(name)
        if documented is None:
            failures.append(f"{display_name} is missing from the generated table")
        elif documented.upper() == "UNKNOWN" or not documented.strip():
            failures.append(f"{display_name} has an empty or UNKNOWN documented licence")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the committed generated section without rewriting the document",
    )
    parser.add_argument("--doc", type=Path, default=LICENSE_DOCUMENT)
    args = parser.parse_args(argv)

    try:
        document = args.doc.read_text(encoding="utf-8")
        records, errors = resolve_dependencies()
        generated = render_generated_section(records, errors)
        if args.check:
            failures = check_document(document, records, errors)
            if failures:
                print("Licence report check failed:")
                for failure in failures:
                    print(f"- {failure}")
                return 1
            print(f"Licence report check passed for {len(records)} distributions.")
            return 0
        args.doc.write_text(update_document(document, generated), encoding="utf-8")
    except (OSError, ValueError, InvalidRequirement, tomllib.TOMLDecodeError) as exc:
        print(f"Licence report failed: {exc}")
        return 1

    unknown = [
        record["distribution"].metadata.get("Name", name)
        for name, record in records.items()
        if _metadata_licence(record["distribution"]).upper() == "UNKNOWN"
    ]
    print(f"Generated licence table for {len(records)} distributions in {args.doc}.")
    if errors:
        print(f"Dependency resolution reported {len(errors)} error(s).")
    if unknown:
        print("Unknown licences require manual resolution: " + ", ".join(sorted(unknown)))
    return 1 if errors or unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())
