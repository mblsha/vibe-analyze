import os
import subprocess
from typing import Optional

from .util import DEFAULT_EXCLUDES, is_path_excluded, which_fd


def _fd_cmd(root: str, excludes: list[str]) -> list[str]:
    exe = which_fd()
    if not exe:
        return []
    args = [exe, "--hidden", "--ignore-vcs", "--type", "f", ".", root]
    # fd does excludes via --exclude patterns; we map dir endings and globs
    for pat in excludes:
        args.extend(["--exclude", pat])
    try:
        out = subprocess.check_output(args, text=True)
        paths = [p.strip() for p in out.splitlines() if p.strip()]
        return paths
    except Exception:
        return []


def _walk_fallback(root: str, excludes: list[str]) -> list[str]:
    root = os.path.abspath(root)
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # apply directory excludes in-place to prune
        pruned = []
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            rel = os.path.relpath(full, root)
            rel = rel.replace("\\", "/") + "/"
            if is_path_excluded(rel, excludes):
                continue
            pruned.append(d)
        dirnames[:] = pruned
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            rel_unix = rel.replace("\\", "/")
            if not is_path_excluded(rel_unix, excludes):
                out.append(full)
    return out


def discover_files(root: str, excludes: Optional[list[str]] = None) -> list[str]:
    if excludes is None:
        excludes = DEFAULT_EXCLUDES
    # Try fd first
    paths = _fd_cmd(root, excludes)
    if paths:
        return sorted(paths)
    return sorted(_walk_fallback(root, excludes))
