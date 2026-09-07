"""`jin/applyOps` の 19 オペレーション往復（design.yaml machine 4）。

> jin/applyOps の各オペレーション（19 種）について
> applyOps → 再パース → 期待モデル と 逆オペレーションで元に戻る が通る

`jin_core` 側の `test_ops.py` が同じことを**関数呼び出しで**確かめている。ここで見るのは
**LSP のプロトコル越しでも同じ結果になる**ことである（引数の JSON 化・逆オペレーションの
プロトコル露出・正準形テキストの往復が挟まっても壊れないこと）。

要件書 §6.3 の「undo/redo はクライアント側がオペレーションの逆を保持する」が成り立つには、
サーバが返した `inverses` を**そのまま送り返せば**元に戻る必要がある。
"""

from __future__ import annotations

import json
import sys

import pytest
import pytest_lsp
from jin_core import canonical
from jin_core.model import JinFile
from jin_core.ops import OPERATIONS
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import OPERATION_CASES, RICH_MODEL, as_plain, make_client

URI = "file:///workspace/rich.jin"


def rich_text() -> str:
    """`RICH_MODEL` の正準形テキスト。"""
    return canonical.dumps(JinFile.model_validate(RICH_MODEL))


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "jin_lsp"], client_factory=make_client
    ),
)
async def client(lsp_client: LanguageClient):
    lsp_client.jin_applied_edits = []

    @lsp_client.feature(types.WORKSPACE_APPLY_EDIT)
    def _on_apply_edit(params: types.ApplyWorkspaceEditParams):
        lsp_client.jin_applied_edits.append(params)
        return types.ApplyWorkspaceEditResult(applied=True)

    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(
                workspace=types.WorkspaceClientCapabilities(apply_edit=True)
            )
        )
    )
    yield
    await lsp_client.shutdown_session()


async def open_document(client: LanguageClient, text: str) -> None:
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(uri=URI, language_id="jin", version=1, text=text)
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)


async def apply(client: LanguageClient, ops: list[dict]) -> dict:
    result = as_plain(
        await client.protocol.send_request_async("jin/applyOps", {"uri": URI, "ops": ops})
    )
    assert isinstance(result, dict)
    return result


def test_the_case_table_covers_every_operation() -> None:
    """ケース表が 19 件を**過不足なく**覆う。1 つ書き忘れたら落ちる。"""
    assert {case["op"] for case in OPERATION_CASES} == set(OPERATIONS)
    assert len(OPERATION_CASES) == 19


@pytest.mark.asyncio
@pytest.mark.parametrize("case", OPERATION_CASES, ids=lambda case: str(case["op"]))
async def test_apply_then_invert_restores_the_canonical_text(
    client: LanguageClient, case: dict
) -> None:
    """順オペレーション → 逆オペレーションで**元の正準形テキストへバイト単位で戻る**。

    配列要素の位置も、順オペレーションが副次的に作った入れ物（`boundary`）も戻ること
    （`docs/spec/ops.md` §1 の最後の項・§2.1 の復元条件）。
    """
    original = rich_text()
    await open_document(client, original)

    forward = await apply(client, [case])
    assert forward["ok"] is True, forward
    changed = forward["text"]
    assert changed != original or case["op"] == "moveTool", (
        f"{case['op']} が何も変えていない（ケースが弱い）"
    )

    # サーバが返した逆オペレーションを**そのまま**送り返す（undo の実際の手順）。
    backward = await apply(client, forward["inverses"])
    assert backward["ok"] is True, backward
    assert backward["text"] == original, f"{case['op']} の逆オペレーションで元に戻らない"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", OPERATION_CASES, ids=lambda case: str(case["op"]))
async def test_apply_then_reparse_matches_the_model_in_the_response(
    client: LanguageClient, case: dict
) -> None:
    """応答の `model` が、応答の `text` を**再パースした**モデルと一致する。

    サーバは新モデルとテキストの両方を返す。片方だけ正しくても、エディタ側は
    「表示しているモデル」と「ファイルの中身」が食い違ったまま気づけない。
    """
    await open_document(client, rich_text())
    result = await apply(client, [case])
    assert result["ok"] is True, result
    reparsed = JinFile.model_validate(json.loads(result["text"]))
    assert result["model"] == reparsed.model_dump(by_alias=True, mode="json")


@pytest.mark.asyncio
async def test_a_failing_operation_in_the_middle_applies_nothing(
    client: LanguageClient,
) -> None:
    """1 つでも失敗したら**何も適用しない**（`docs/spec/ops.md` §6 の原子性）。"""
    original = rich_text()
    await open_document(client, original)
    result = await apply(
        client,
        [
            {"op": "setDescription", "pointer": "/circles/0", "value": "先に成功する方"},
            {"op": "removeTool", "pointer": "/circles/0/tools/99"},
        ],
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "JIN002"
    # モデルが変わっていないこと（次の applyOps が元のテキストから始まる）
    after = await apply(client, [{"op": "setRoot", "pointer": "", "value": "B"}])
    assert '"description": "説明"' in after["text"], "失敗したオペレーションが部分適用された"


@pytest.mark.asyncio
async def test_the_workspace_edit_carries_the_same_text_as_the_response(
    client: LanguageClient,
) -> None:
    """`workspace/applyEdit` で送る差分と、応答の `text` が同じであること。

    ずれると「クライアントのバッファ」と「サーバのモデル」が分かれる。
    """
    await open_document(client, rich_text())
    client.jin_applied_edits.clear()
    result = await apply(
        client, [{"op": "setDescription", "pointer": "/circles/0", "value": "同じであること"}]
    )
    assert client.jin_applied_edits, "workspace/applyEdit が送られていない"
    changes = client.jin_applied_edits[-1].edit.changes
    assert changes is not None
    assert changes[URI][0].new_text == result["text"]
