"""位置変換（`docs/spec/diagnostics.md` §5.1）。

`jin_core` は **1 始まり / コードポイント / end 排他**、LSP は **0 始まり / UTF-16 コードユニット**。
変換は `jin_lsp.positions` の 1 モジュールだけが行う（CLAUDE.md「書くときの約束」）。
"""

from __future__ import annotations

import pytest
from jin_core.diagnostics import Position as JinPosition
from jin_core.diagnostics import Range as JinRange
from jin_lsp import positions
from lsprotocol import types

# サロゲートペア（U+1F600）を含む行。UTF-16 では 2 コードユニット、コードポイントでは 1。
ASTRAL_LINE = '  "rune": "😀 描け",\n'
# BMP 内の日本語。UTF-16 でも 1 コードユニット。
CJK_LINE = '  "rune": "日本語で描け",\n'


def test_ascii_only_shifts_the_base() -> None:
    """ASCII だけなら基点の 1 → 0 の差だけが出る。"""
    lines = ['{"root": "A"}\n']
    jin = JinRange(JinPosition(1, 10), JinPosition(1, 13))
    assert positions.to_lsp_range(lines, jin) == types.Range(
        start=types.Position(line=0, character=9),
        end=types.Position(line=0, character=12),
    )


def test_cjk_is_one_utf16_unit_per_codepoint() -> None:
    """BMP 内の日本語はコードポイントと UTF-16 コードユニットが 1:1（列がずれない）。"""
    lines = [CJK_LINE]
    # `日本語で描け` の直後（コードポイント 21 = 1 始まり）
    jin = JinRange(JinPosition(1, 11), JinPosition(1, 19))
    lsp = positions.to_lsp_range(lines, jin)
    assert lsp.start.character == 10
    assert lsp.end.character == 18


def test_astral_plane_costs_two_utf16_units() -> None:
    """サロゲートペアは UTF-16 で 2 コードユニット。**ここで変換しないと列がずれる**。

    `ASTRAL_LINE` は `  "rune": "😀 描け",` で、`😀` はコードポイント 12（1 始まり）に居る。
    その直後のコードポイント 13 は UTF-16 では 13 番目のコードユニットの**次**、
    すなわち 0 始まりで 13 になる（絵文字が 1 つ余分に食う）。
    """
    lines = [ASTRAL_LINE]
    after_emoji = positions.to_lsp_position(lines, JinPosition(1, 13))
    assert after_emoji.character == 13, "サロゲートペアぶんの +1 が乗っていない"
    # コードポイント基準なら 12 になるので、素の `col - 1` では通らない
    assert after_emoji.character != 12


def test_round_trip_is_idempotent_and_lands_on_a_codepoint_boundary() -> None:
    """LSP → jin → LSP が**安定点**に落ち、もう一度回しても動かない。

    恒等ではない。`ASTRAL_LINE` の `character=12` は `😀` のサロゲートペアの**途中**を指し、
    コードポイントでは表現できないので境界へ丸められる（そこだけ 12 → 13 に動く）。
    LSP 仕様もこの丸めをクライアントに許している。ここで固定するのは
    「丸めが 1 回で収束する」ことで、これが崩れると打鍵のたびに位置が漂う。
    """
    lines = [ASTRAL_LINE, CJK_LINE]
    moved: list[int] = []
    for line_index, line in enumerate(lines):
        for character in range(len(line.encode("utf-16-le")) // 2):
            lsp = types.Position(line=line_index, character=character)
            once = positions.to_lsp_position(lines, positions.from_lsp_position(lines, lsp))
            twice = positions.to_lsp_position(lines, positions.from_lsp_position(lines, once))
            assert twice == once, f"{line_index}:{character} で収束しない"
            if once != lsp:
                moved.append(character)
    # 動くのはサロゲートペアの中間 1 点だけ（`ASTRAL_LINE` の `😀` は 1 文字しかない）
    assert moved == [12], f"想定外の位置で丸めが起きた: {moved}"


def test_positions_outside_a_surrogate_pair_round_trip_exactly() -> None:
    """コードポイント境界の上なら LSP → jin → LSP は恒等。"""
    lines = [CJK_LINE]
    for character in range(len(CJK_LINE.encode("utf-16-le")) // 2):
        lsp = types.Position(line=0, character=character)
        assert positions.to_lsp_position(lines, positions.from_lsp_position(lines, lsp)) == lsp


def test_from_lsp_position_is_one_based() -> None:
    """LSP（0 始まり）→ jin（1 始まり）。"""
    lines = ['{"root": "A"}\n']
    jin = positions.from_lsp_position(lines, types.Position(line=0, character=0))
    assert jin == JinPosition(1, 1)


def test_diagnostic_carries_code_severity_and_hint() -> None:
    """`hint` は `data` に載せ、**`message` にも足す**（要件書 §5 / 成功条件 3）。

    `data` はクライアントが codeAction の往復で持ち回るもので、人には表示されない。
    hint が見えなければ「LSP 診断の出力だけで修正しきれる」は成り立たない。
    """
    from jin_core.diagnostics import Diagnostic as JinDiagnostic

    lines = ['{"root": "Summarizr"}\n']
    jin = JinDiagnostic(
        file="a.jin",
        pointer="/root",
        range=JinRange(JinPosition(1, 11), JinPosition(1, 21)),
        code="JIN011",
        severity="error",
        message="circle 'Summarizr' は定義されていません",
        hint="近い名前: Summarizer",
    )
    lsp = positions.to_lsp_diagnostic(lines, jin)
    assert lsp.code == "JIN011"
    assert lsp.severity == types.DiagnosticSeverity.Error
    assert lsp.source == "jin"
    assert lsp.message == "circle 'Summarizr' は定義されていません\n近い名前: Summarizer"
    assert lsp.data == {"pointer": "/root", "hint": "近い名前: Summarizer"}


def test_warning_severity_maps_to_lsp_warning() -> None:
    from jin_core.diagnostics import Diagnostic as JinDiagnostic

    lines = ["{}\n"]
    jin = JinDiagnostic(
        file="a.jin",
        pointer="",
        range=JinRange(JinPosition(1, 1), JinPosition(1, 3)),
        code="JIN070",
        severity="warning",
        message="警告",
    )
    lsp = positions.to_lsp_diagnostic(lines, jin)
    assert lsp.severity == types.DiagnosticSeverity.Warning
    assert lsp.data == {"pointer": ""}


def test_hint_absent_leaves_only_the_pointer() -> None:
    """`hint` が無いときに `"hint": None` を送らない（クライアントが空文字を表示しないように）。"""
    from jin_core.diagnostics import Diagnostic as JinDiagnostic

    jin = JinDiagnostic(
        file="a.jin",
        pointer="/circles/0",
        range=JinRange(JinPosition(1, 1), JinPosition(1, 2)),
        code="JIN001",
        severity="error",
        message="x",
    )
    assert "hint" not in positions.to_lsp_diagnostic(["{}\n"], jin).data


@pytest.mark.parametrize("column", [0, -1])
def test_a_zero_or_negative_column_is_refused(column: int) -> None:
    """1 始まりの契約を破る値を黙って通さない（`col - 1` が負の列を作る前に落とす）。"""
    with pytest.raises(ValueError):
        positions.to_lsp_position(["{}\n"], JinPosition(1, column))


def test_a_position_past_the_end_of_the_line_is_clamped_not_crashed() -> None:
    """行末より後ろの列（診断の end が行末+1 を指すことがある）で落ちない。"""
    lines = ["{}\n"]
    lsp = positions.to_lsp_position(lines, JinPosition(1, 999))
    assert lsp.line == 0
    assert lsp.character >= 0
