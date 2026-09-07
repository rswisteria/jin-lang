"""標準機能のラウンドトリップ（design.yaml machine 2 / 要件書 §6.2）。

> completion / definition / references / hover / documentSymbol / formatting /
> rename / codeAction が pytest-lsp で往復する

`formatting` は `test_stdio_roundtrip.py` が `jin fmt` との一致まで見る。ここでは
残りの機能が「**正しい中身**を返す」ことを見る（往復するだけなら空の応答でも通るので、
何を返したかまで確かめる）。
"""

from __future__ import annotations

import sys

import pytest
import pytest_lsp
from jin_core import canonical
from jin_core.model import JinFile
from jin_lsp.features.edits import APPLY_OPS_COMMAND, DEFAULT_LOOP_MAX
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import RICH_MODEL, make_client, minimal

URI = "file:///workspace/a.jin"


def rich_text() -> str:
    return canonical.dumps(JinFile.model_validate(RICH_MODEL))


def line_of(text: str, needle: str) -> int:
    """`needle` を含む最初の行の 0 始まり行番号。"""
    for index, line in enumerate(text.splitlines()):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} を含む行が無い")


def column_of(text: str, needle: str, inside: str) -> types.Position:
    """`needle` を含む行の、`inside` の中ほどを指す位置。"""
    index = line_of(text, needle)
    line = text.splitlines()[index]
    start = line.index(inside)
    return types.Position(line=index, character=start + max(1, len(inside) // 2))


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "jin_lsp"], client_factory=make_client
    ),
)
async def client(lsp_client: LanguageClient):
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


# ---- definition / references ---------------------------------------------------------
@pytest.mark.asyncio
async def test_definition_jumps_from_a_delegate_reference_to_the_circle(
    client: LanguageClient,
) -> None:
    """circle 参照 → 定義（要件書 §6.2 definition 行）。"""
    text = rich_text()
    await open_document(client, text)
    # `delegate` の中の "B"
    position = column_of(text, '"delegate"', '"delegate"')
    delegate_line = line_of(text, '"delegate"')
    location = await client.text_document_definition_async(
        types.DefinitionParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=delegate_line + 1, character=8),
        )
    )
    assert location is not None, "delegate の参照から定義へ跳べない"
    lines = text.splitlines()
    assert '"B"' in lines[location.range.start.line]
    del position


@pytest.mark.asyncio
async def test_definition_from_root_reaches_the_circle_name(client: LanguageClient) -> None:
    text = rich_text()
    await open_document(client, text)
    location = await client.text_document_definition_async(
        types.DefinitionParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=column_of(text, '"root"', '"A"'),
        )
    )
    assert location is not None
    assert '"A"' in text.splitlines()[location.range.start.line]


@pytest.mark.asyncio
async def test_references_finds_every_pointer_to_a_circle(client: LanguageClient) -> None:
    """circle `B` は `delegate[0]` と `tools[1].circle` から参照されている。"""
    text = rich_text()
    await open_document(client, text)
    # circle B の定義（`"name": "B"`）の上で references
    b_line = next(index for index, line in enumerate(text.splitlines()) if '"name": "B"' in line)
    locations = await client.text_document_references_async(
        types.ReferenceParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=b_line, character=15),
            context=types.ReferenceContext(include_declaration=False),
        )
    )
    assert locations is not None and len(locations) == 2, [
        text.splitlines()[loc.range.start.line] for loc in (locations or [])
    ]


# ---- hover ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hover_on_a_circle_names_the_adk_class(client: LanguageClient) -> None:
    """要素 → ADK クラス名と生成される引数（要件書 §6.2 hover 行）。"""
    text = rich_text()
    await open_document(client, text)
    hover = await client.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=column_of(text, '"name": "A"', '"A"'),
        )
    )
    assert hover is not None
    assert "LlmAgent" in hover.contents.value


@pytest.mark.asyncio
async def test_hover_on_a_summon_tool_names_agent_tool(client: LanguageClient) -> None:
    text = rich_text()
    await open_document(client, text)
    hover = await client.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=column_of(text, '"name": "summarize"', '"summarize"'),
        )
    )
    assert hover is not None
    assert "AgentTool" in hover.contents.value


@pytest.mark.asyncio
async def test_hover_on_the_rune_shows_the_whole_text(client: LanguageClient) -> None:
    """rune の全文（要件書 §6.2 hover 行）。"""
    text = rich_text()
    await open_document(client, text)
    hover = await client.text_document_hover_async(
        types.HoverParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=column_of(text, '"rune"', '"rune"'),
        )
    )
    assert hover is not None
    assert "{q} を調べる" in hover.contents.value


# ---- documentSymbol ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_document_symbol_nests_tools_and_state_under_the_circle(
    client: LanguageClient,
) -> None:
    """circle > tools / state / flow の階層（要件書 §6.2）。"""
    await open_document(client, rich_text())
    symbols = await client.text_document_document_symbol_async(
        types.DocumentSymbolParams(text_document=types.TextDocumentIdentifier(uri=URI))
    )
    assert symbols is not None
    names = [symbol.name for symbol in symbols]
    assert names == ["A", "B"]
    children = {child.name for child in symbols[0].children}
    assert {"search", "summarize", "q"} <= children


# ---- completion ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_completion_offers_circle_names_in_a_delegate_slot(
    client: LanguageClient,
) -> None:
    """参照名の補完（要件書 §6.2 completion 行）。"""
    text = rich_text()
    await open_document(client, text)
    delegate_line = line_of(text, '"delegate"')
    result = await client.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=delegate_line + 1, character=8),
        )
    )
    assert result is not None
    labels = {item.label for item in result.items}
    assert {"A", "B"} <= labels, labels


@pytest.mark.asyncio
async def test_completion_offers_enum_values_for_a_kind(client: LanguageClient) -> None:
    text = rich_text()
    await open_document(client, text)
    result = await client.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=column_of(text, '"kind": "tool"', '"tool"'),
        )
    )
    assert result is not None
    labels = {item.label for item in result.items}
    assert {"tool", "builtin", "summon"} <= labels, labels


@pytest.mark.asyncio
async def test_completion_offers_state_keys_after_a_brace_in_a_rune(
    client: LanguageClient,
) -> None:
    """rune 内 `{` の後で state key（要件書 §6.2 completion 行の最後）。"""
    text = rich_text()
    await open_document(client, text)
    rune_line = line_of(text, '"rune"')
    line = text.splitlines()[rune_line]
    result = await client.text_document_completion_async(
        types.CompletionParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=rune_line, character=line.index("{q}") + 1),
        )
    )
    assert result is not None
    assert "q" in {item.label for item in result.items}


# ---- rename --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rename_a_circle_follows_every_reference(client: LanguageClient) -> None:
    """circle / tool / state。参照を全て追随（要件書 §6.2 rename 行）。"""
    text = rich_text()
    await open_document(client, text)
    b_line = next(i for i, line in enumerate(text.splitlines()) if '"name": "B"' in line)
    edit = await client.text_document_rename_async(
        types.RenameParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=b_line, character=15),
            new_name="Bee",
        )
    )
    assert edit is not None and edit.changes is not None
    new_text = edit.changes[URI][0].new_text
    assert '"B"' not in new_text, "参照が追随していない"
    assert new_text.count("Bee") == 3, f"circle 名 + delegate + summon.circle の 3 箇所: {new_text}"


@pytest.mark.asyncio
async def test_rename_a_tool_follows_the_await_list(client: LanguageClient) -> None:
    text = rich_text()
    await open_document(client, text)
    edit = await client.text_document_rename_async(
        types.RenameParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=column_of(text, '"name": "search"', '"search"'),
            new_name="lookup",
        )
    )
    assert edit is not None and edit.changes is not None
    new_text = edit.changes[URI][0].new_text
    assert '"search"' not in new_text
    assert new_text.count("lookup") == 2, "boundary.await が追随していない"


@pytest.mark.asyncio
async def test_rename_to_an_existing_name_changes_nothing(client: LanguageClient) -> None:
    """名前の重複（JIN010）は当てない。**黙って壊れたモデルを書かない**。"""
    text = rich_text()
    await open_document(client, text)
    b_line = next(i for i, line in enumerate(text.splitlines()) if '"name": "B"' in line)
    edit = await client.text_document_rename_async(
        types.RenameParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            position=types.Position(line=b_line, character=15),
            new_name="A",
        )
    )
    assert edit is None


# ---- codeAction ----------------------------------------------------------------------
async def code_actions(client: LanguageClient, text: str) -> list:
    diagnostics = client.diagnostics[URI]
    return list(
        await client.text_document_code_action_async(
            types.CodeActionParams(
                text_document=types.TextDocumentIdentifier(uri=URI),
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=len(text.splitlines()), character=0),
                ),
                context=types.CodeActionContext(diagnostics=list(diagnostics)),
            )
        )
        or []
    )


@pytest.mark.asyncio
async def test_code_action_replaces_a_misspelled_circle_name(client: LanguageClient) -> None:
    """JIN011 → 名前置換（要件書 §6.2 codeAction 行）。"""
    text = minimal("A").replace('"root": "A"', '"root": "Aa"', 1)
    await open_document(client, text)
    actions = await code_actions(client, text)
    quickfixes = [a for a in actions if getattr(a, "kind", None) == types.CodeActionKind.QuickFix]
    assert quickfixes, actions
    assert "'A' に置き換える" in quickfixes[0].title
    changes = quickfixes[0].edit.changes
    assert '"root": "A"' in changes[URI][0].new_text


@pytest.mark.asyncio
async def test_code_action_adds_max_to_a_loop_without_a_bound(client: LanguageClient) -> None:
    """JIN030 → `max: 5` 追加（要件書 §6.2 / diagnostics.md §2）。"""
    text = canonical.dumps(
        JinFile.model_validate(
            {
                "$schema": RICH_MODEL["$schema"],
                "version": 1,
                "root": "Loop",
                "circles": [
                    {"name": "Loop", "flow": {"kind": "loop", "steps": ["Worker"]}},
                    {"name": "Worker", "core": "m"},
                ],
            }
        )
    )
    await open_document(client, text)
    assert {d.code for d in client.diagnostics[URI]} == {"JIN030"}
    actions = await code_actions(client, text)
    quickfixes = [a for a in actions if getattr(a, "kind", None) == types.CodeActionKind.QuickFix]
    assert quickfixes and f"max: {DEFAULT_LOOP_MAX}" in quickfixes[0].title
    assert f'"max": {DEFAULT_LOOP_MAX}' in quickfixes[0].edit.changes[URI][0].new_text


@pytest.mark.asyncio
async def test_code_action_extracts_the_overflowing_tools_into_a_sub_circle(
    client: LanguageClient,
) -> None:
    """JIN020 → 選択要素をサブ陣に抽出（要件書 §6.2）。"""
    tools = [{"name": f"t{index}", "kind": "tool", "ref": f"m:t{index}"} for index in range(14)]
    text = canonical.dumps(
        JinFile.model_validate(
            {
                "$schema": RICH_MODEL["$schema"],
                "version": 1,
                "root": "Big",
                "circles": [{"name": "Big", "core": "m", "tools": tools}],
            }
        )
    )
    await open_document(client, text)
    assert {d.code for d in client.diagnostics[URI]} == {"JIN020"}
    actions = await code_actions(client, text)
    quickfixes = [a for a in actions if getattr(a, "kind", None) == types.CodeActionKind.QuickFix]
    assert quickfixes, "JIN020 の抽出アクションが出ていない"
    new_text = quickfixes[0].edit.changes[URI][0].new_text
    assert '"name": "BigExtracted"' in new_text
    assert '"kind": "summon"' in new_text
    # 紋は 1 つも失われない（元に残る分 + 移した分）
    assert new_text.count('"kind": "tool"') == 14

    # **抽出後に JIN020 が解消していること。** ここを見ないと「動くが直らない」
    # コードアクションになる（`summon` を 1 つ足すぶん、残す数は 11 まで）。
    client.text_document_did_change(
        types.DidChangeTextDocumentParams(
            text_document=types.VersionedTextDocumentIdentifier(uri=URI, version=2),
            content_changes=[types.TextDocumentContentChangeWholeDocument(text=new_text)],
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert [d.code for d in client.diagnostics[URI]] == [], "抽出しても JIN020 が残っている"


@pytest.mark.asyncio
async def test_code_action_exposes_every_operation_as_a_command(
    client: LanguageClient,
) -> None:
    """§6.3 の全オペレーションを command として露出（要件書 §6.2 codeAction 行）。"""
    from jin_core.ops import OPERATIONS

    text = minimal()
    await open_document(client, text)
    actions = await code_actions(client, text)
    commands = [a for a in actions if getattr(a, "command", None) == APPLY_OPS_COMMAND]
    assert len(commands) == len(OPERATIONS) == 19
