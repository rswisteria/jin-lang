"""Jin v2 の hover / completion / `jin/applyOps` が**実際のプロトコル**（stdio・pytest-lsp）で往復する。

`test_v2_documents.py` は `jin_lsp.requests` / `features` を直接呼ぶ。ここでは
`python -m jin_lsp` を別プロセスで起こし、`textDocument/hover` / `textDocument/completion` /
`jin/applyOps` を LSP として投げる（`jin_converter` を通した素の JSON で受ける）。
ブラウザの式エディタが送るのと同じ「式のリテラルの先頭位置」で completion を求める。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_lsp
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import as_plain, make_client

REPO_ROOT = Path(__file__).resolve().parents[3]
PADDLE = (REPO_ROOT / "examples-v2" / "paddle" / "paddle.jin").read_text(encoding="utf-8")
URI = "file:///workspace/paddle.jin"


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "jin_lsp"], client_factory=make_client
    ),
)
async def client(lsp_client: LanguageClient):
    await lsp_client.initialize_session(
        types.InitializeParams(capabilities=types.ClientCapabilities())
    )
    yield
    await lsp_client.shutdown_session()


async def open_paddle(client: LanguageClient) -> None:
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(uri=URI, language_id="jin", version=1, text=PADDLE)
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)


def position_of(needle: str, inside: str, offset: int = 1) -> types.Position:
    for index, line in enumerate(PADDLE.splitlines()):
        if needle in line:
            return types.Position(line=index, character=line.index(inside) + offset)
    raise AssertionError(needle)


@pytest.mark.asyncio
async def test_hover_and_completion_answer_for_v2_over_the_protocol(
    client: LanguageClient,
) -> None:
    await open_paddle(client)
    hover = await client.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=position_of('"name": "score"', '"score"'),
        )
    )
    assert hover is not None and "**公開**" in hover.contents.value

    result = await client.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=position_of('"expr": "ball.x + ball.vx * dt"', '"ball.x'),
        )
    )
    assert result is not None
    labels = [item.label for item in result.items]
    assert labels[:2] == ["dt", "ball"] and "input.key" in labels and "abs" in labels


@pytest.mark.asyncio
async def test_apply_ops_for_v2_returns_jil_and_updates_the_diagnostics(
    client: LanguageClient,
) -> None:
    await open_paddle(client)
    result = as_plain(
        await client.protocol.send_request_async(
            "jin/applyOps",
            {
                "uri": URI,
                "ops": [
                    {
                        "op": "addStep",
                        "pointer": "/circles/1/rites/0/steps",
                        "value": {"do": "set", "target": "score", "expr": "nope"},
                    }
                ],
            },
        )
    )
    assert isinstance(result, dict)
    assert result["ok"] is True
    # `workspace/applyEdit` を宣言していないクライアントには送らず、`text` で返す
    assert result["applied"] is False and result["text"].startswith("{\n")
    # 適用後の診断（JIN203: nope は未定義）が応答に載り、JIL は作れない
    codes = {d["code"] for d in result["diagnostics"]}
    assert "JIN203" in codes
    assert result["jil"] is None and "JIN203" in result["jilError"]
    # サーバの記憶も更新されている（続けて completion を求めると足したステップが見える）
    model = as_plain(await client.protocol.send_request_async("jin/model", {"uri": URI}))
    assert isinstance(model, dict)
    assert model["model"]["circles"][1]["rites"][0]["steps"][-1]["target"] == "score"
