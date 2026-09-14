"""`storage`（abilities.md §8・v2.1）と `num`（expr.md §4.1）。

ホスト境界は変えない: 入りは `boot` の `manifest.storage`（写し）、出は `tick` の戻り値の `storage`
（書き込みの一覧・あった tick だけ）。決定性の根拠は「1 回目の最後の記憶を 2 回目の boot に渡せば続く」こと。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_file
from jin_wasm.codegen import generate
from jin_wasm.jinrec import JinrecError, read_jinrec
from jin_wasm.runtime import InputState, LuaHost, apply_storage_writes, run_headless

REPO_ROOT = Path(__file__).resolve().parents[3]
PROGRAM = REPO_ROOT / "tests" / "fixtures" / "v2-programs" / "storage.jin"


def game(debug: bool = True):
    result = check_file(PROGRAM)
    assert result.ok, result.diagnostics
    assert result.model is not None
    return generate(result.model, source_name=PROGRAM.name, debug=debug)


# ---------------------------------------------------------------- 記憶が実行をまたいで続く


def test_the_memory_persists_across_runs_through_the_headless_result() -> None:
    """1 回目: runs = 1（無い鍵は "" → num → 0）。2 回目: 1 回目の記憶を渡すと runs = 2、best も更新。"""
    g = game()
    first = run_headless(g.lua, g.manifest, seed=7, ticks=3)
    assert first.public == {"Only.runs": 1, "Only.best": 1, "Only.label": ""}
    assert first.storage == {"runs": "1", "best": "1", "label": "run 1"}
    second = run_headless(g.lua, g.manifest, seed=7, ticks=3, storage=first.storage)
    assert second.public == {"Only.runs": 2, "Only.best": 2, "Only.label": "run 1"}
    assert second.storage == {"runs": "2", "best": "2", "label": "run 2"}
    # tick 0 の step が label を書き換えた後に描くので、画面は自分の書き込み（"run 2"）。
    assert ["text", "run 2", 2, 2] in second.frames[0]["ops"]
    # 渡した写しは書き換えられない（ホストの辞書が正）。
    assert first.storage == {"runs": "1", "best": "1", "label": "run 1"}


def test_writes_appear_only_in_the_ticks_that_wrote_and_in_release_too() -> None:
    """`storage` は書き込みがあった tick の結果にだけ載る（release でも）。キーの順は public の直後。"""
    for debug in (True, False):
        g = game(debug)
        host = LuaHost(g.lua)
        host.boot(7, {**g.manifest, "storage": {"runs": "4", "best": "9"}})
        first = host.tick(0, InputState().apply([]))
        # boot の核で runs を書き、tick 0 の step は runs(5) < best(9) なので best は書かない。
        assert first["storage"] == [["runs", "5"]]
        keys = list(first)
        assert keys.index("storage") == keys.index("public") + 1
        if not debug:
            assert keys == ["ops", "audio", "done", "error", "public", "storage"]
        second = host.tick(1, InputState().apply([]))
        assert "storage" not in second
        assert second["public"] == {"Only.runs": 5, "Only.best": 9, "Only.label": ""}


def test_get_sees_own_writes_before_the_boot_copy_and_empty_when_missing() -> None:
    g = game()
    host = LuaHost(g.lua)
    host.boot(7, {**g.manifest, "storage": {"label": "old", "junk": "x"}})
    result = host.tick(0, InputState().apply([]))
    # 核: runs = 0 + 1 → set("runs", "1")。step: runs(1) > best(0) → best / label を書く。
    assert result["storage"] == [["runs", "1"], ["best", "1"], ["label", "run 1"]]
    assert result["public"] == {"Only.runs": 1, "Only.best": 1, "Only.label": "old"}
    # 書いた後の get は自分の値（画面の text は "run 1"）。
    assert ["text", "run 1", 2, 2] in result["ops"]


def test_a_broken_storage_copy_is_read_as_empty() -> None:
    """manifest.storage が無い / 形が合わない値は空として読む（落とさない）。"""
    g = game()
    for storage in (None, "text", 5, [], {"runs": 3}, {"runs": None}):
        host = LuaHost(g.lua)
        manifest = dict(g.manifest)
        if storage is not None:
            manifest["storage"] = storage
        host.boot(7, manifest)
        result = host.tick(0, InputState().apply([]))
        assert result["public"]["Only.runs"] == 1, storage


def test_cmp_in_the_boot_core_orders_by_code_point() -> None:
    """expr.md §4.1（v2.1）: 核が `order = cmp("B", "a") + cmp("ｱ", "😀") * 2` を 1 回 set する。

    どちらもコードポイント順で -1 なので -3。ロケールの照合順なら 1 つ目が、UTF-16 のコード単位順なら
    2 つ目が逆になり、どちらが割れても値が変わる。ブラウザ（Wasmoon）とのパリティは
    `apps/player/e2e/storage.spec.ts` がトレースの全行一致とこの行の値で見る。
    """
    g = game()
    result = run_headless(g.lua, g.manifest, seed=7, ticks=1)
    orders = [row for row in result.rows if row["kind"] == "set" and row["name"] == "order"]
    assert [row["output"] for row in orders] == [-3]
    assert "Only.order" not in result.public  # out: false（公開 state の検査を増やさない）


def test_apply_storage_writes_ignores_malformed_entries() -> None:
    store: dict[str, str] = {"a": "1"}
    apply_storage_writes(store, {"storage": [["a", "2"], ["b"], "x", ["c", 3], ["d", "4"]]})
    assert store == {"a": "2", "d": "4"}
    apply_storage_writes(store, {})
    assert store == {"a": "2", "d": "4"}


# ---------------------------------------------------------------- num（str の逆）


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", 3.0),
        ("-3", -3.0),
        ("0.5", 0.5),
        ("1e3", 1000.0),
        ("1.5E-2", 0.015),
        ("", 0.0),  # 無い鍵
        (" 3", 0.0),
        ("3 ", 0.0),
        ("0x10", 0.0),
        ("inf", 0.0),
        ("nan", 0.0),
        ("1e999", 0.0),  # 溢れは 0
        (".5", 0.0),
        ("3.", 0.0),
        ("+3", 0.0),
        ("abc", 0.0),
    ],
)
def test_num_accepts_only_the_str_and_json_number_forms(
    prelude: Any, text: str, expected: float
) -> None:
    got = prelude.F.num(text)
    assert got == expected and isinstance(got, float), (text, got)


def test_num_round_trips_str(prelude: Any) -> None:
    for value in (0.0, 1.0, -2.5, 0.1, 1e21, 123456789.0, 2.0**53):
        assert prelude.F.num(prelude.F.str(value)) == value


# ---------------------------------------------------------------- 録画のヘッダ


def test_the_recording_header_carries_the_storage_copy(tmp_path: Path) -> None:
    path = tmp_path / "r.jinrec"
    path.write_text(
        json.dumps({"jinrec": 1, "seed": 7, "ticks": 2, "storage": {"runs": "3"}}) + "\n",
        encoding="utf-8",
    )
    assert read_jinrec(path).storage == {"runs": "3"}
    path.write_text(json.dumps({"jinrec": 1, "seed": 7}) + "\n", encoding="utf-8")
    assert read_jinrec(path).storage is None
    for broken in ('{"jinrec": 1, "storage": [1]}', '{"jinrec": 1, "storage": {"a": 1}}'):
        path.write_text(broken + "\n", encoding="utf-8")
        with pytest.raises(JinrecError, match="storage"):
            read_jinrec(path)


def test_headless_run_with_a_recording_uses_the_header_copy(tmp_path: Path) -> None:
    """`jin run --input` と同じ経路: ヘッダの storage → boot の写し。"""
    g = game()
    path = tmp_path / "r.jinrec"
    path.write_text(
        json.dumps({"jinrec": 1, "seed": 7, "ticks": 2, "storage": {"runs": "3", "best": "3"}})
        + "\n",
        encoding="utf-8",
    )
    recording = read_jinrec(path)
    result = run_headless(
        g.lua, g.manifest, seed=7, ticks=recording.ticks or 0, storage=recording.storage
    )
    assert result.public == {"Only.runs": 4, "Only.best": 4, "Only.label": ""}
