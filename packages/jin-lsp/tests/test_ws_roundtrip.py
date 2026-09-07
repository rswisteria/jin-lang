"""WebSocket トランスポートのラウンドトリップ（要件書 §6.1 / design.yaml machine 1・3）。

**pytest-lsp の `ClientServerConfig` は ws を張れない**（`server_command` しか受け取らず、
WebSocket の接続先を持たない・`lsp-api-probe.md` §2 の実測）。
一方 `pytest_lsp.LanguageClient` は `pygls.client.JsonRPCClient` を継承しており
**`start_ws(host, port)` を持つ**（2026-09-07 実測）。そこでサーバは自分でサブプロセスとして
起動し、クライアントだけ pytest-lsp のものを使う。

ここで確かめるのは「**同一サーバ実装**が両トランスポートで同じ答えを返す」ことである
（FR-LSP-002）。個々の機能の中身は `test_stdio_roundtrip.py` が見る。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from jin_core.model import JinFile
from jin_lsp.server import TOKEN_PREFIX
from lsprotocol import types

from .conftest import BROKEN, as_plain, make_client, minimal

URI = "file:///workspace/a.jin"

#: サーバが待ち受けを始めるまで待つ上限（秒）。CI の遅いランナーでも足りる値。
STARTUP_TIMEOUT = 20.0

#: 切断の待ち上限（秒）。ここで詰まってもテスト全体を止めない。
SHUTDOWN_TIMEOUT = 15.0


def free_port() -> int:
    """空きポートを 1 つ取る。

    取ったポートを閉じてからサーバに渡すので、その隙間に別のプロセスが同じポートを
    掴む可能性は残る。テストの中で使うぶんには実務的に十分で、代わりに
    「サーバが実際に待ち受けたこと」を接続の成功で確かめる。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WsServer:
    """`python -m jin_lsp --ws PORT` をサブプロセスで起動して束ねる。"""

    def __init__(self, *, root: Path | None = None) -> None:
        self.port = free_port()
        self.root = root
        self.token: str | None = None
        command = [sys.executable, "-m", "jin_lsp", "--ws", str(self.port)]
        if root is not None:
            command += ["--root", str(root)]
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    async def wait_until_ready(self) -> None:
        """ポートが開くまで待つ。`--root` 付きなら stderr のトークン行も拾う。"""
        if self.root is not None:
            assert self.process.stderr is not None
            line = await asyncio.get_running_loop().run_in_executor(
                None, self.process.stderr.readline
            )
            assert line.startswith(TOKEN_PREFIX), f"トークン行が stderr に出ていない: {line!r}"
            self.token = line[len(TOKEN_PREFIX) :].strip()
        deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            except OSError:
                await asyncio.sleep(0.05)
                continue
            writer.close()
            await writer.wait_closed()
            del reader
            return
        raise AssertionError(f"サーバが {STARTUP_TIMEOUT} 秒で待ち受けを始めなかった")

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - 保険
            self.process.kill()
            self.process.wait(timeout=10)
        if self.process.stderr is not None:
            self.process.stderr.close()


async def connect(server: WsServer):
    """ws で繋いで `initialize` まで済ませたクライアントを返す。"""
    client = make_client()

    # pytest-lsp の既定クライアントは `workspace/applyEdit` に応答しない（実測）。
    # `jin/applyOps` はサーバからこのリクエストを打つので、登録しておかないと
    # `MethodNotFound` になる。stdio 側の fixture と同じ扱い。
    client.jin_applied_edits = []

    @client.feature(types.WORKSPACE_APPLY_EDIT)
    def _on_apply_edit(params: types.ApplyWorkspaceEditParams):
        client.jin_applied_edits.append(params)
        return types.ApplyWorkspaceEditResult(applied=True)

    await client.start_ws("127.0.0.1", server.port)
    await client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(
                workspace=types.WorkspaceClientCapabilities(apply_edit=True)
            ),
            root_uri="file:///workspace",
        )
    )
    return client


async def disconnect(client) -> None:
    """**`shutdown_session()` を先に呼ぶ**（呼ばないと `stop()` が返らない）。

    pygls 2.1.1 の `run_websocket` は `websocket.recv()` でブロックしており、
    `stop()` が立てる `stop_event` を見るのは**次のメッセージを受け取ったあと**である
    （2026-09-07 実測）。サーバに `shutdown` / `exit` を送って向こうから接続を
    閉じてもらえば `ConnectionClosed` でループを抜ける。
    `shutdown_session()` はサーバがエラー状態なら何もしないので、その場合に備えて
    `stop()` 側にも待ち時間の上限を置く。
    """
    with contextlib.suppress(TimeoutError, Exception):
        await asyncio.wait_for(client.shutdown_session(), timeout=SHUTDOWN_TIMEOUT)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(client.stop(), timeout=SHUTDOWN_TIMEOUT)


@pytest_asyncio.fixture
async def ws_client() -> AsyncIterator[object]:
    server = WsServer()
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            yield client
        finally:
            await disconnect(client)
    finally:
        server.stop()


async def open_document(client, text: str, uri: str = URI) -> None:
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(uri=uri, language_id="jin", version=1, text=text)
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)


@pytest.mark.asyncio
async def test_did_open_publishes_diagnostics_over_websocket(ws_client) -> None:
    """machine: initialize → didOpen → publishDiagnostics が **ws でも**通る。"""
    await open_document(ws_client, BROKEN)
    assert {d.code for d in ws_client.diagnostics[URI]} == {"JIN001"}


@pytest.mark.asyncio
async def test_the_four_custom_requests_round_trip_over_websocket(ws_client) -> None:
    """machine: `jin/model` / `jin/renderSvg` / `jin/applyOps` / `jin/ops` が ws でも往復する。"""
    from jin_render import render

    text = minimal()
    await open_document(ws_client, text)
    model = JinFile.model_validate(json.loads(text))

    result = as_plain(await ws_client.protocol.send_request_async("jin/model", {"uri": URI}))
    assert result["model"]["root"] == "A"

    result = as_plain(await ws_client.protocol.send_request_async("jin/renderSvg", {"uri": URI}))
    assert result["svg"] == render(model)

    result = as_plain(await ws_client.protocol.send_request_async("jin/ops", None))
    assert len(result["operations"]) == 19

    result = as_plain(
        await ws_client.protocol.send_request_async(
            "jin/applyOps",
            {
                "uri": URI,
                "ops": [{"op": "setDescription", "pointer": "/circles/0", "value": "説明"}],
            },
        )
    )
    assert result["ok"] is True
    assert result["model"]["circles"][0]["description"] == "説明"


@pytest.mark.asyncio
async def test_standard_features_round_trip_over_websocket(ws_client) -> None:
    """machine: 標準機能が ws でも往復する（同一サーバ実装であること）。"""
    await open_document(ws_client, minimal())
    symbols = await ws_client.text_document_document_symbol_async(
        types.DocumentSymbolParams(text_document=types.TextDocumentIdentifier(uri=URI))
    )
    assert symbols and symbols[0].name == "A"

    edits = await ws_client.text_document_formatting_async(
        types.DocumentFormattingParams(
            text_document=types.TextDocumentIdentifier(uri=URI),
            options=types.FormattingOptions(tab_size=2, insert_spaces=True),
        )
    )
    assert list(edits) == []  # 既に正準形


# --------------------------------------------------------------------------------------
# jin/open と jin/save（ADR-011・ws モードのエディタ専用）
# --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_open_and_save_are_refused_without_a_root() -> None:
    """`--root` を渡さずに起動したら、トークンの有無に関わらず**常に拒む**。"""
    server = WsServer()
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            with pytest.raises(Exception, match="無効"):
                await client.protocol.send_request_async(
                    "jin/open", {"uri": URI, "token": "なんでも"}
                )
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_open_reads_a_file_under_the_root(tmp_path: Path) -> None:
    path = tmp_path / "a.jin"
    path.write_text(minimal("Root"), encoding="utf-8")
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            result = as_plain(
                await client.protocol.send_request_async(
                    "jin/open", {"uri": path.as_uri(), "token": server.token}
                )
            )
            assert result["text"] == minimal("Root")
            assert result["diagnostics"] == []
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_save_writes_the_canonical_form(tmp_path: Path) -> None:
    """保存されるのは**正準形**（要件書 成功条件 5「エディタ保存と jin fmt がバイト一致」）。"""
    path = tmp_path / "a.jin"
    messy = minimal("Root").replace("  ", " ")
    path.write_text(messy, encoding="utf-8")
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            result = as_plain(
                await client.protocol.send_request_async(
                    "jin/save",
                    {"uri": path.as_uri(), "token": server.token, "text": messy},
                )
            )
            assert result["text"] == minimal("Root")
            assert path.read_text(encoding="utf-8") == minimal("Root")
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_a_wrong_token_is_refused(tmp_path: Path) -> None:
    """トークンが違えば読めない（same-origin が無い ws への防御）。"""
    (tmp_path / "a.jin").write_text(minimal("Root"), encoding="utf-8")
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            with pytest.raises(Exception, match="トークン"):
                await client.protocol.send_request_async(
                    "jin/open", {"uri": (tmp_path / "a.jin").as_uri(), "token": "にせもの"}
                )
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_a_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    """`--root` の外は読めない（`..` を含む URI も `resolve()` してから見る）。"""
    outside = tmp_path / "outside.jin"
    outside.write_text(minimal("Root"), encoding="utf-8")
    root = tmp_path / "inside"
    root.mkdir()
    server = WsServer(root=root)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            for uri in (outside.as_uri(), (root / ".." / "outside.jin").as_uri()):
                with pytest.raises(Exception, match="root"):
                    await client.protocol.send_request_async(
                        "jin/open", {"uri": uri, "token": server.token}
                    )
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_a_non_jin_suffix_is_refused(tmp_path: Path) -> None:
    """`.jin` 以外は触らない（`~/.bashrc` を書かせない）。"""
    other = tmp_path / "a.txt"
    other.write_text("x", encoding="utf-8")
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            with pytest.raises(Exception, match="以外"):
                await client.protocol.send_request_async(
                    "jin/open", {"uri": other.as_uri(), "token": server.token}
                )
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_save_refuses_a_syntax_error(tmp_path: Path) -> None:
    """壊れたテキストでファイルを潰さない。"""
    path = tmp_path / "a.jin"
    path.write_text(minimal("Root"), encoding="utf-8")
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            with pytest.raises(Exception, match="構文エラー"):
                await client.protocol.send_request_async(
                    "jin/save", {"uri": path.as_uri(), "token": server.token, "text": BROKEN}
                )
            assert path.read_text(encoding="utf-8") == minimal("Root"), "元のファイルが壊れた"
        finally:
            await disconnect(client)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_save_refuses_a_symlink_and_leaves_the_target_untouched(tmp_path: Path) -> None:
    """書き先が symlink なら拒み、その先の実体も書き換えない。

    **root の中に張られたリンクでも拒む。** 最初の実装は `Path.resolve()` の結果を
    そのまま書き先にしていたため、`link.jin` → `secret.jin` の保存で `secret.jin` が
    書き換わった（このテストで実際に踏んだ）。`--root` を指定した利用者が
    許可したのは「root の中の `.jin`」であって「リンクの向こう側」ではない。
    """
    secret = tmp_path / "secret.jin"
    secret.write_text(minimal("Secret"), encoding="utf-8")
    link = tmp_path / "link.jin"
    link.symlink_to(secret)
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        client = await connect(server)
        try:
            with pytest.raises(Exception, match="リンク"):
                await client.protocol.send_request_async(
                    "jin/save",
                    {"uri": link.as_uri(), "token": server.token, "text": minimal("Root")},
                )
        finally:
            await disconnect(client)
        assert secret.read_text(encoding="utf-8") == minimal("Secret"), (
            "symlink を辿って実体を書き換えた"
        )
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_the_server_survives_a_client_reconnect(tmp_path: Path) -> None:
    """**クライアントが切れてもサーバは終わらない**（Phase 5 で直した欠陥の再発検知）。

    pygls 2.1.1 の `LanguageServer.start_ws` は、1 本目の接続が閉じた直後に
    `self.shutdown()` を呼ぶ（`pygls.server` を実測）。それをそのまま使っていると
    **ブラウザのエディタはページを 1 回再読み込みしただけで死ぬ**。
    `JinLanguageServer.serve_ws` は接続ごとに `run_websocket` を回し、
    `stop_event` も接続ごとに作り直す（使い回すと 2 本目が受信ループに入らない）。

    ここでは **LSP の `shutdown` / `exit` を送らずに**ソケットだけ閉じる。
    ブラウザはページを離れるときに閉じるだけで、終了要求は出さないからである
    （`disconnect()` ヘルパは `shutdown_session()` を呼ぶので、この場面には使えない
    — `exit` を受けたサーバが終了するのは**正しい**挙動であって、直したい欠陥ではない）。

    3 回張るのは、2 本目だけ通って 3 本目で落ちる形（`stop_event` の共有）も
    同時に捕まえるためである。
    """
    import websockets

    target = tmp_path / "a.jin"
    target.write_text(minimal("Main"), encoding="utf-8")
    server = WsServer(root=tmp_path)
    try:
        await server.wait_until_ready()
        for attempt in range(3):
            async with websockets.connect(f"ws://127.0.0.1:{server.port}") as socket:
                await socket.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"processId": None, "rootUri": None, "capabilities": {}},
                        }
                    )
                )
                raw = await asyncio.wait_for(socket.recv(), timeout=STARTUP_TIMEOUT)
                answer = json.loads(raw)
                assert "result" in answer, f"{attempt + 1} 本目の initialize が失敗: {answer}"
    finally:
        server.stop()
