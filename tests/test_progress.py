from __future__ import annotations

import hydrohex.progress as progress


def test_dependency_free_progress_fallback(monkeypatch, capsys):
    monkeypatch.setattr(progress, "_tqdm", lambda: None)
    with progress.progress_bar(total=2, desc="Test stage", enabled=True) as bar:
        bar.update(1)
        bar.update(1)
    err = capsys.readouterr().err
    assert "Test stage" in err
    assert "100.0%" in err


def test_progress_disabled_is_silent(monkeypatch, capsys):
    monkeypatch.setattr(progress, "_tqdm", lambda: None)
    with progress.progress_bar(total=1, desc="Hidden", enabled=False) as bar:
        bar.update(1)
    assert capsys.readouterr().err == ""
