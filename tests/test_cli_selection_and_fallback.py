"""Selection path and Mode B fallback tests."""
# ruff: noqa: PLR0913
# isort: skip_file

from pathlib import Path
from vibe_analyze import cli
from vibe_analyze import selector


def write(p: Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_selection_trim_and_mode_b_fallback(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    write(repo / "README.md", "# Test\nSelection path")
    # Create many files so that prioritized list is large
    files = []
    for i in range(100):
        p = repo / "pkg" / f"f{i}.py"
        # Each ~4000 chars (~1000 tokens rough) to easily exceed tight budget
        write(p, ("A" * 4000) + f"\n# file {i}\n")
        files.append(str(p))

    # Stage 1 returns the dir glob
    def fake_stage1(request, overview, model, timeout_s):
        return [(100, "pkg/")]

    # Stage 2 ranks files; ensure deterministic order and varying priorities
    def fake_stage2(request, overview, candidates, model, mode, timeout_s):
        ranked = []
        for idx, c in enumerate(sorted(candidates)):
            pr = 100 - (idx % 50)  # cycle priorities to have some lows to trim
            ranked.append((pr, c))
        return ranked

    monkeypatch.setattr(selector, "stage1_select", fake_stage1)
    monkeypatch.setattr(selector, "stage2_select", fake_stage2)

    captured = {"cxml": None}

    def fake_analyze(system, user_cxml, model, timeout_s):
        captured["cxml"] = user_cxml
        return "Answer"

    monkeypatch.setattr(cli, "analyze", fake_analyze)

    # Use extreme headroom to force small budget and trimming
    rc = cli.main(
        [
            "--request",
            "Explain behavior",
            "--cwd",
            str(repo),
            "--headroom",
            "0.99",
        ]
    )
    assert rc == 0
    out = capsys.readouterr()
    # Stdout is the answer
    assert out.out.strip() == "Answer"
    # Expect fallback notice and many TRIMMED lines
    assert "FALLBACK: switched to transitive scope (B) due to token budget" in out.err
    assert "TRIMMED (low priority):" in out.err
    # Ensure only a small number of files ended up in the CXML bundle due to budget
    cxml = captured["cxml"]
    assert cxml is not None
    MAX_BUNDLE_DOCS = 20
    assert cxml.count("<document index=") < MAX_BUNDLE_DOCS
