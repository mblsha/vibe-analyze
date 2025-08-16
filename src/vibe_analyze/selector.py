from typing import List, Tuple
from .llm import GeminiClient
from .util import parse_ranked_lines


STAGE1_SYSTEM = (
    "You are a codebase file selector optimizing for RECALL. \n"
    "Goal: choose directories and globs that likely contain information to answer the user’s request.\n"
    "Output ONLY lines in the format: \"<priority>\t<glob_or_dir>\" where priority is 1–100 (100 = must-include).\n"
    "Avoid binaries/build artifacts. Prefer source, configs, infra, tests, and relevant docs."
)

STAGE2_SYSTEM_C = (
    "You are a file selector optimizing for RECALL under Mode=C (pragmatic, answer-centric).\n"
    "Return ONLY lines: \"<priority>\t<path>\" where priority is 1–100 (100 = must-include).\n"
    "Prioritize files most useful to answer the question; include tests/docs/configs if helpful."
)

STAGE2_SYSTEM_B = (
    "You are a file selector optimizing for RECALL under Mode=B (transitive scope).\n"
    "Include direct files and transitive dependencies (imports/includes).\n"
    "Rank by criticality to behavior.\n"
    "Return ONLY lines: \"<priority>\t<path>\" where priority is 1–100."
)


def stage1_select(request: str, overview: str, model: str, timeout_s: int) -> List[Tuple[int, str]]:
    client = GeminiClient(model=model, temperature=0.0, timeout_s=timeout_s)
    if not client.ready():
        return []
    user = (
        f"{request}\n----\nPROJECT OVERVIEW (READMEs + tree):\n{overview}\n\n"
        "Return the smallest set of dirs/globs that achieves high recall.\n"
        "If in doubt, include; we will trim later by priority."
    )
    text = client.generate(system=STAGE1_SYSTEM, user=user)
    return parse_ranked_lines(text)


def stage2_select(request: str, overview: str, candidates: List[str], model: str, mode: str, timeout_s: int) -> List[Tuple[int, str]]:
    client = GeminiClient(model=model, temperature=0.0, timeout_s=timeout_s)
    if not client.ready():
        return []
    sys_msg = STAGE2_SYSTEM_C if mode == "C" else STAGE2_SYSTEM_B
    cand_list = "\n".join(candidates)
    user = (
        f"{request}\n----\nPROJECT OVERVIEW:\n{overview}\n----\nCANDIDATE FILES:\n{cand_list}\n\n"
        "Select and rank files. Be generous; we will budget-trim by priority later."
    )
    text = client.generate(system=sys_msg, user=user)
    return parse_ranked_lines(text)

