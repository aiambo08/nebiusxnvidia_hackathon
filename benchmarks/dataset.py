"""F4 session index: which recordings exist, how they are split, and their hashes.

`benchmarks/manifests/sessions.yaml` is committed; the clips it describes stay local in
`benchmarks/data/` (git-ignored). Split is by session (`dev` or `test`), never by frame.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "benchmarks" / "manifests" / "sessions.yaml"
DATA = ROOT / "benchmarks" / "data"
SESSION_RE = re.compile(r"^s\d{3}$")
SPLITS = ("dev", "test")
PRIVATE_RE = re.compile(r"[:\\/@]|\d+\.\d+\.\d+\.\d+")


@dataclass
class Session:
    id: str
    split: str
    sha256: str
    frames: int
    fps: float
    resolution: list[int]
    seconds: float
    conditions: str = ""
    label: str = "REAL HARDWARE"
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def clip(self) -> Path:
        return DATA / f"{self.id}_clean.avi"


def check_session_id(sid: str) -> str:
    if not SESSION_RE.match(sid):
        raise ValueError(f"session id must look like s001, got {sid!r}")
    return sid


def check_public(text: str, what: str = "metadata") -> str:
    if PRIVATE_RE.search(text):
        raise ValueError(f"{what} must not contain a URL, an IP address or a path")
    return text


def development(manifests: Path | None = None) -> tuple[set[str], set[str]]:
    """Session ids and clip sha256 used while building the detectors (top-level F1/F3 manifests)."""
    ids, hashes = set(), set()
    for p in (manifests or INDEX.parent).glob("*.yaml"):
        if p.name == INDEX.name:
            continue
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if m.get("session"):
            ids.add(str(m["session"]))
        sha = (m.get("source") or {}).get("sha256")
        if sha and sha != "TBD":
            hashes.add(sha)
    return ids, hashes


def frame_count(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(index: Path | None = None) -> list[Session]:
    index = index or INDEX
    if not index.exists():
        return []
    raw = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
    out = [Session(**s) for s in raw.get("sessions", [])]
    validate(out)
    return out


def validate(sessions: list[Session]) -> None:
    seen: set[str] = set()
    for s in sessions:
        check_session_id(s.id)
        if s.id in seen:
            raise ValueError(f"duplicate session {s.id}")
        seen.add(s.id)
        if s.split not in SPLITS:
            raise ValueError(f"session {s.id}: split must be one of {SPLITS}, got {s.split!r}")
        texts = [s.conditions, s.notes, *(str(v) for v in s.extra.values()), *map(str, s.extra)]
        for t in texts:
            check_public(t, f"session {s.id} metadata")


def save(sessions: list[Session], index: Path | None = None) -> None:
    index = index or INDEX
    validate(sessions)
    index.parent.mkdir(parents=True, exist_ok=True)
    body = {"sessions": [asdict(s) for s in sorted(sessions, key=lambda s: s.id)]}
    index.write_text("# F4 session index (clips stay local in benchmarks/data/, never committed)\n"
                     + yaml.safe_dump(body, sort_keys=False), encoding="utf-8", newline="\n")


def add(session: Session, index: Path | None = None) -> None:
    index = index or INDEX
    sessions = load(index)
    if any(s.id == session.id for s in sessions):
        raise ValueError(f"session {session.id} already in {index.name}")
    save([*sessions, session], index)


def verify(sessions: list[Session], data: Path | None = None) -> list[str]:
    """Problems found (missing clip, hash or frame-count mismatch); empty when intact."""
    data = data or DATA
    problems = []
    for s in sessions:
        clip = data / f"{s.id}_clean.avi"
        if not clip.exists():
            problems.append(f"{s.id}: clip missing")
        elif sha256(clip) != s.sha256:
            problems.append(f"{s.id}: sha256 mismatch (dataset changed)")
        elif (n := frame_count(clip)) != s.frames:
            problems.append(f"{s.id}: decoder reports {n} frames, index says {s.frames}")
    return problems
