"""Utility functions for discovery, redaction, and helpers."""
# isort: skip_file

import fnmatch
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from typing import Optional
import yaml  # type: ignore

SECRET_BLOCKLIST_GLOBS = [
    ".env*",
    "*.pem",
    "id_rsa*",
    "secrets.*",
    "*.key",
    "*.p12",
    "*.keystore",
]

DEFAULT_EXCLUDES = [
    ".git/",
    ".svn/",
    ".hg/",
    "node_modules/",
    "dist/",
    "build/",
    ".next/",
    ".cache/",
    "coverage/",
    "target/",
    "out/",
    "__pycache__/",
    ".venv/",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.mp4",
    "*.mov",
    "*.ogg",
    "*.wav",
    "*.webm",
    "*.ico",
    "*.woff*",
    "*.min.*",
]

IMPORT_REGEXES = [
    re.compile(r"\b(import|require)\s*\(|\bfrom\s+['\"][^'\"]+['\"]"),  # JS/TS
    re.compile(r"^\s*(from\s+[.\w]+\s+import|import\s+[.\w]+)", re.M),  # Python
    re.compile(r"^\s*import\s*\(|^\s*import\s+\"[^\"]+\"", re.M),  # Go
    re.compile(r"^\s*use\s+[a-zA-Z0-9_:]+", re.M),  # Rust
    re.compile(r"^\s*#\s*include\s+[<\"].+[>\"]", re.M),  # C/C++
    re.compile(r"^\s*import\s+[a-zA-Z0-9_.]+;", re.M),  # Java/Kotlin
    re.compile(r"(?i)\binclude(s)?\s*:\s*"),  # YAML/TOML
]


def eprint(msg: str) -> None:
    sys.stderr.write(msg.rstrip("\n") + "\n")
    sys.stderr.flush()


def is_path_excluded(path: str, excludes: list[str]) -> bool:
    p = path.replace("\\", "/")
    for pat in excludes:
        if pat.endswith("/"):
            # directory pattern
            if p.startswith(pat) or ("/" + pat) in p:
                if pat in ("node_modules/", ".git/") and (p == pat[:-1] or p.startswith(pat)):
                    return True
                if pat != "node_modules/" and (p.startswith(pat)):
                    return True
        elif fnmatch.fnmatch(p, pat):
            return True
    return False


def which_fd() -> Optional[str]:
    return shutil.which("fd") or shutil.which("fdfind")


_KIB = 1024


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    x = float(n)
    while x >= _KIB and i < len(units) - 1:
        x /= float(_KIB)
        i += 1
    if i == 0:
        return f"{int(x)}B"
    return f"{x:.1f}{units[i]}"


def read_text_safe(path: str, max_bytes: Optional[int] = None) -> str:
    with open(path, "rb") as f:
        data = f.read(max_bytes if max_bytes is not None else None)
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode("latin-1", errors="replace")


def list_readme_files(root: str) -> list[str]:
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.upper().startswith("README"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    ent = 0.0
    for c in freq.values():
        p = c / n
        ent -= p * math.log2(p)
    return ent


def find_high_entropy_tokens(s: str, min_len: int = 20, entropy_threshold: float = 3.7) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    token = []
    start = None

    def flush():
        nonlocal token, start
        if start is not None and len(token) >= min_len:
            t = "".join(token)
            if shannon_entropy(t) >= entropy_threshold:
                spans.append((start, start + len(token)))
        token = []
        start = None

    for i, ch in enumerate(s):
        if ch.isalnum() or ch in "_-.+/=":
            if start is None:
                start = i
            token.append(ch)
        else:
            flush()
    flush()
    return spans


def redact_high_entropy(s: str) -> tuple[str, int]:
    spans = find_high_entropy_tokens(s)
    if not spans:
        return s, 0
    # Replace spans with ‹REDACTED› preserving line numbers (not columns)
    out = []
    last = 0
    count = 0
    for a, b in spans:
        out.append(s[last:a])
        out.append("‹REDACTED›")
        last = b
        count += 1
    out.append(s[last:])
    return "".join(out), count


def read_yaml_if_exists(path: str) -> dict:
    # PyYAML is an explicit dependency; import already resolved at module load
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


@dataclass
class FileInfo:
    path: str
    size: int
    blocked_secret: bool = False
    oversized: bool = False
    redactions: int = 0
    content: Optional[str] = None


def is_secret_blocklisted(path: str) -> bool:
    p = path.replace("\\", "/")
    for pat in SECRET_BLOCKLIST_GLOBS:
        if fnmatch.fnmatch(p, pat):
            return True
    # Common credential stores
    lowers = p.lower()
    return any(k in lowers for k in ["aws/credentials", "gcp/", "gcloud/"])


def parse_ranked_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line in text.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        if "\t" in line_s:
            prio_str, rest = line_s.split("\t", 1)
        elif " " in line_s:
            prio_str, rest = line_s.split(" ", 1)
        else:
            continue
        try:
            pr = int(prio_str)
        except ValueError:
            continue
        pr = max(1, min(100, pr))
        out.append((pr, rest.strip()))
    # High priority first
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


def collect_import_refs(text: str) -> set[str]:
    refs: set[str] = set()
    for rx in IMPORT_REGEXES:
        for m in rx.finditer(text):
            s = m.group(0)
            # Extract quoted path if present
            q = re.search(r"['\"]([^'\"]+)['\"]", s)
            if q:
                refs.add(q.group(1))
            else:
                # fallback to token-ish words
                words = re.findall(r"[A-Za-z0-9_./-]+", s)
                for w in words:
                    if len(w) >= MIN_WORD_LEN and not w.isdigit():
                        refs.add(w)
    return refs


def best_effort_resolve_refs_to_paths(refs: set[str], all_paths: list[str]) -> set[str]:
    # Very rough heuristic: match by suffix filename or by path parts
    lower_all = [(p, p.lower()) for p in all_paths]
    chosen: set[str] = set()
    for r in refs:
        base = os.path.basename(r).lower()
        if not base:
            continue
        for p, pl in lower_all:
            if pl.endswith("/" + base) or pl.endswith(base):
                chosen.add(p)
    return chosen
MIN_WORD_LEN = 3
