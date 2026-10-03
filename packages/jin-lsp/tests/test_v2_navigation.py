"""Jin v2 の definition / references / documentSymbol / rename / codeAction（設計書 §11 #58）。

参照の表は `jin_core.v2.references`（`rename` の追随と同じ）。ここで固定するのは LSP 側の
写し方: 式の中の名前は**識別子だけ**の範囲（引用符の内側・UTF-16）になること、編集は
`jin_core.v2.ops` を当てた正準形の全文になること、ops.md §4 の表の quickfix が診断を消すこと。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jin_core.canonical import dumps
from jin_core.check import check_text
from jin_core.v2.ops import OPERATIONS, apply_op
from jin_lsp import positions
from jin_lsp.features import v2_edits, v2_navigation
from jin_lsp.session import DocumentState, DocumentStore
from lsprotocol import types

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = (REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin").read_text(encoding="utf-8")
ERRORS = REPO_ROOT / "tests" / "fixtures" / "errors" / "v2"
URI = "file:///paddle.jin"


def open_text(text: str, uri: str = URI) -> DocumentState:
    return DocumentStore().update(uri, text)


def at(text: str, needle: str, inside: str, offset: int = 0) -> types.Position:
    """`needle` を含む最初の行で、`inside` の先頭から `offset` 文字目（LSP の 0 始まり）。"""
    for index, line in enumerate(text.splitlines()):
        if needle in line:
            return types.Position(line=index, character=line.index(inside) + offset)
    raise AssertionError(f"{needle!r} を含む行が無い")


def covered(text: str, range_: types.Range) -> str:
    """LSP の範囲が指す文字列（1 行に収まる範囲だけ）。"""
    assert range_.start.line == range_.end.line
    line = text.splitlines()[range_.start.line]
    return line[range_.start.character : range_.end.character]


# ---------------------------------------------------------------- definition / references


def test_definition_from_an_identifier_in_an_expression_jumps_to_the_state_name() -> None:
    state = open_text(PADDLE)
    position = at(PADDLE, '"expr": "score + 1"', "score + 1", 2)
    found = v2_navigation.definition(state, URI, position)
    assert found is not None
    assert covered(PADDLE, found.range) == "score"
    assert '"name": "score"' in PADDLE.splitlines()[found.range.start.line]


def test_definition_from_a_public_state_of_another_circle_and_from_the_circle_name() -> None:
    state = open_text(PADDLE)
    line = "str(Play.score)"  # 原文は `"\"SCORE \" ++ str(Play.score)"`（JSON のエスケープ込み）
    to_state = v2_navigation.definition(state, URI, at(PADDLE, line, "score)", 1))
    to_circle = v2_navigation.definition(state, URI, at(PADDLE, line, "Play.", 1))
    assert to_state is not None and to_circle is not None
    assert '"name": "score"' in PADDLE.splitlines()[to_state.range.start.line]
    assert covered(PADDLE, to_circle.range) == "Play"
    assert '"name": "Play"' in PADDLE.splitlines()[to_circle.range.start.line]


def test_definition_from_structural_references() -> None:
    state = open_text(PADDLE)
    core = v2_navigation.definition(state, URI, at(PADDLE, '"core": "begin"', '"begin"', 2))
    cast = v2_navigation.definition(state, URI, at(PADDLE, '"target": "paint"', '"paint"', 2))
    head = v2_navigation.definition(state, URI, at(PADDLE, '"target": "canvas.clear"', "canvas", 1))
    assert [covered(PADDLE, d.range) for d in (core, cast, head) if d is not None] == [
        "begin",
        "paint",
        "canvas",
    ]


def test_no_definition_inside_a_string_literal_or_off_a_name() -> None:
    state = open_text(PADDLE)
    inside_literal = at(PADDLE, "str(Play.score)", "SCORE", 1)
    assert v2_navigation.definition(state, URI, inside_literal) is None
    assert v2_navigation.definition(state, URI, at(PADDLE, '"width": 320', "320")) is None


def test_references_list_every_use_with_identifier_ranges() -> None:
    state = open_text(PADDLE)
    position = at(PADDLE, '"name": "score"', '"score"', 1)
    found = v2_navigation.references_at(state, URI, position)
    assert [covered(PADDLE, location.range) for location in found] == ["score"] * 6
    with_declaration = v2_navigation.references_at(state, URI, position, include_declaration=True)
    assert len(with_declaration) == 7
    assert with_declaration[0].range.start.line == position.line


def test_references_count_utf16_columns_for_non_ascii_text() -> None:
    """式の前に BMP 外の文字があると、UTF-16 の列はコードポイントの列より 1 つ進む。"""
    text = PADDLE.replace('SCORE \\" ++ str(Play.score)', '😀 \\" ++ str(Play.score)')
    assert text != PADDLE
    state = open_text(text)
    found = v2_navigation.references_at(state, URI, at(text, '"name": "score"', '"score"', 1))
    other = [loc for loc in found if "Play.score" in text.splitlines()[loc.range.start.line]]
    assert len(other) == 1
    line = text.splitlines()[other[0].range.start.line]
    utf16 = line.encode("utf-16-le")
    start, end = other[0].range.start.character, other[0].range.end.character
    assert utf16[start * 2 : end * 2].decode("utf-16-le") == "score"


def test_navigation_answers_from_the_last_good_model_while_the_text_is_broken() -> None:
    store = DocumentStore()
    store.update(URI, PADDLE)
    broken = store.update(URI, PADDLE[:-10])  # 末尾を切って構文エラーにする
    assert broken.model is None
    position = at(PADDLE, '"expr": "score + 1"', "score + 1", 1)
    assert v2_navigation.definition(broken, URI, position) is not None
    assert v2_navigation.document_symbols(broken)


# ---------------------------------------------------------------- documentSymbol


def test_document_symbols_nest_forms_and_circles() -> None:
    symbols = v2_navigation.document_symbols(open_text(PADDLE))
    names = [s.name for s in symbols]
    assert names == ["Ball", "Game", "Play", "Result"]
    ball = symbols[0]
    assert ball.kind == types.SymbolKind.Struct
    assert [f.name for f in ball.children or []] == ["x", "y", "vx", "vy"]
    play = symbols[2]
    children = {child.name: child for child in play.children or []}
    assert children["score"].detail == "num（公開）"
    assert children["canvas"].detail == "host canvas"
    assert children["begin"].detail == "()（核）"
    assert [p.name for p in children["step"].children or []] == ["dt"]
    assert "on tick" in children
    assert covered(PADDLE, play.selection_range) == '"Play"'
    game = symbols[1]
    assert [c.name for c in game.children or []] == ["flow: loop"]


# ---------------------------------------------------------------- rename


def test_prepare_rename_returns_the_identifier_and_its_name() -> None:
    state = open_text(PADDLE)
    found = v2_edits.prepare_rename(state, at(PADDLE, '"cond": "input.key', "input.", 2))
    assert isinstance(found, types.PrepareRenamePlaceholder)
    assert covered(PADDLE, found.range) == "input"
    assert found.placeholder == "input"
    assert v2_edits.prepare_rename(state, at(PADDLE, '"width": 320', "320")) is None


def test_rename_from_a_reference_matches_the_rename_operation_byte_for_byte() -> None:
    state = open_text(PADDLE)
    edit = v2_edits.rename(state, URI, at(PADDLE, '"expr": "score + 1"', "score", 1), "points")
    assert edit is not None
    [text_edit] = edit.changes[URI]
    expected = apply_op(
        state.model, {"op": "rename", "pointer": "/circles/1/state/2", "value": "points"}
    )
    assert text_edit.new_text == dumps(expected.model)
    assert "Play.points" in text_edit.new_text
    assert check_text(text_edit.new_text, "x.jin").diagnostics == []


def test_rename_refuses_a_duplicate_name_and_a_broken_text() -> None:
    state = open_text(PADDLE)
    assert v2_edits.rename(state, URI, at(PADDLE, '"name": "score"', '"score"', 1), "ball") is None
    broken = DocumentStore()
    broken.update(URI, PADDLE)
    broken_state = broken.update(URI, PADDLE[:-10])
    position = at(PADDLE, '"name": "score"', '"score"', 1)
    assert v2_edits.rename(broken_state, URI, position, "points") is None
    assert v2_edits.prepare_rename(broken_state, position) is None


# ---------------------------------------------------------------- codeAction（ops.md §4）


def actions_for(state: DocumentState) -> list[types.CodeAction]:
    diagnostics = [positions.to_lsp_diagnostic(state.lines, d) for d in state.diagnostics]
    params = types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri=URI),
        range=types.Range(types.Position(0, 0), types.Position(0, 0)),
        context=types.CodeActionContext(diagnostics=diagnostics),
    )
    found = v2_edits.code_actions(state, URI, params)
    return [action for action in found if isinstance(action, types.CodeAction)]


def after(action: types.CodeAction) -> list[str]:
    assert action.edit is not None and action.edit.changes is not None
    return [d.code for d in check_text(action.edit.changes[URI][0].new_text, "x.jin").diagnostics]


@pytest.mark.parametrize(
    ("fixture", "title"),
    [
        ("JIN204_namespace_not_granted", "道具環に 'canvas' を足す"),
        ("JIN210_too_many_steps", "2 個のステップを手順 'mainExtracted' に抽出する"),
        ("JIN211_nesting_too_deep", "1 個のステップを手順 'mainExtracted' に抽出する"),
        ("JIN220_exit_not_public", "A の state 'done' を公開する（out: true）"),
        ("JIN230_key_without_input", "道具環に 'input' を足す"),
        ("JIN240_unreachable_step", "到達しないステップを消す"),
    ],
)
def test_each_quick_fix_of_the_table_clears_its_diagnostic(fixture: str, title: str) -> None:
    state = open_text((ERRORS / f"{fixture}.jin").read_text(encoding="utf-8"))
    [action] = actions_for(state)
    assert action.title == title
    assert action.kind == types.CodeActionKind.QuickFix
    assert after(action) == []


def test_a_near_name_replaces_only_the_identifier_in_the_expression() -> None:
    text = PADDLE.replace('"expr": "score + 1"', '"expr": "scor + 1"')
    state = open_text(text)
    assert [d.code for d in state.diagnostics] == ["JIN203"]
    [action] = actions_for(state)
    assert action.title == "'score' に置き換える"
    assert after(action) == []
    assert action.edit.changes[URI][0].new_text == dumps(open_text(PADDLE).model)


def test_a_bare_name_in_flow_exit_becomes_the_public_state_of_a_child() -> None:
    text = PADDLE.replace('"exit": "Result.quit"', '"exit": "quit"')
    state = open_text(text)
    assert [d.code for d in state.diagnostics] == ["JIN220"]
    [action] = actions_for(state)
    assert action.title == "exit を 'Result.quit' にする（state を公開する）"
    assert action.edit.changes[URI][0].new_text == dumps(open_text(PADDLE).model)


def test_code_actions_expose_the_32_operations_as_commands() -> None:
    state = open_text(PADDLE)
    params = types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri=URI),
        range=types.Range(types.Position(0, 0), types.Position(0, 0)),
        context=types.CodeActionContext(diagnostics=[]),
    )
    commands = v2_edits.code_actions(state, URI, params)
    assert all(isinstance(c, types.Command) for c in commands)
    assert [c.arguments[0]["op"] for c in commands] == sorted(OPERATIONS)
