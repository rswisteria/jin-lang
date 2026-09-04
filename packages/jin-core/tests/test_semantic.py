"""意味検査の回帰テスト（修正ラウンド 1）。

`docs/spec/model.md` §5（可視な state）と `docs/spec/diagnostics.md` §4（優先順位）を
コード側から固定する。
"""

from __future__ import annotations

import json
import time

import pytest
from jin_core.check import check_text
from jin_core.model import DEFAULT_SCHEMA_URL, JinFile
from jin_core.semantic import (
    MAX_CANDIDATES_SCANNED,
    _build_graph,
    _find_cycle,
    _subtree_states,
    close_names,
    levenshtein,
    replace_rune_key,
    rune_keys,
)


def document(root: str, circles: list[dict]) -> str:
    return json.dumps(
        {"$schema": DEFAULT_SCHEMA_URL, "version": 1, "root": root, "circles": circles},
        ensure_ascii=False,
    )


def codes(text: str) -> list[str]:
    return [d.code for d in check_text(text, "t.jin").diagnostics]


# --------------------------------------------------------------------------------------
# B-8: rune の {key} 抽出とエスケープ
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("rune", "expected"),
    [
        ("{a}", ["a"]),
        ("{{a}}", []),  # リテラルの {a}
        ("{a}}", ["a"]),  # 参照 a + リテラルの }
        ("{{{a}}}", ["a"]),  # リテラル { + 参照 a + リテラル }
        ("{{a}", []),  # リテラル { + 'a}' （参照ではない）
        ("x{a}y{b}z", ["a", "b"]),
        ("{a}{a}", ["a", "a"]),
        ("{1a}", []),  # 識別子として不正
        ("{a", []),
        ("a}", []),
    ],
)
def test_rune_keys_follows_the_escape_rules(rune: str, expected: list[str]) -> None:
    """B-8: `"{a}}"` は「参照 a + リテラル `}`」（docs/spec/model.md §3.1）。

    修正前は単一の正規表現に否定先読み `(?!\\})` があり、この形を取りこぼして
    JIN050 が素通りしていた。
    """
    assert rune_keys(rune) == expected


def test_jin050_fires_for_a_key_followed_by_a_literal_brace() -> None:
    """B-8 の実害: `{missing}}` が JIN050 をすり抜けていた。"""
    text = document(
        "A",
        [{"name": "A", "core": "m", "instruction": {"rune": "{missing}}"}}],
    )
    assert codes(text) == ["JIN050"]


# --------------------------------------------------------------------------------------
# S8: rename の置換にテンプレート展開を混ぜない
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("new", ["\\g<0>", "\\1", "\\\\", "b\\g<1>c"])
def test_replace_rune_key_treats_the_new_name_literally(new: str) -> None:
    """S8: `re.sub` の置換文字列だと `\\g<0>` などが展開され、原文に無い内容が入る。"""
    assert replace_rune_key("x {a} y", "a", new) == "x {" + new + "} y"


def test_replace_rune_key_does_not_touch_escaped_braces() -> None:
    assert replace_rune_key("{{a}} {a}", "a", "b") == "{{a}} {b}"


def test_replace_rune_key_handles_a_key_before_a_literal_brace() -> None:
    assert replace_rune_key("{a}}", "a", "b") == "{b}}"


# --------------------------------------------------------------------------------------
# B-1: JIN013 の文言
# --------------------------------------------------------------------------------------
def test_jin013_same_parent_twice_is_not_reported_as_two_parents() -> None:
    """B-1: 同じ親が 2 回参照しても「2 個の親を持っています: P / P」と言わない。"""
    text = document(
        "P",
        [
            {"name": "P", "flow": {"kind": "sequence", "steps": ["C", "C"]}},
            {"name": "C", "core": "m"},
        ],
    )
    diagnostics = check_text(text, "t.jin").diagnostics
    assert [d.code for d in diagnostics] == ["JIN013"]
    message = diagnostics[0].message
    assert "P / P" not in message
    assert "'P' から 2 回参照" in message


def test_jin013_distinct_parents_still_lists_them() -> None:
    text = document(
        "P",
        [
            {"name": "P", "flow": {"kind": "sequence", "steps": ["C", "Q"]}},
            {"name": "Q", "delegate": ["C"], "core": "m"},
            {"name": "C", "core": "m"},
        ],
    )
    diagnostics = [d for d in check_text(text, "t.jin").diagnostics if d.code == "JIN013"]
    assert len(diagnostics) == 1
    assert "2 個の親" in diagnostics[0].message
    assert "P / Q" in diagnostics[0].message


# --------------------------------------------------------------------------------------
# B-2: flow.exit.key の未解決参照
# --------------------------------------------------------------------------------------
def test_unresolved_exit_key_is_reported() -> None:
    """B-2: `exit.key` が見える state に無いと loop が止まらない。"""
    text = document(
        "L",
        [
            {
                "name": "L",
                "flow": {"kind": "loop", "steps": ["W"], "exit": {"key": "done", "equals": True}},
            },
            {"name": "W", "core": "m"},
        ],
    )
    diagnostics = check_text(text, "t.jin").diagnostics
    assert [d.code for d in diagnostics] == ["JIN011"]
    assert diagnostics[0].pointer == "/circles/0/flow/exit/key"


def test_exit_key_produced_inside_the_loop_body_is_accepted() -> None:
    text = document(
        "L",
        [
            {
                "name": "L",
                "flow": {"kind": "loop", "steps": ["W"], "exit": {"key": "done", "equals": True}},
            },
            {"name": "W", "core": "m", "state": [{"name": "done", "type": "bool", "out": True}]},
        ],
    )
    assert codes(text) == []


def test_exit_key_declared_on_the_loop_itself_is_accepted() -> None:
    text = document(
        "L",
        [
            {
                "name": "L",
                "state": [{"name": "done", "type": "bool"}],
                "flow": {"kind": "loop", "steps": ["W"], "exit": {"key": "done", "equals": True}},
            },
            {"name": "W", "core": "m"},
        ],
    )
    assert codes(text) == []


# --------------------------------------------------------------------------------------
# ADR-014 / DP-JIN-JIN050-LOOP-SCOPE-01: loop の兄弟可視性（machine-readable: upstream-rule）
# --------------------------------------------------------------------------------------
def test_loop_makes_every_sibling_branch_visible() -> None:
    """`docs/spec/model.md` §5 の loop 行「すべての兄弟枝の部分木を含める」。

    ADR-014 は現仕様の維持を決めた（案: 厳格化しない）。その代わり、この規則が
    コードで実際に成立していることをテストで固定する。**後ろの兄弟が作る state を
    前の兄弟が読んでも JIN050 を出さない**のが loop の扱い。
    """
    text = document(
        "L",
        [
            {
                "name": "L",
                "flow": {"kind": "loop", "steps": ["X", "Y"], "max": 3},
            },
            {"name": "X", "core": "m", "instruction": {"rune": "{later}"}},
            {"name": "Y", "core": "m", "state": [{"name": "later", "type": "str", "out": True}]},
        ],
    )
    assert codes(text) == []


def test_sequence_does_not_make_later_siblings_visible() -> None:
    """同じ形でも sequence なら「先行する兄弟枝のみ」なので JIN050 が出る。"""
    text = document(
        "S",
        [
            {"name": "S", "flow": {"kind": "sequence", "steps": ["X", "Y"]}},
            {"name": "X", "core": "m", "instruction": {"rune": "{later}"}},
            {"name": "Y", "core": "m", "state": [{"name": "later", "type": "str", "out": True}]},
        ],
    )
    assert codes(text) == ["JIN050"]


def test_parallel_makes_no_sibling_visible() -> None:
    text = document(
        "P",
        [
            {"name": "P", "flow": {"kind": "parallel", "steps": ["X", "Y"]}},
            {"name": "X", "core": "m", "instruction": {"rune": "{other}"}},
            {"name": "Y", "core": "m", "state": [{"name": "other", "type": "str", "out": True}]},
        ],
    )
    assert codes(text) == ["JIN050"]


# --------------------------------------------------------------------------------------
# S3: 編集距離の枝刈り
# --------------------------------------------------------------------------------------
def test_levenshtein_is_exact_without_a_limit() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "abc") == 0


def test_levenshtein_stops_once_the_limit_is_exceeded() -> None:
    """S3: 上限を超えると確定した時点で打ち切る。値は「上限 + 1」で十分。"""
    assert levenshtein("kitten", "sitting", limit=1) == 2
    assert levenshtein("kitten", "sitting", limit=3) == 3
    # 長さの差だけで下界が決まる場合は行列を作らない。
    assert levenshtein("a", "a" * 500, limit=2) == 3


def test_close_names_scans_at_most_the_candidate_cap() -> None:
    """S3: 候補数に上限を置く。上限より後ろの候補は見ない。"""
    candidates = [f"name{i:05d}" for i in range(MAX_CANDIDATES_SCANNED + 5)]
    marker = "name99999x"
    assert close_names(marker, [*candidates, marker]) == []
    assert close_names(marker, [marker, *candidates]) == [marker]


def test_check_of_a_large_document_stays_fast() -> None:
    """S3: 大きな `.jin` で編集距離が二次的に効かないこと。

    修正前は 88 KB のファイルで `jin check` が 107 秒かかった（Phase 4 の LSP は
    打鍵ごとに `check_text` を呼ぶ）。1200 circle・全 delegate 未解決という最悪形での実測:

    | 状態 | 所要 |
    |---|---|
    | 修正前相当（候補数上限も打ち切りも予算も無し） | 15.75 秒 |
    | 候補数上限 500 + banded 早期打ち切りのみ（予算なし） | 3.76 秒 |
    | さらに `DistanceBudget`（本実装） | **0.20 秒** |

    上限 2.0 秒は実測の 10 倍の余裕がある。予算を外すと 3.76 秒、
    候補数上限まで外すと 15.75 秒になるので、どちらの後退も余裕をもって捕まる。
    """
    circles = [
        {"name": f"circle_{i:04d}", "core": "m", "delegate": [f"missing_{i:04d}"]}
        for i in range(1200)
    ]
    text = document("circle_0000", circles)
    started = time.perf_counter()
    result = check_text(text, "big.jin")
    elapsed = time.perf_counter() - started
    assert all(d.code == "JIN011" for d in result.diagnostics)
    assert len(result.diagnostics) == 1200  # 診断は 1 件も減らさない
    assert elapsed < 2.0, f"{elapsed:.2f} 秒かかりました"


def test_distance_budget_degrades_hints_deterministically() -> None:
    """S3: 予算を使い切ったあとは hint が「近い名前」から「定義済みの…」へ落ちる。

    落ちるのは hint の詳しさだけで、診断の件数・コード・位置は変わらない。
    消費は文書順なので同じ入力なら常に同じ出力になる（NFR-DET-002）。
    """
    from jin_core.semantic import MAX_DISTANCE_COMPUTATIONS, DistanceBudget

    names = [f"circle_{i:04d}" for i in range(400)]
    budget = DistanceBudget(total=len(names))
    # 1 回目は全候補を見られる。
    first = close_names("circle_0001x", names, budget=budget)
    assert first, "予算があるのに候補が返らない"
    assert first[0] == "circle_0001"
    # 予算を使い切ったので 2 回目は候補を 1 つも見ない。
    assert budget.remaining == 0
    assert close_names("circle_0002x", names, budget=budget) == []
    assert MAX_DISTANCE_COMPUTATIONS > 0


def test_large_document_diagnostics_are_reproducible() -> None:
    """S3: 予算の消費が入っても出力は決定的であること。"""
    circles = [{"name": f"c{i:04d}", "core": "m", "delegate": [f"c{i:04d}x"]} for i in range(300)]
    text = document("c0000", circles)
    first = [
        (d.code, d.pointer, d.message, d.hint) for d in check_text(text, "big.jin").diagnostics
    ]
    second = [
        (d.code, d.pointer, d.message, d.hint) for d in check_text(text, "big.jin").diagnostics
    ]
    assert first == second
    # 予算が効いている範囲では「近い名前」つきの hint が前方に集まる。
    detailed = [i for i, d in enumerate(first) if d[3].startswith("近い名前")]
    assert detailed, "近い名前の hint が 1 件も出ていない"
    assert detailed == sorted(detailed)


# --------------------------------------------------------------------------------------
# S4: 深い連鎖で RecursionError を出さない
# --------------------------------------------------------------------------------------
def test_find_cycle_handles_a_chain_longer_than_the_recursion_limit() -> None:
    """S4: `_find_cycle` は再帰しない。5000 段の連鎖 + 戻り辺で閉路を返す。"""
    length = 5000
    edges = [(f"c{i}", f"c{i + 1}") for i in range(length)]
    assert _find_cycle(edges) is None
    edges.append((f"c{length}", "c0"))
    cycle = _find_cycle(edges)
    assert cycle is not None
    assert cycle[0] == cycle[-1] == "c0"


def test_analyze_handles_a_chain_longer_than_the_recursion_limit() -> None:
    """S4: `_subtree_states` も再帰しない。2000 段の親子連鎖を通す。"""
    length = 2000
    circles: list[dict] = [
        {"name": f"c{i}", "flow": {"kind": "sequence", "steps": [f"c{i + 1}"]}}
        for i in range(length)
    ]
    circles.append({"name": f"c{length}", "core": "m", "state": [{"name": "deep", "type": "str"}]})
    model = JinFile.model_validate(json.loads(document("c0", circles)))
    graph = _build_graph(model, {c.name for c in model.circles})
    subtree = _subtree_states(model, graph)
    assert subtree["c0"] == {"deep"}
    assert subtree[f"c{length}"] == {"deep"}


def test_subtree_states_terminates_on_a_cycle() -> None:
    """循環していても畳めること（JIN012 は別に出る）。"""
    circles = [
        {
            "name": "A",
            "state": [{"name": "a", "type": "str"}],
            "flow": {"kind": "sequence", "steps": ["B"]},
        },
        {
            "name": "B",
            "state": [{"name": "b", "type": "str"}],
            "flow": {"kind": "sequence", "steps": ["A"]},
        },
    ]
    model = JinFile.model_validate(json.loads(document("A", circles)))
    graph = _build_graph(model, {c.name for c in model.circles})
    subtree = _subtree_states(model, graph)
    assert subtree["A"] == {"a", "b"}
    assert subtree["B"] == {"a", "b"}


def test_close_names_passes_the_threshold_as_a_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3: 打ち切り上限を `levenshtein` へ実際に渡していること。

    `levenshtein` 側に上限の実装があっても、呼び出し側が渡さなければ枝刈りは効かない。
    その取りこぼしは結果の値には出ないので、呼び出しの引数を直接見る。
    """
    from jin_core import semantic

    seen: list[int | None] = []
    original = semantic.levenshtein

    def spy(a: str, b: str, *, limit: int | None = None) -> int:
        seen.append(limit)
        return original(a, b, limit=limit)

    monkeypatch.setattr(semantic, "levenshtein", spy)
    semantic.close_names("searchh", ["search", "summarize", "translate"])
    assert seen, "levenshtein が呼ばれていない"
    assert all(limit is not None for limit in seen), seen
    assert set(seen) == {max(1, len("searchh") // 3)}
