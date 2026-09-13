"""`jin build` / `jin run` の v2（Jin v2・jin_wasm）分岐。v1 の経路は `test_build_run.py`。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jin_cli.main import app
from jin_wasm.jinrec import dumps_jinrec
from typer.testing import CliRunner

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples-v2"
PROGRAMS = REPO_ROOT / "tests" / "fixtures" / "v2-programs"
FIB = EXAMPLES / "fib" / "fib.jin"
PADDLE = EXAMPLES / "paddle" / "paddle.jin"
PIPELINE = REPO_ROOT / "examples" / "pipeline" / "pipeline.jin"


def invoke(*args: str):
    return runner.invoke(app, [str(a) for a in args])


# ---------------------------------------------------------------- run


def test_run_prints_the_public_state_of_the_last_tick() -> None:
    result = invoke("run", FIB)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.strip()) == {"Fib.answer": 6765}
    assert "tick 0 で done" in result.stderr


def test_run_writes_trace_and_frames(tmp_path: Path) -> None:
    trace = tmp_path / "t.jsonl"
    frames = tmp_path / "f.jsonl"
    result = invoke("run", PADDLE, "--ticks", "30", "--trace", trace, "--frames", frames)
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert rows and list(rows[0]) == [
        "seq",
        "tick",
        "circle",
        "kind",
        "name",
        "pointer",
        "input",
        "output",
    ]
    assert [r["tick"] for r in rows if r["kind"] == "frame"] == list(range(30))
    frame_rows = [json.loads(line) for line in frames.read_text(encoding="utf-8").splitlines()]
    assert [f["tick"] for f in frame_rows] == list(range(30))
    assert frame_rows[0]["ops"][0] == ["clear", "#000"]
    assert oct(trace.stat().st_mode & 0o777) == "0o600"


def test_run_replays_a_recording(tmp_path: Path) -> None:
    rec = tmp_path / "rec.jinrec"
    rec.write_text(
        dumps_jinrec(
            {"file": "paddle.jin", "seed": 7, "fps": 60, "ticks": 200},
            [{"tick": 0, "kind": "key", "name": "ArrowRight", "down": True}],
        ),
        encoding="utf-8",
    )
    result = invoke("run", PADDLE, "--input", rec)
    assert result.exit_code == 0, result.output
    public = json.loads(result.stdout.strip())
    assert public["Play.score"] >= 1
    assert "200 tick" in result.stderr


def test_run_ticks_option_overrides_the_recording_header(tmp_path: Path) -> None:
    rec = tmp_path / "rec.jinrec"
    rec.write_text(dumps_jinrec({"ticks": 200}, []), encoding="utf-8")
    result = invoke("run", FIB, "--input", rec, "--ticks", "3")
    assert result.exit_code == 0, result.output
    assert "1 tick 走らせました" in result.stderr  # root が tick 0 で done


def test_run_rejects_a_broken_recording(tmp_path: Path) -> None:
    rec = tmp_path / "rec.jinrec"
    rec.write_text(
        '{"jinrec": 1}\n{"tick": 2, "kind": "key", "name": "A", "down": true}\n{"tick": 1, "kind": "key", "name": "A", "down": false}\n',
        encoding="utf-8",
    )
    result = invoke("run", FIB, "--input", rec)
    assert result.exit_code == 2
    assert "rec.jinrec:3" in result.stderr and "昇順" in result.stderr


def test_run_reports_a_runtime_error_and_exits_one(tmp_path: Path) -> None:
    trace = tmp_path / "t.jsonl"
    result = invoke("run", PROGRAMS / "runtime_error_index.jin", "--trace", trace)
    assert result.exit_code == 1
    assert "実行時エラー" in result.stderr and "添字" in result.stderr
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert any(r["kind"] == "error" for r in rows)


@pytest.mark.parametrize(
    "args",
    [
        ("run", FIB, "go"),
        ("run", FIB, "--model", "fake"),
        ("run", FIB, "--session", "s"),
    ],
)
def test_run_rejects_v1_arguments_on_a_v2_file(args) -> None:
    result = invoke(*args)
    assert result.exit_code == 2
    assert "version: 2" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("run", PIPELINE),
        ("run", PIPELINE, "go", "--ticks", "3"),
        ("run", PIPELINE, "go", "--debug"),
        ("build", PIPELINE, "--out", "x", "--debug"),
    ],
)
def test_v1_files_reject_v2_arguments(args, tmp_path: Path) -> None:
    args = [tmp_path / a if a == "x" else a for a in args]
    result = invoke(*args)
    assert result.exit_code == 2
    assert "version" in result.stderr


# ---------------------------------------------------------------- render（Phase 3）


@pytest.mark.parametrize("focus", [None, "Play", "Play/step", "Game"])
def test_render_accepts_v2(focus: str | None) -> None:
    """Phase 3: `jin render` は v2 を `jin_render.render` へ渡す（陣名 / 陣名/手順名）。"""
    args = ["render", PADDLE] + (["--focus", focus] if focus else [])
    result = invoke(*args)
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("<svg ")
    assert 'data-jin-kind="stage"' in result.stdout
    if focus == "Play/step":
        assert 'data-jin-kind="step-edge"' in result.stdout


@pytest.mark.parametrize("focus", ["Nope", "Play/nope", "Play/step/0"])
def test_render_rejects_an_unknown_v2_focus(focus: str) -> None:
    result = invoke("render", PADDLE, "--focus", focus)
    assert result.exit_code == 2
    assert "focus" in result.stderr


def test_render_overlays_a_v2_trace(tmp_path: Path) -> None:
    """`jin run --trace` が書いた行（seq 0 始まり）を `jin render --trace` が読めること。"""
    trace = tmp_path / "t.jsonl"
    assert invoke("run", PADDLE, "--ticks", "2", "--debug", "--trace", trace).exit_code == 0
    result = invoke("render", PADDLE, "--focus", "Play", "--trace", trace, "--upto", "0")
    assert result.exit_code == 0, result.stderr
    # `--upto 0` は `enter` 行（seq 0）だけを発火させる（v2 layout.md §6）。
    assert result.stdout.count('data-jin-fired="1"') >= 1
    assert 'data-jin-seq="0"' in result.stdout


# ---------------------------------------------------------------- build


def test_build_writes_the_bundle(tmp_path: Path, monkeypatch) -> None:
    from jin_wasm import bundle

    empty = tmp_path / "no-player"
    empty.mkdir()
    monkeypatch.setattr(bundle, "PLAYER_DIR", empty)
    out = tmp_path / "dist"
    result = invoke("build", FIB, "--out", out)
    assert result.exit_code == 0, result.output
    assert (out / "game.lua").read_text(encoding="utf-8").startswith("-- generated by jin")
    manifest = json.loads((out / "game.manifest.json").read_text(encoding="utf-8"))
    assert manifest["file"] == "fib.jin" and manifest["debug"] is False
    assert "sync_player.py" in result.stderr  # プレイヤーが同梱されていなければ 1 行
    assert sorted(p.name for p in out.iterdir()) == ["game.lua", "game.manifest.json"]


def test_build_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    assert invoke("build", FIB, "--out", out).exit_code == 0
    again = invoke("build", FIB, "--out", out)
    assert again.exit_code == 1 and "--force" in again.stderr
    forced = invoke("build", FIB, "--out", out, "--force", "--debug")
    assert forced.exit_code == 0, forced.output
    manifest = json.loads((out / "game.manifest.json").read_text(encoding="utf-8"))
    assert manifest["debug"] is True
    assert not list(out.glob(".*jin-tmp"))


def test_build_single_is_refused_without_the_synced_player(tmp_path: Path, monkeypatch) -> None:
    from jin_wasm import bundle

    empty = tmp_path / "no-player"
    empty.mkdir()
    monkeypatch.setattr(bundle, "PLAYER_DIR", empty)
    result = invoke("build", FIB, "--out", tmp_path / "dist", "--single")
    assert result.exit_code == 1 and "sync_player.py" in result.stderr
    plain = invoke("build", FIB, "--out", tmp_path / "dist")
    assert plain.exit_code == 0, plain.output
    assert "sync_player.py" in plain.stderr  # プレイヤー無しは stderr に 1 行
    assert sorted(p.name for p in (tmp_path / "dist").iterdir()) == [
        "game.lua",
        "game.manifest.json",
    ]


def test_build_writes_the_player_and_single_embeds_it(tmp_path: Path, monkeypatch) -> None:
    """同梱されたプレイヤー（ここでは偽物）が `<out>/` に並び、`--single` は index.html 1 本になる。"""
    from jin_wasm import bundle

    player = tmp_path / "player"
    player.mkdir()
    (player / "index.html").write_text(
        f"<html><body>{bundle.BUNDLE_MARKER}{bundle.PLAYER_SCRIPT_TAG}</body></html>",
        encoding="utf-8",
    )
    (player / "player.js").write_text("void 0;", encoding="utf-8")
    (player / "wasmoon.wasm").write_bytes(b"\x00asm")
    monkeypatch.setattr(bundle, "PLAYER_DIR", player)

    out = tmp_path / "dist"
    result = invoke("build", FIB, "--out", out)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert sorted(p.name for p in out.iterdir()) == [
        "game.lua",
        "game.manifest.json",
        "index.html",
        "player.js",
        "wasmoon.wasm",
    ]
    single = tmp_path / "single"
    result = invoke("build", FIB, "--out", single, "--single", "--debug")
    assert result.exit_code == 0, result.output
    assert [p.name for p in single.iterdir()] == ["index.html"]
    html = (single / "index.html").read_text(encoding="utf-8")
    assert "window.JIN_BUNDLE" in html and '"debug": true' in html.replace(
        '"debug":true', '"debug": true'
    )


def _with_assets(tmp_path: Path, asset_path: str) -> Path:
    doc = json.loads(PADDLE.read_text(encoding="utf-8"))
    doc["stage"]["assets"] = [{"name": "hit", "kind": "sound", "path": asset_path}]
    source = tmp_path / "game.jin"
    source.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return source


def test_build_copies_assets_and_rewrites_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "sounds").mkdir()
    (tmp_path / "sounds" / "hit.wav").write_bytes(b"RIFF....")
    source = _with_assets(tmp_path, "sounds/hit.wav")
    out = tmp_path / "dist"
    result = invoke("build", source, "--out", out)
    assert result.exit_code == 0, result.output
    assert (out / "assets" / "hit.wav").read_bytes() == b"RIFF...."
    manifest = json.loads((out / "game.manifest.json").read_text(encoding="utf-8"))
    assert manifest["assets"] == [{"name": "hit", "kind": "sound", "path": "assets/hit.wav"}]


@pytest.mark.parametrize("asset_path", ["../outside.wav", "/etc/hostname"])
def test_build_refuses_assets_outside_the_source_directory(tmp_path: Path, asset_path: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.wav").write_bytes(b"x")
    source = _with_assets(project, asset_path)
    out = tmp_path / "dist"
    result = invoke("build", source, "--out", out)
    assert result.exit_code == 1
    assert "asset" in result.stderr
    assert not out.exists()


def test_build_refuses_a_symlinked_asset(tmp_path: Path) -> None:
    (tmp_path / "real.wav").write_bytes(b"x")
    os.symlink(tmp_path / "real.wav", tmp_path / "link.wav")
    source = _with_assets(tmp_path, "link.wav")
    result = invoke("build", source, "--out", tmp_path / "dist")
    assert result.exit_code == 1 and "シンボリックリンク" in result.stderr
