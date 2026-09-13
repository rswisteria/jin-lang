"""Jin v2（`version: 2`）のドキュメントを LSP がどこまで扱うか（Phase 3）。

- 診断 / `jin/model` / `jin/renderSvg`（`focus` に `陣名/手順名` を許す）/ formatting は v2 で答える
- hover / completion / documentSymbol / rename / codeAction / `jin/applyOps` は v1 だけ（v2 は Phase 5）。
  v2 のドキュメントでは「モデル無し」と同じ振る舞い（None / 空 / JIN002）になり、**落ちない**
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jin_core.v2.model import JinFileV2
from jin_lsp import requests
from jin_lsp.features import completion, edits, navigation
from jin_lsp.session import DocumentStore
from lsprotocol import types

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = (REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin").read_text(encoding="utf-8")
URI = "file:///paddle.jin"


@pytest.fixture
def state():
    store = DocumentStore()
    return store.update(URI, PADDLE)


def test_a_v2_document_keeps_its_model_and_has_no_v1_model(state) -> None:
    assert isinstance(state.model, JinFileV2)
    assert state.model_v1 is None
    assert state.model_v1_for_display is None
    assert isinstance(state.model_for_display, JinFileV2)
    assert state.diagnostics == []


def test_render_svg_answers_for_v2_with_a_rite_focus(state) -> None:
    result = requests.jin_render_svg(state, URI)
    assert result["svg"].startswith("<svg") and result["stale"] is False
    assert 'data-jin-kind="stage"' in result["svg"]
    rite = requests.jin_render_svg(state, URI, focus="Play/step")
    assert 'data-jin-kind="step-edge"' in rite["svg"]
    with pytest.raises(requests.RequestError) as caught:
        requests.jin_render_svg(state, URI, focus="Play/nope")
    assert caught.value.code == "JIN002"


def test_render_svg_accepts_seq_zero_traces_for_v2(state) -> None:
    rows = [{"seq": 0, "pointer": "/circles/1"}, {"seq": 1, "pointer": "/stage"}]
    result = requests.jin_render_svg(state, URI, focus="Play", trace=rows, upto=0)
    assert 'data-jin-fired="1"' in result["svg"]


def test_jin_model_returns_the_v2_model(state) -> None:
    result = requests.jin_model(state, URI)
    assert result["model"]["version"] == 2
    assert any(p["pointer"] == "/stage/width" for p in result["pointers"])


def test_apply_ops_is_refused_for_v2_until_phase_5(state) -> None:
    with pytest.raises(requests.RequestError) as caught:
        requests.jin_apply_ops(state, URI, [{"op": "setRoot", "pointer": "", "value": "Play"}])
    assert caught.value.code == "JIN002"
    assert "version: 2" in caught.value.message


def test_formatting_still_works_for_v2(state) -> None:
    assert edits.format_document(state) == []  # 既に正準形


def test_v1_only_features_answer_empty_for_v2_without_raising(state) -> None:
    position = types.Position(line=2, character=5)
    assert navigation.hover(state, position) is None
    assert navigation.definition(state, URI, position) is None
    assert navigation.references(state, URI, position) == []
    assert navigation.document_symbols(state) == []
    assert completion.complete(state, position).items == []
    assert edits.prepare_rename(state, position) is None
    assert edits.rename(state, URI, position, "X") is None
    params = types.CodeActionParams(
        text_document=types.TextDocumentIdentifier(uri=URI),
        range=types.Range(position, position),
        context=types.CodeActionContext(diagnostics=[]),
    )
    assert edits.code_actions(state, URI, params) == []
