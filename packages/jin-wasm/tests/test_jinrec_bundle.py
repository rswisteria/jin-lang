"""`.jinrec` の読み書き（runtime.md §7）と bundle の書き出し（§9）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_wasm.bundle import WriteRefused, player_available, write_bundle
from jin_wasm.codegen import generate
from jin_wasm.jinrec import JinrecError, dumps_jinrec, read_jinrec

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2" / "fib" / "fib.jin"


# ---------------------------------------------------------------- jinrec


def test_jinrec_round_trip(tmp_path: Path) -> None:
    events = [
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 9, "kind": "key", "name": "ArrowLeft", "down": False},
        {"tick": 40, "kind": "pointer", "x": 150, "y": 110, "down": True},
        {"tick": 40, "kind": "pointer", "x": 150.5, "y": 110, "down": False},
    ]
    path = tmp_path / "r.jinrec"
    path.write_text(
        dumps_jinrec({"file": "paddle.jin", "seed": 7, "fps": 60, "ticks": 600}, events),
        encoding="utf-8",
    )
    rec = read_jinrec(path)
    assert (rec.file, rec.seed, rec.fps, rec.ticks) == ("paddle.jin", 7, 60, 600)
    assert rec.events == [
        {"tick": 3, "kind": "key", "name": "ArrowLeft", "down": True},
        {"tick": 9, "kind": "key", "name": "ArrowLeft", "down": False},
        {"tick": 40, "kind": "pointer", "x": 150.0, "y": 110.0, "down": True},
        {"tick": 40, "kind": "pointer", "x": 150.5, "y": 110.0, "down": False},
    ]


def test_jinrec_header_only_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "r.jinrec"
    path.write_text('﻿{"jinrec": 1}\r\n\n', encoding="utf-8")  # 先頭 BOM + CRLF + 空行
    rec = read_jinrec(path)
    assert rec.events == [] and rec.ticks is None


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "ヘッダ"),
        ('{"jinrec": 2}\n', "1 行目"),
        ("[1]\n", "オブジェクト"),
        ('{"jinrec": 1, "ticks": "x"}\n', "整数"),
        ('{"jinrec": 1}\n{"tick": -1, "kind": "key", "name": "A", "down": true}\n', "0 以上"),
        ('{"jinrec": 1}\n{"tick": 1, "kind": "mouse"}\n', "kind"),
        ('{"jinrec": 1}\n{"tick": 1, "kind": "key", "name": 1, "down": true}\n', "name"),
        ('{"jinrec": 1}\n{"tick": 1, "kind": "key", "name": "A", "down": 1}\n', "down"),
        ('{"jinrec": 1}\n{"tick": 1, "kind": "pointer", "x": "a", "y": 1, "down": true}\n', "x"),
        ('{"jinrec": 1}\nnot json\n', "JSON"),
    ],
)
def test_jinrec_rejects_broken_files_with_a_line_number(
    tmp_path: Path, text: str, fragment: str
) -> None:
    path = tmp_path / "r.jinrec"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(JinrecError) as info:
        read_jinrec(path)
    assert fragment in str(info.value)
    assert str(path) in str(info.value)


# ---------------------------------------------------------------- bundle


def game():
    result = check_file(FIB)
    return generate(result.model, source_name="fib.jin")


def test_bundle_writes_game_and_manifest(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    result = write_bundle(game(), out, source=FIB)
    assert [p.name for p in result.written] == ["game.lua", "game.manifest.json"]
    manifest = json.loads((out / "game.manifest.json").read_text(encoding="utf-8"))
    assert manifest["jil"] == game().manifest["jil"]
    assert not player_available()
    assert result.notes and "Phase 4" in result.notes[0]


def test_bundle_refuses_existing_files_and_leaves_nothing_behind(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    out.mkdir()
    (out / "game.manifest.json").write_text("old", encoding="utf-8")
    with pytest.raises(WriteRefused):
        write_bundle(game(), out, source=FIB)
    assert sorted(p.name for p in out.iterdir()) == ["game.manifest.json"]
    assert (out / "game.manifest.json").read_text(encoding="utf-8") == "old"


def test_bundle_force_replaces_through_a_temporary_file(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    write_bundle(game(), out, source=FIB)
    before = (out / "game.lua").read_text(encoding="utf-8")
    debug = generate(check_file(FIB).model, source_name="fib.jin", debug=True)
    write_bundle(debug, out, source=FIB, force=True)
    after = (out / "game.lua").read_text(encoding="utf-8")
    assert before != after and "DEBUG = true" in after
    assert not list(out.glob(".*"))


def test_bundle_refuses_a_symlinked_out_dir(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    with pytest.raises(WriteRefused):
        write_bundle(game(), link, source=FIB)
    assert list(real.iterdir()) == []


def test_bundle_refuses_a_regular_file_as_out(tmp_path: Path) -> None:
    out = tmp_path / "file"
    out.write_text("x", encoding="utf-8")
    with pytest.raises(WriteRefused):
        write_bundle(game(), out, source=FIB)


def test_bundle_removes_the_directory_it_created_on_failure(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "dist"
    from jin_wasm import bundle

    def boom(fd: int, data: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(bundle, "_write_all", boom)
    with pytest.raises(WriteRefused):
        write_bundle(game(), out, source=FIB)
    assert not out.exists()


def test_bundle_single_is_refused_without_the_player(tmp_path: Path) -> None:
    with pytest.raises(WriteRefused) as info:
        write_bundle(game(), tmp_path / "dist", source=FIB, single=True)
    assert "Phase 4" in str(info.value)
