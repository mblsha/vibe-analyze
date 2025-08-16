import os
from pathlib import Path
import io

import vibe_analyze.cli as cli
import vibe_analyze.selector as selector


def write(p: Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_early_fit_skips_selection_and_blocks_secrets(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    # README and small source file
    write(repo / "README.md", "# Sample Repo\nThis is a test.")
    write(repo / "src" / "app.py", "print('hello')\n")
    # Secret file is blocked
    write(repo / ".env", "SECRET=shhhh")
    # Oversized file should be skipped
    big = "x" * 1024 * 1024  # 1MB
    write(repo / "dist" / "bundle.js", big)

    # Make sure selection functions are NOT called under early fit
    called_stage1 = {"called": False}

    def forbid_stage1(*a, **k):
        called_stage1["called"] = True
        raise AssertionError("stage1_select should not be called under early-fit path")

    monkeypatch.setattr(selector, "stage1_select", forbid_stage1)
    monkeypatch.setattr(selector, "stage2_select", forbid_stage1)

    captured_cxml = {"text": None}

    def fake_analyze(system: str, user_cxml: str, model: str, timeout_s: int) -> str:
        captured_cxml["text"] = user_cxml
        return "OK"

    monkeypatch.setattr(cli, "analyze", fake_analyze)

    rc = cli.main([
        "--request", "What does app do?",
        "--cwd", str(repo),
        "--file-cap-bytes", "524288",  # 512KB cap so big file is skipped
    ])
    assert rc == 0
    out = capsys.readouterr()
    # stdout has the answer only
    assert out.out.strip() == "OK"
    # stderr contains BLOCKED and SKIPPED notices
    assert "BLOCKED (secret): .env" in out.err
    assert "SKIPPED (too large): dist/bundle.js" in out.err
    # Ensure early-fit path included file contents and redaction did not break structure
    assert captured_cxml["text"] is not None
    assert "<files>" in captured_cxml["text"]
    assert "src/app.py" in captured_cxml["text"]

