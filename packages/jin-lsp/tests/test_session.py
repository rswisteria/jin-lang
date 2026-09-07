"""ドキュメント状態と last-good モデル（DP-COMMON-07 / NFR-AVAIL-001）。

DP-COMMON-07 の確定内容は「**last-good モデルを 1 世代だけ**保持し、SVG はキャッシュしない」。
NFR-AVAIL-001 は「JSON 構文エラー中も、直前の正常なモデルで hover / renderSvg を提供する」。
"""

from __future__ import annotations

from jin_lsp.session import DocumentStore

from .conftest import BROKEN, SEMANTIC_ERROR, minimal

GOOD = minimal("A")
GOOD_2 = minimal("B")


def test_a_valid_document_becomes_the_last_good_model() -> None:
    store = DocumentStore()
    state = store.update("file:///a.jin", GOOD)
    assert state.model is not None
    assert state.last_good is not None
    assert state.last_good.model.root == "A"


def test_a_syntax_error_keeps_the_previous_model_available() -> None:
    """段 1 で落ちても、直前の正常モデルで hover / renderSvg が答えられる。"""
    store = DocumentStore()
    store.update("file:///a.jin", GOOD)
    state = store.update("file:///a.jin", BROKEN)
    assert state.model is None, "壊れたテキストからモデルはできない"
    assert state.last_good is not None, "last-good が消えている（NFR-AVAIL-001 が満たせない）"
    assert state.last_good.model.root == "A"
    assert state.last_good.text == GOOD


def test_only_one_generation_of_last_good_is_kept() -> None:
    """**1 世代だけ**（DP-COMMON-07）。世代を積むと長寿命プロセスで際限なく太る。"""
    store = DocumentStore()
    store.update("file:///a.jin", GOOD)
    store.update("file:///a.jin", GOOD_2)
    state = store.update("file:///a.jin", BROKEN)
    assert state.last_good is not None
    assert state.last_good.model.root == "B", "1 つ前ではなく 2 つ前に戻っている"
    assert not hasattr(state, "history"), "履歴を持ってはならない（DP-COMMON-07）"


def test_a_semantic_error_still_updates_the_last_good_model() -> None:
    """`last_good` の「正常」は**パースでき schema を通った**まで。

    意味エラー（未定義 circle への参照など）を含むモデルでも `jin_render.render` は
    落ちない契約なので（phase3-handoff §5）、ここで捨てると壊れたモデルの図が見られなくなる。
    """
    store = DocumentStore()
    store.update("file:///a.jin", GOOD)
    state = store.update("file:///a.jin", SEMANTIC_ERROR)
    assert state.diagnostics, "JIN011 相当の意味診断が出ていない"
    assert state.last_good is not None
    assert state.last_good.model.root == "Nope", "意味エラーを理由に last-good を更新しなかった"


def test_closing_a_document_frees_its_state() -> None:
    """`didClose` で状態を捨てる（長寿命プロセスで開いたドキュメントを溜めない）。"""
    store = DocumentStore()
    store.update("file:///a.jin", GOOD)
    store.close("file:///a.jin")
    assert store.get("file:///a.jin") is None


def test_documents_do_not_share_state() -> None:
    store = DocumentStore()
    store.update("file:///a.jin", GOOD)
    store.update("file:///b.jin", GOOD_2)
    a = store.get("file:///a.jin")
    b = store.get("file:///b.jin")
    assert a is not None and b is not None
    assert a.model is not None and b.model is not None
    assert (a.model.root, b.model.root) == ("A", "B")


def test_lines_are_kept_for_position_conversion() -> None:
    """UTF-16 換算には行の中身が要る（`jin_lsp.positions`）。改行は行に含める。"""
    store = DocumentStore()
    state = store.update("file:///a.jin", GOOD)
    assert "".join(state.lines) == GOOD


def test_diagnostics_stop_at_the_first_failing_stage() -> None:
    """段階診断（JSON 構文 → スキーマ → 意味）。前段が通らなければ後段を出さない。"""
    store = DocumentStore()
    state = store.update("file:///a.jin", BROKEN)
    codes = {d.code for d in state.diagnostics}
    assert codes == {"JIN001"}, f"段 1 で止まっていない: {codes}"
