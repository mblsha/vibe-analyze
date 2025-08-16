from pathlib import Path

import vibe_analyze.cli as cli


def test_files_to_prompt_cxml_output(monkeypatch, capsys):
    # Use the committed fixture project
    repo = Path("tests/fixtures/sample_project").resolve()

    captured = {"cxml": None}

    def fake_analyze(system, user_cxml, model, timeout_s):
        captured["cxml"] = user_cxml
        return "OK"

    monkeypatch.setattr(cli, "analyze", fake_analyze)

    rc = cli.main([
        "--request",
        "Summarize the sample project",
        "--cwd",
        str(repo),
    ])
    assert rc == 0
    out = capsys.readouterr()
    assert out.out.strip() == "OK"

    cxml = captured["cxml"]
    assert cxml is not None
    # Ensure we used files-to-prompt --cxml style output
    assert "<documents>" in cxml
    assert "<document index=" in cxml
    # Should include our fixture files
    assert "src/app.py" in cxml
    assert "Sample Project" in cxml or "This is a tiny sample project" in cxml

