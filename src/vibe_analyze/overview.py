import os

from .util import human_size


def _dir_stats(root: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        files = 0
        size = 0
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                st = os.stat(full)
                size += int(st.st_size)
                files += 1
            except Exception:
                continue
        stats[dirpath] = (files, size)
    return stats


def build_compact_tree(root: str, depth: int = 4, max_lines: int = 2000) -> str:
    stats = _dir_stats(root)
    root = os.path.abspath(root)
    lines: list[str] = []

    def helper(path: str, level: int):
        if level > depth:
            return
        files, size = stats.get(path, (0, 0))
        rel = os.path.relpath(path, root)
        rel = "." if rel == "." else rel.replace("\\", "/")
        lines.append(f"{rel}/ (files={files}, size={human_size(size)})")
        if len(lines) >= max_lines:
            return
        try:
            entries = [os.path.join(path, d) for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
        except Exception:
            entries = []
        for d in sorted(entries):
            if len(lines) >= max_lines:
                break
            helper(d, level + 1)

    helper(root, 1)
    if len(lines) >= max_lines:
        lines.append("… (truncated)")
    return "\n".join(lines)
