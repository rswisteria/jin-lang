"""Jin の Language Server（要件書 §6）— プロトコル露出と、その組み立て。

**LSP 固有のロジックは位置変換とプロトコル露出だけに限定する**（要件書 §6 冒頭）。
診断は `jin_core.check.check_text`、正準形は `jin_core.canonical.dumps`、
SVG は `jin_render.render`、意味編集は `jin_core.ops.apply_ops` がそれぞれ**唯一の実装**であり、
ここに同じ規則を書き直さない。段階診断（構文 → スキーマ → 意味）も `check_text` の中にある。

トランスポート（要件書 §6.1）:

- `start_io()` … Claude Code プラグイン / VS Code
- `start_ws(host, port)` … ブラウザのエディタ。**同一サーバ実装**

hazard: stdio モードでは **stdout が JSON-RPC の通信路**である。このモジュールと
その依存に `print(...)` を置かない。ログは `jin_lsp.logs.configure` が stderr へ固定する
（DP-COMMON-14・人間確定）。

guard: main -> logs.configure
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from jin_core.diagnostics import CANONICAL_CODES
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from jin_lsp import SERVER_NAME, SERVER_VERSION, logs, positions, protocol, requests
from jin_lsp.features import completion, edits, navigation
from jin_lsp.session import DocumentState, DocumentStore

logger = logging.getLogger(__name__)

#: `didChange` の再診断を遅らせる秒数（DP-IMPL-JIN-P4-DEBOUNCE-01・2026-09-07 に toyota が確定）。
#: 要件書に無い値である。根拠は `delivery/20260904-1445-jin/check-text-benchmark.md`:
#: 現実的な 1000 行の診断は中央値 8.9 ms なので体感は即時のまま、敵対的なファイル
#: （1000 行以内で最悪 5.1 秒）の打鍵連打で計算が積み上がるのを防ぐ。
#: `didOpen` には**掛けない**（開いた瞬間の診断を遅らせる理由が無く、
#: NFR-PERF-001 の計測にデバウンス値が混ざる）。
DEBOUNCE_SECONDS = 0.15

#: `codeAction` が名乗る種別。`quickfix` は「診断を直す」、`refactor` は §6.3 の
#: オペレーション露出（要件書 §6.2 の codeAction 行「加えて §6.3 の全オペレーションを
#: command として露出」）。
CODE_ACTION_KINDS = [types.CodeActionKind.QuickFix, types.CodeActionKind.Refactor]


class JinLanguageServer(LanguageServer):
    """`DocumentStore`（last-good モデル 1 世代）とデバウンスを持つサーバ。

    pygls の `Workspace` はテキストの正本を持つが、**診断済みの結果**（モデル・
    pointer→range 対応表・last-good）はこちらが持つ（`jin_lsp.session`）。
    """

    def __init__(self, *, debounce: float = DEBOUNCE_SECONDS) -> None:
        # `converter_factory` を差し替えて、独自リクエストの params を**素の JSON**で受ける。
        # 既定のままだと `await` / `$schema` のようなキーが黙って `_0` に化ける
        # （`jin_lsp.protocol` の docstring に実測を書いた）。
        super().__init__(SERVER_NAME, SERVER_VERSION, converter_factory=protocol.jin_converter)
        self.documents = DocumentStore()
        self.debounce = debounce
        #: URI ごとの「これから走る診断」。**新しい打鍵が来たら古いものを捨てる**
        #: （check-text-benchmark.md の constraint「デバウンスし、古い要求をキャンセルする」）。
        self._pending: dict[str, asyncio.Task[None]] = {}
        #: 診断を走らせた回数。デバウンスが効いていることをテストで数えるために持つ。
        self.diagnostics_runs = 0

    # ---- 診断 -----------------------------------------------------------------

    def analyze_now(self, uri: str, text: str, version: int = 0) -> DocumentState:
        """デバウンスを挟まずに診断し、結果を publish する。"""
        state = self.documents.update(uri, text, version=version)
        self.diagnostics_runs += 1
        self.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                version=version or None,
                diagnostics=[
                    positions.to_lsp_diagnostic(state.lines, diagnostic)
                    for diagnostic in state.diagnostics
                ],
            )
        )
        return state

    def schedule_analysis(self, uri: str, text: str, version: int = 0) -> None:
        """`didChange` 用。`DEBOUNCE_SECONDS` 待ってから診断する。

        待っているあいだに次の打鍵が来たら、**前の待ちをキャンセルして**掛け直す。
        走り出した診断そのものは止められない（`check_text` は同期の CPU 仕事）ので、
        ここで担保するのは「打鍵ごとに計算が積み上がらない」ことである。
        敵対的なファイルの 1 件ぶん（最悪 5.1 秒）は残る
        （`check-text-benchmark.md` の「残存」・Issue #8 の人間判断）。
        """
        self.cancel_pending(uri)
        self._pending[uri] = asyncio.create_task(self._debounced(uri, text, version))

    def cancel_pending(self, uri: str) -> None:
        task = self._pending.pop(uri, None)
        if task is not None and not task.done():
            task.cancel()

    async def _debounced(self, uri: str, text: str, version: int) -> None:
        try:
            await asyncio.sleep(self.debounce)
        except asyncio.CancelledError:
            return
        self._pending.pop(uri, None)
        self.analyze_now(uri, text, version)

    # ---- ドキュメント ---------------------------------------------------------

    def state_of(self, uri: str) -> DocumentState | None:
        return self.documents.get(uri)


def create_server(*, debounce: float = DEBOUNCE_SECONDS) -> JinLanguageServer:
    """ハンドラを登録した サーバを作る。

    ファクトリにしてあるのは、テストが `debounce=0` の実体を直接組み立てられるように
    するためである（`start_io` / `start_ws` を経由せずにハンドラ関数を呼べる）。
    """
    server = JinLanguageServer(debounce=debounce)

    # ---- テキスト同期 ---------------------------------------------------------

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    def did_open(ls: JinLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
        """開いた瞬間は**デバウンスしない**（NFR-PERF-001 の計測にも効く）。"""
        document = params.text_document
        ls.analyze_now(document.uri, document.text, document.version)

    @server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
    def did_change(ls: JinLanguageServer, params: types.DidChangeTextDocumentParams) -> None:
        uri = params.text_document.uri
        text = ls.workspace.get_text_document(uri).source
        ls.schedule_analysis(uri, text, params.text_document.version or 0)

    @server.feature(types.TEXT_DOCUMENT_DID_SAVE)
    def did_save(ls: JinLanguageServer, params: types.DidSaveTextDocumentParams) -> None:
        """保存時は待たずに出す（要件書 §6.2「open / change / save で再計算」）。"""
        uri = params.text_document.uri
        ls.cancel_pending(uri)
        ls.analyze_now(uri, ls.workspace.get_text_document(uri).source)

    @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
    def did_close(ls: JinLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
        uri = params.text_document.uri
        ls.cancel_pending(uri)
        ls.documents.close(uri)
        # 閉じたドキュメントの診断は消す（クライアントに残り続けないように）。
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )

    # ---- 標準機能（要件書 §6.2）------------------------------------------------

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionOptions(trigger_characters=['"', ":", "{"]),
    )
    def completions(ls: JinLanguageServer, params: types.CompletionParams) -> types.CompletionList:
        return completion.complete(ls.state_of(params.text_document.uri), params.position)

    @server.feature(types.TEXT_DOCUMENT_DEFINITION)
    def definition(ls: JinLanguageServer, params: types.DefinitionParams) -> types.Location | None:
        return navigation.definition(
            ls.state_of(params.text_document.uri), params.text_document.uri, params.position
        )

    @server.feature(types.TEXT_DOCUMENT_REFERENCES)
    def references(ls: JinLanguageServer, params: types.ReferenceParams) -> list[types.Location]:
        return navigation.references(
            ls.state_of(params.text_document.uri), params.text_document.uri, params.position
        )

    @server.feature(types.TEXT_DOCUMENT_HOVER)
    def hover(ls: JinLanguageServer, params: types.HoverParams) -> types.Hover | None:
        return navigation.hover(ls.state_of(params.text_document.uri), params.position)

    @server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
    def document_symbol(
        ls: JinLanguageServer, params: types.DocumentSymbolParams
    ) -> list[types.DocumentSymbol]:
        return navigation.document_symbols(ls.state_of(params.text_document.uri))

    @server.feature(types.TEXT_DOCUMENT_FORMATTING)
    def formatting(
        ls: JinLanguageServer, params: types.DocumentFormattingParams
    ) -> list[types.TextEdit] | None:
        """正準形（`jin fmt` と同一）。

        `jin_core.canonical.dumps` を呼ぶだけなので、出力は `jin fmt` とバイト一致する
        （`tests/contract/test_lsp_contract.py` が CLI の出力と突き合わせる）。
        """
        return edits.format_document(ls.state_of(params.text_document.uri))

    @server.feature(types.TEXT_DOCUMENT_RENAME)
    def rename(ls: JinLanguageServer, params: types.RenameParams) -> types.WorkspaceEdit | None:
        return edits.rename(
            ls.state_of(params.text_document.uri),
            params.text_document.uri,
            params.position,
            params.new_name,
        )

    @server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
    def prepare_rename(
        ls: JinLanguageServer, params: types.PrepareRenameParams
    ) -> types.PrepareRenameResult | None:
        return edits.prepare_rename(ls.state_of(params.text_document.uri), params.position)

    @server.feature(
        types.TEXT_DOCUMENT_CODE_ACTION,
        types.CodeActionOptions(code_action_kinds=CODE_ACTION_KINDS),
    )
    def code_action(
        ls: JinLanguageServer, params: types.CodeActionParams
    ) -> list[types.CodeAction | types.Command]:
        return edits.code_actions(
            ls.state_of(params.text_document.uri), params.text_document.uri, params
        )

    # ---- 独自リクエスト（要件書 §6.3）------------------------------------------

    @server.feature("jin/model")
    def jin_model(ls: JinLanguageServer, params: Any) -> dict[str, Any]:
        uri = _uri_of(params)
        return requests.jin_model(ls.state_of(uri), uri)

    @server.feature("jin/renderSvg")
    def jin_render_svg(ls: JinLanguageServer, params: Any) -> dict[str, Any]:
        uri = _uri_of(params)
        return requests.jin_render_svg(
            ls.state_of(uri),
            uri,
            focus=_field(params, "focus"),
            trace=_field(params, "trace"),
            upto=_field(params, "upto"),
        )

    @server.feature("jin/ops")
    def jin_ops(ls: JinLanguageServer, params: Any) -> dict[str, Any]:
        return requests.jin_ops()

    @server.feature("jin/applyOps")
    async def jin_apply_ops(ls: JinLanguageServer, params: Any) -> dict[str, Any]:
        """オペレーションを当て、差分を `workspace/applyEdit` でクライアントへ送る。

        送るのは**全文 1 個の `TextEdit`** である。正準形は要素の順序も入れ替えるので
        最小差分を作っても行単位では散らばり、エディタ側の適用結果は同じになる。
        1 個にしておけば「サーバが作った正準形」と「クライアントに残るテキスト」が
        ずれる余地が無い（要件書 成功条件 5 のバイト同一性）。
        """
        uri = _uri_of(params)
        state = ls.state_of(uri)
        result = requests.jin_apply_ops(state, uri, _field(params, "ops") or [])
        if not result.get("ok"):
            return result
        text = result["text"]
        assert state is not None
        if _client_applies_edits(ls):
            await ls.workspace_apply_edit_async(
                types.ApplyWorkspaceEditParams(
                    label="jin/applyOps",
                    edit=types.WorkspaceEdit(
                        changes={uri: [edits.whole_document_edit(state.lines, text)]}
                    ),
                )
            )
            result["applied"] = True
        else:
            # `workspace/applyEdit` を受けられないクライアントに送るとリクエストが
            # `MethodNotFound` で失敗し、**オペレーションは当たったのにテキストが
            # 更新されない**という食い違いだけが残る。送らずに、当てるべきテキストを
            # `text` として返し、`applied: false` で「自分で当ててくれ」と伝える
            # （NFR-FAIL-001「黙って落とさない」）。
            result["applied"] = False
        # クライアントが編集を当てたあとの診断を、こちらの記憶にも反映する。
        new_state = ls.analyze_now(uri, text, state.version)
        result["diagnostics"] = [diagnostic.to_json_dict() for diagnostic in new_state.diagnostics]
        return result

    return server


def _client_applies_edits(server: JinLanguageServer) -> bool:
    """クライアントが `workspace/applyEdit` を受けられるか（`initialize` の宣言を見る）。

    宣言が無いクライアントには送らない。pytest-lsp の既定クライアントも、
    ブラウザの素の WebSocket クライアントも、この機能を実装しているとは限らない。
    """
    workspace = getattr(server.client_capabilities, "workspace", None)
    return bool(getattr(workspace, "apply_edit", False))


def _field(params: Any, name: str) -> Any:
    """LSP の独自リクエストの引数は素の dict でも属性つきオブジェクトでも届く。

    `lsprotocol` は未知のメソッドの `params` を変換しないので dict のまま来るが、
    クライアントによっては属性で持つ型を寄越す。どちらでも読めるようにする
    （**黙って `None` にしない**。読めない形なら `AttributeError` ではなく `None`）。
    """
    if isinstance(params, dict):
        return params.get(name)
    return getattr(params, name, None)


def _uri_of(params: Any) -> str:
    uri = _field(params, "uri")
    if not isinstance(uri, str) or not uri:
        raise requests.RequestError(
            "JIN002",
            "uri を文字列で渡してください",
            ' 例: {"uri": "file:///path/to/a.jin"}',
        )
    return uri


def main(argv: list[str] | None = None) -> None:
    """`python -m jin_lsp` と `jin lsp` の共通の入口。

    guard: main -> logs.configure
    """
    parser = argparse.ArgumentParser(prog="jin-lsp", description="Jin の Language Server")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--stdio", action="store_true", help="stdio で待ち受ける（既定）")
    transport.add_argument(
        "--ws", type=int, metavar="PORT", help="WebSocket で待ち受ける（ブラウザのエディタ用）"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="--ws のときの待ち受けアドレス（既定: 127.0.0.1）"
    )
    parser.add_argument("--verbose", action="store_true", help="ログを詳細にする（stderr）")
    args = parser.parse_args(argv)

    logs.configure(logging.DEBUG if args.verbose else logging.WARNING)
    server = create_server()
    if args.ws is not None:
        server.start_ws(args.host, args.ws)
    else:
        server.start_io()


#: 診断コードの一覧（`codeAction` が自分の対象コードを名乗るのに使う）。
KNOWN_CODES = frozenset(CANONICAL_CODES)

__all__ = [
    "CODE_ACTION_KINDS",
    "DEBOUNCE_SECONDS",
    "KNOWN_CODES",
    "JinLanguageServer",
    "create_server",
    "main",
]
