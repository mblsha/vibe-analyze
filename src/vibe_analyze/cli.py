"""CLI orchestration for vibe-analyze."""
# ruff: noqa: PLR0915
# isort: skip_file

import argparse
import concurrent.futures
import os
import pathlib
import sys
import tempfile

from fnmatch import fnmatch
from typing import Optional

from plumbum import local

from .discover import discover_files
from .llm import GeminiClient
from .overview import build_compact_tree
from .util import (
    eprint,
    list_readme_files,
    read_text_safe,
    DEFAULT_EXCLUDES,
    is_secret_blocklisted,
    FileInfo,
    redact_high_entropy,
    read_yaml_if_exists,
    human_size,
    collect_import_refs,
    best_effort_resolve_refs_to_paths,
)
from .tokenize import count_tokens
from .selector import stage1_select, stage2_select


ANALYSIS_SYSTEM = (
    "You are a senior staff-level engineer. \n"
    "Use the provided files (CXML blocks) and answer the user's request precisely and concisely. \n"
    "If the answer may depend on omitted code, call it out explicitly."
)


def load_cfg(root: str) -> dict:
    cfg = {
        "headroom": 0.15,
        "file_cap_bytes": 524288,
        "selector_model": "flash-1m",
        "analysis_model": "pro-1m",
        "max_stage1": 2000,
        "max_stage2": 20000,
        "allow_secrets": False,
        "regex_imports": "default-set",
        "excludes": DEFAULT_EXCLUDES.copy(),
    }
    y = read_yaml_if_exists(os.path.join(root, ".vibe.yml"))
    for k, v in y.items() if isinstance(y, dict) else []:
        if k in cfg:
            cfg[k] = v
    return cfg


def assemble_overview(root: str, tree_depth: int = 4) -> str:
    readmes = list_readme_files(root)
    parts: list[str] = []
    if readmes:
        parts.append(
            "READMEs:\n" + "\n".join([f"## {os.path.relpath(p, root)}\n" + read_text_safe(p, 200_000) for p in readmes])
        )
    tree = build_compact_tree(root, depth=tree_depth)
    parts.append("COMPACT DIRECTORY TREE (counts, sizes):\n" + tree)
    return "\n\n".join(parts)


def stat_and_filter(
    files: list[str], root: str, file_cap: int, allow_secrets: bool
) -> tuple[dict[str, FileInfo], list[str]]:
    infos: dict[str, FileInfo] = {}
    blocked: list[str] = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            st = os.stat(path)
            size = int(st.st_size)
        except Exception:
            continue
        info = FileInfo(path=rel, size=size)
        if size > file_cap:
            info.oversized = True
            eprint(f"SKIPPED (too large): {rel} [size={human_size(size)}, cap={human_size(file_cap)}]")
            continue
        if not allow_secrets and is_secret_blocklisted(rel):
            info.blocked_secret = True
            blocked.append(rel)
            eprint(f"BLOCKED (secret): {rel}")
            continue
        infos[rel] = info
    return infos, blocked


def load_and_redact(infos: dict[str, FileInfo], root: str) -> None:
    # Parallel read and redact
    def worker(rel: str):
        p = os.path.join(root, rel)
        text = read_text_safe(p)
        redacted, count = redact_high_entropy(text)
        if count > 0:
            eprint(f"REDACTED token(s): {rel} ({count} matches)")
        return rel, redacted, count

    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        futures = [ex.submit(worker, rel) for rel in infos]
        for fut in concurrent.futures.as_completed(futures):
            rel, text, count = fut.result()
            infos[rel].content = text
            infos[rel].redactions = count


def fits_early(request: str, overview: str, infos: dict[str, FileInfo], headroom: float) -> bool:
    texts = [ANALYSIS_SYSTEM, request, overview]
    for fi in infos.values():
        if fi.content is not None:
            texts.append(fi.content)
    tokens = count_tokens(texts)
    return tokens <= int((1.0 - headroom) * 1_000_000)


def cxml_bundle(
    files: list[tuple[int, str]], info_map: dict[str, FileInfo], request: str, overview: str, root: str
) -> tuple[str, str]:
    # Build a temporary directory with redacted file contents, then invoke files-to-prompt --cxml via plumbum

    tmpdir_obj = tempfile.TemporaryDirectory(prefix="vibe_f2p_")
    tmpdir = tmpdir_obj.name
    # Write files preserving relative paths
    for _, rel in files:
        fi = info_map.get(rel)
        if not fi or fi.content is None:
            continue
        dst = pathlib.Path(tmpdir, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(fi.content, encoding="utf-8")
    # Run files-to-prompt
    try:
        f2p = local["files-to-prompt"]
        cxml_body = f2p["--cxml", tmpdir]().strip()
    except Exception as ex:
        # Fallback to internal builder if files-to-prompt unavailable
        eprint(f"files-to-prompt failed: {ex}; falling back to internal CXML")
        parts: list[str] = ["<files>"]
        for _, rel in files:
            fi = info_map.get(rel)
            if not fi or fi.content is None:
                continue
            parts.append(f'  <file path="{rel}">')
            parts.append("  <![CDATA[")
            parts.append(fi.content)
            parts.append("  ]]>\n  </file>")
        parts.append("</files>")
        cxml_body = "\n".join(parts)
    finally:
        tmpdir_obj.cleanup()
    # Prepend overview and request
    cxml = f"{request}\n\nPROJECT OVERVIEW:\n{overview}\n\n" + cxml_body
    return ANALYSIS_SYSTEM, cxml


def analyze(system: str, user_cxml: str, model: str, timeout_s: int) -> str:
    client = GeminiClient(model=model, temperature=0.2, timeout_s=timeout_s)
    if not client.ready():
        raise RuntimeError(client.error() or "Gemini not ready")
    return client.generate(system=system, user=user_cxml)


def budgeted_pack(
    prioritized: list[tuple[int, str]], info_map: dict[str, FileInfo], headroom: float, request: str, overview: str
) -> list[tuple[int, str]]:
    # prioritize shorter files within same priority
    grouped: dict[int, list[str]] = {}
    for pr, rel in prioritized:
        if rel in info_map and info_map[rel].content is not None:
            grouped.setdefault(pr, []).append(rel)
    out: list[tuple[int, str]] = []
    texts: list[str] = [ANALYSIS_SYSTEM, request, overview]
    for pr in sorted(grouped, reverse=True):
        rels = sorted(grouped[pr], key=lambda r: len(info_map[r].content or ""))
        for r in rels:
            # try adding in batches; count tokens
            trial = texts + [info_map[r].content or ""]
            if count_tokens(trial) <= int((1.0 - headroom) * 1_000_000):
                texts = trial
                out.append((pr, r))
            else:
                # can't fit; move on
                continue
    return out


def fallback_mode_b(
    seed_ranked: list[tuple[int, str]], root: str, info_map: dict[str, FileInfo]
) -> list[tuple[int, str]]:
    # Seed with top-K
    K = min(50, len(seed_ranked))
    seeds = [r for _, r in seed_ranked[:K] if r in info_map]
    all_paths = list(info_map.keys())
    dep_scores: dict[str, int] = {}
    for s in seeds:
        txt = info_map[s].content or ""
        refs = collect_import_refs(txt)
        paths = best_effort_resolve_refs_to_paths(refs, all_paths)
        base_pr = next((p for p, r in seed_ranked if r == s), 50)
        for p in paths:
            dep_scores[p] = max(dep_scores.get(p, 0), 1, base_pr - 5)
    # Merge seeds (keep original scores) and deps (inherited)
    merged: dict[str, int] = {r: p for p, r in seed_ranked}
    for p, sc in dep_scores.items():
        merged[p] = max(merged.get(p, 0), sc)
    ranked = sorted([(p, r) for r, p in merged.items()], key=lambda x: (-x[0], x[1]))
    return ranked


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="vibe-analyze", description="High-recall codebase answering (CLI)")
    ap.add_argument("--request", required=True)
    ap.add_argument("--headroom", type=float, default=0.15)
    ap.add_argument("--file-cap-bytes", type=int, default=524288)
    ap.add_argument("--selector-model", default="flash-1m")
    ap.add_argument("--analysis-model", default="pro-1m")
    ap.add_argument("--max-stage1", type=int, default=2000)
    ap.add_argument("--max-stage2", type=int, default=20000)
    ap.add_argument("--mode", choices=["C", "B"], default="C")
    ap.add_argument("--allow-secrets", action="store_true", default=False)
    ap.add_argument("--regex-imports", default="default-set")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--timeout-s", type=int, default=120)
    args = ap.parse_args(argv)

    root = os.path.abspath(args.cwd)
    if not os.path.isdir(root):
        eprint(f"Invalid --cwd: {root}")
        return 2

    # Load config overrides
    cfg = load_cfg(root)
    headroom = args.headroom if args.headroom is not None else cfg["headroom"]
    file_cap = args.file_cap_bytes if args.file_cap_bytes is not None else cfg["file_cap_bytes"]
    selector_model = args.selector_model or cfg["selector_model"]
    analysis_model = args.analysis_model or cfg["analysis_model"]
    max_stage1 = args.max_stage1 or cfg["max_stage1"]
    max_stage2 = args.max_stage2 or cfg["max_stage2"]
    allow_secrets = args.allow_secrets or cfg["allow_secrets"]
    excludes = cfg["excludes"]

    # 1) Discover
    files = discover_files(root, excludes=excludes)

    # 2) Overview
    overview = assemble_overview(root)

    # 3) Early filters
    info_map, blocked = stat_and_filter(files, root, file_cap, allow_secrets)
    load_and_redact(info_map, root)

    # Early-fit check with headroom
    if fits_early(args.request, overview, info_map, headroom):
        # everything fits; analyze directly
        system, cxml = cxml_bundle([(100, r) for r in info_map], info_map, args.request, overview, root)
        try:
            answer = analyze(system, cxml, analysis_model, args.timeout_s)
        except Exception as e:
            eprint(f"Analysis error: {e}")
            return 1
        sys.stdout.write((answer or "").strip() + "\n")
        return 0

    # 4) Hierarchical selection
    st1 = stage1_select(args.request, overview, selector_model, args.timeout_s)
    # Expand stage1 globs/dirs via discovery again; pragmatic: just filter known files by matching prefix/glob
    expanded: list[str] = []

    all_rels = [os.path.relpath(p, root).replace("\\", "/") for p in files]
    for _prio, pat in st1[:max_stage1]:
        pat_norm = pat.replace("\\", "/")
        for rel in all_rels:
            if rel.startswith(pat_norm.rstrip("*/")) or fnmatch(rel, pat_norm):
                expanded.append(rel)
        if len(expanded) >= max_stage1:
            break
    if not expanded:
        # fallback: take all
        expanded = all_rels[:max_stage2]

    # Stage 2 rank
    st2 = stage2_select(
        args.request, overview, expanded[:max_stage2], selector_model, mode="C", timeout_s=args.timeout_s
    )
    prioritized = st2 if st2 else [(50, rel) for rel in expanded[:max_stage2]]

    # 5) Assembly & budgeting (Mode C)
    packed = budgeted_pack(prioritized, info_map, headroom, args.request, overview)

    # If we had to trim anything under Mode C, fallback to Mode B (transitive scope)
    if len(packed) < len(prioritized):
        eprint("FALLBACK: switched to transitive scope (B) due to token budget")
        ranked_b = fallback_mode_b(prioritized, root, info_map)
        packed = budgeted_pack(ranked_b, info_map, headroom, args.request, overview)

    # 6) Final send
    system, cxml = cxml_bundle(packed, info_map, args.request, overview, root)
    try:
        answer = analyze(system, cxml, analysis_model, args.timeout_s)
    except Exception as e:
        eprint(f"Analysis error: {e}")
        return 1
    sys.stdout.write((answer or "").strip() + "\n")
    # Diagnostics: trims are implicitly anything not included; emit verbose list
    included = {r for _, r in packed}
    for pr, rel in prioritized:
        if rel not in included and rel in info_map:
            eprint(f"TRIMMED (low priority): {rel} [prio={pr}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
