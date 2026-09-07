"""stdio トランスポートのラウンドトリップ（要件書 §9「LSP」/ design.yaml machine 1〜3）。

pytest-lsp がサーバを**サブプロセスとして起動**し、本物の JSON-RPC で話す。
ws 側は `test_ws_roundtrip.py` が同じアサーションを別トランスポートで回す。
"""

from __future__ import annotations

import json
import sys

import pytest
import pytest_lsp
from jin_core import canonical
from jin_core.model import JinFile
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import BROKEN, SCHEMA_ERROR, SEMANTIC_ERROR, as_plain, make_client, minimal

URI = "file:///workspace/a.jin"


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "jin_lsp"], client_factory=make_client
    ),
)
async def client(lsp_client: LanguageClient):
    # pytest-lsp の既定クライアントは `workspace/applyEdit` に応答しない（実測:
    # `pytest_lsp/client.py` の `default_feature` に無い）。`jin/applyOps` の
    # ラウンドトリップにはこれが要るので、テスト側で登録する。
    lsp_client.jin_applied_edits = []

    @lsp_client.feature(types.WORKSPACE_APPLY_EDIT)
    def _on_apply_edit(params: types.ApplyWorkspaceEditParams):
        lsp_client.jin_applied_edits.append(params)
        return types.ApplyWorkspaceEditResult(applied=True)

    # `LanguageClient` は initialize の結果を保持しない（実測）。テストが
    # サーバの capabilities を見られるように、ここで結果を持たせておく。
    lsp_client.jin_initialize_result = await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(
                workspace=types.WorkspaceClientCapabilities(apply_edit=True)
            ),
            root_uri="file:///workspace",
        )
    )
    yield
    await lsp_client.shutdown_session()


async def open_document(client: LanguageClient, text: str, uri: str = URI) -> None:
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(uri=uri, language_id="jin", version=1, text=text)
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)


@pytest.mark.asyncio
async def test_initialize_advertises_the_jin_capabilities(client: LanguageClient) -> None:
    """`initialize` が要件書 §6.2 の機能を宣言する。"""
    capabilities = client.jin_initialize_result.capabilities
    assert capabilities.completion_provider is not None
    assert capabilities.definition_provider
    assert capabilities.references_provider
    assert capabilities.hover_provider
    assert capabilities.document_symbol_provider
    assert capabilities.document_formatting_provider
    assert capabilities.rename_provider
    assert capabilities.code_action_provider


@pytest.mark.asyncio
async def test_did_open_publishes_no_diagnostics_for_a_valid_file(
    client: LanguageClient,
) -> None:
    await open_document(client, minimal())
    assert list(client.diagnostics[URI]) == []


@pytest.mark.asyncio
async def test_a_syntax_error_publishes_jin001_only(client: LanguageClient) -> None:
    """段階診断: 段 1 で落ちたら段 2 / 段 3 は出さない。"""
    await open_document(client, BROKEN)
    codes = {d.code for d in client.diagnostics[URI]}
    assert codes == {"JIN001"}


@pytest.mark.asyncio
async def test_a_schema_error_publishes_jin002_only(client: LanguageClient) -> None:
    await open_document(client, SCHEMA_ERROR)
    codes = {d.code for d in client.diagnostics[URI]}
    assert codes == {"JIN002"}


@pytest.mark.asyncio
async def test_a_semantic_error_reaches_stage_three(client: LanguageClient) -> None:
    await open_document(client, SEMANTIC_ERROR)
    codes = {d.code for d in client.diagnostics[URI]}
    assert codes and not (codes & {"JIN001", "JIN002"}), f"段 3 に届いていない: {codes}"


@pytest.mark.asyncio
async def test_diagnostics_carry_the_hint_in_data(client: LanguageClient) -> None:
    """要件書 §5 の `hint` を `data` に載せて運ぶ（LSP に標準フィールドが無い）。"""
    await open_document(client, SEMANTIC_ERROR)
    diagnostic = client.diagnostics[URI][0]
    assert diagnostic.source == "jin"
    assert "pointer" in diagnostic.data


@pytest.mark.asyncio
async def test_did_change_republishes_diagnostics(client: LanguageClient) -> None:
    """打鍵で診断が更新される（デバウンス後に届く）。"""
    await open_document(client, minimal())
    client.text_document_did_change(
        types.DidChangeTextDocumentParams(
            text_document=types.VersionedTextDocumentIdentifier(uri=URI, version=2),
            content_changes=[types.TextDocumentContentChangeWholeDocument(text=BROKEN)],
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert {d.code for d in client.diagnostics[URI]} == {"JIN001"}


@pytest.mark.asyncio
async def test_formatting_matches_jin_fmt_byte_for_byte(client: LanguageClient) -> None:
    """machine: formatting の出力が `jin fmt` の出力とバイト一致する。

    `jin fmt` は `jin_core.canonical.dumps` を呼ぶだけなので、ここでも同じ関数の
    出力と突き合わせる（CLI をサブプロセスで起動する横断テストは `tests/contract/`）。
    """
    messy = minimal().replace("  ", " ")  # インデントを崩す
    await open_document(client, messy)
    edits = await client.text_document_formatting_async(
        types.DocumentFormattingParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            options=types.FormattingOptions(tab_size=2, insert_spaces=True),
        )
    )
    assert edits is not None and len(edits) == 1
    expected = canonical.dumps(JinFile.model_validate(json.loads(messy)))
    assert edits[0].new_text == expected


@pytest.mark.asyncio
async def test_jin_model_returns_the_model_and_the_pointer_table(
    client: LanguageClient,
) -> None:
    """`jin/model`: モデル JSON + pointer→range 対応表（要件書 §6.3）。"""
    await open_document(client, minimal())
    result = as_plain(await client.protocol.send_request_async("jin/model", {"uri": URI}))
    assert result["model"]["root"] == "A"
    # 対応表は**配列**（JSON Pointer は `/` を含むので、オブジェクトのキーにすると
    # 往復しないクライアントがある。`jin_lsp.requests._range_to_json` の理由を参照）
    entries = {entry["pointer"]: entry for entry in result["pointers"]}
    assert "/circles/0/name" in entries
    entry = entries["/circles/0/name"]
    assert set(entry) == {"pointer", "start", "end"}
    assert set(entry["start"]) == {"line", "col"}
    assert [e["pointer"] for e in result["pointers"]] == sorted(entries), "順序が決定的でない"


@pytest.mark.asyncio
async def test_jin_render_svg_matches_the_renderer(client: LanguageClient) -> None:
    """`jin/renderSvg`: `jin_render.render` の出力とバイト一致する（唯一の入口）。"""
    from jin_render import render

    text = minimal()
    await open_document(client, text)
    result = as_plain(await client.protocol.send_request_async("jin/renderSvg", {"uri": URI}))
    assert result["svg"] == render(JinFile.model_validate(json.loads(text)))


@pytest.mark.asyncio
async def test_jin_ops_lists_the_nineteen_operations(client: LanguageClient) -> None:
    """`jin/ops`: 利用可能なオペレーション一覧（`docs/spec/ops.md` と同内容・19 件）。"""
    from jin_core.ops import OPERATIONS

    result = as_plain(await client.protocol.send_request_async("jin/ops", None))
    names = {op["name"] for op in result["operations"]}
    assert names == set(OPERATIONS)
    assert len(names) == 19


@pytest.mark.asyncio
async def test_jin_apply_ops_returns_the_new_model_and_the_inverses(
    client: LanguageClient,
) -> None:
    """`jin/applyOps`: モデルを更新し、新モデル・診断・逆オペレーションを返す。"""
    await open_document(client, minimal())
    result = as_plain(
        await client.protocol.send_request_async(
            "jin/applyOps",
            {
                "uri": URI,
                "ops": [{"op": "setDescription", "pointer": "/circles/0", "value": "説明"}],
            },
        )
    )
    assert result["model"]["circles"][0]["description"] == "説明"
    assert result["inverses"] == [{"op": "setDescription", "pointer": "/circles/0", "value": None}]
    assert result["diagnostics"] == []


@pytest.mark.asyncio
async def test_jin_apply_ops_sends_a_workspace_edit(client: LanguageClient) -> None:
    """差分は `workspace/applyEdit` でクライアントへ送る（要件書 §6.3）。"""
    applied = client.jin_applied_edits
    await open_document(client, minimal())
    await client.protocol.send_request_async(
        "jin/applyOps",
        {
            "uri": URI,
            "ops": [{"op": "setDescription", "pointer": "/circles/0", "value": "説明"}],
        },
    )
    assert applied, "workspace/applyEdit が送られていない"
    changes = applied[0].edit.changes
    assert changes is not None and URI in changes
    assert '"description": "説明"' in changes[URI][0].new_text


@pytest.mark.asyncio
async def test_jin_apply_ops_reports_failures_with_a_diagnostic_code(
    client: LanguageClient,
) -> None:
    """失敗は診断コードで理由を返す（`docs/spec/ops.md` §4）。**黙って握り潰さない**。"""
    await open_document(client, minimal())
    result = as_plain(
        await client.protocol.send_request_async(
            "jin/applyOps",
            {"uri": URI, "ops": [{"op": "noSuchOp", "pointer": "/circles/0"}]},
        )
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "JIN002"
    assert result["error"]["hint"]


@pytest.mark.asyncio
async def test_render_svg_falls_back_to_the_last_good_model(client: LanguageClient) -> None:
    """NFR-AVAIL-001: JSON 構文エラー中も直前の正常モデルで renderSvg が答える。"""
    from jin_render import render

    text = minimal()
    await open_document(client, text)
    client.text_document_did_change(
        types.DidChangeTextDocumentParams(
            text_document=types.VersionedTextDocumentIdentifier(uri=URI, version=2),
            content_changes=[types.TextDocumentContentChangeWholeDocument(text=BROKEN)],
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    result = as_plain(await client.protocol.send_request_async("jin/renderSvg", {"uri": URI}))
    assert result["stale"] is True, "last-good で答えたことをクライアントに伝えていない"
    assert result["svg"] == render(JinFile.model_validate(json.loads(text)))


@pytest.mark.asyncio
async def test_hover_falls_back_to_the_last_good_model(client: LanguageClient) -> None:
    """NFR-AVAIL-001: hover も同じ。"""
    await open_document(client, minimal())
    client.text_document_did_change(
        types.DidChangeTextDocumentParams(
            text_document=types.VersionedTextDocumentIdentifier(uri=URI, version=2),
            content_changes=[types.TextDocumentContentChangeWholeDocument(text=BROKEN)],
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    hover = await client.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=5, character=8),
        )
    )
    assert hover is not None, "壊れたテキストで hover が黙って None を返した"
