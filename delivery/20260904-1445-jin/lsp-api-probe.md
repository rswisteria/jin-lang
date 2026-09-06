# pygls 2.x / pytest-lsp 1.0 / lark 1.3 実測プローブ（親セッション実施・2026-09-04）

取得方法: `uv venv` 隔離環境へ `pygls==2.1.1` / `pytest-lsp==1.0.1` / `lark==1.3.1` を実インストールし、
`inspect` と実パースで確認。**学習知識ではなく実機の introspection 結果**。
pygls は 1.x → 2.x で API が変わっているため、**記憶で書くと確実に壊れる**。実装は本ファイルを一次証拠にすること。

## 1. pygls 2.1.1 — 最重要の差分

### `LanguageServer` の import パスが変わっている

```python
from pygls.lsp.server import LanguageServer  # 2.x（正）
# from pygls.server import LanguageServer     # 1.x の書き方。2.x には存在しない（ImportError）
```

`pygls.server` に居るのは `JsonRPCServer` / `JsonRPCProtocol` / `run` / `run_async` / `run_websocket` など低水準の要素のみ。
MRO は `LanguageServer → BaseLanguageServer → JsonRPCServer → object`。

### コンストラクタ（name / version は必須の位置引数）

```
LanguageServer.__init__(self, name: str, version: str,
                        text_document_sync_kind: types.TextDocumentSyncKind = TextDocumentSyncKind.Incremental,
                        notebook_document_sync: types.NotebookDocumentSyncOptions | None = None,
                        *args, **kwargs)
```

### 起動メソッド（3 トランスポートとも実在）

```
start_io(self, stdin: Optional[BinaryIO] = None, stdout: Optional[BinaryIO] = None)
start_ws(self, host: str, port: int) -> None
start_tcp(self, host: str, port: int) -> None
```

→ 要件書 §6.1 の「stdio と WebSocket の両トランスポート・同一サーバ」は `start_io()` / `start_ws(host, port)` で成立する。

### **WebSocket には extra が要る（見落とし注意）**

`importlib.metadata` で確認した pygls 2.1.1 の Requires-Dist:

```
attrs (>=24.3.0)
cattrs (>=23.1.2)
lsprotocol (==2025.0.0)
websockets (>=13.0) ; extra == "ws"
```

- 素の `pygls` には `websockets` が入らない（実測: `import websockets` → ModuleNotFoundError）。
- **依存宣言は `pygls[ws]` にすること**。`pygls` だけだと `jin lsp --ws PORT` が実行時に落ちる。
- `lsprotocol` は `==2025.0.0` に**厳密ピン**されている。lsprotocol を別途ピンし直さないこと。

### ハンドラ登録

```
JsonRPCServer.feature(self, feature_name: str, options: Any | None = None) -> Callable[[F], F]
JsonRPCServer.command(self, command_name: str) -> Callable[[F], F]
```

- 標準機能: `@server.feature(types.TEXT_DOCUMENT_DID_OPEN)` のように `lsprotocol.types` の定数を渡す。
- **独自リクエスト（`jin/model` / `jin/renderSvg` / `jin/applyOps` / `jin/ops`）も同じ `@server.feature("jin/renderSvg")` で登録できる**（`feature_name` は素の str を受ける）。`command` は `workspace/executeCommand` 用なので用途が違う。

### 送信系（実在を確認したメソッド）

- 診断: `server.text_document_publish_diagnostics(...)`
- 編集適用: `server.workspace_apply_edit(...)` / `workspace_apply_edit_async(...)` → 要件書 §6.3 `jin/applyOps` の `workspace/applyEdit` に使う
- ほか `window_show_message` / `window_log_message` / `progress` / `workspace` など

### 位置変換

`pygls.workspace` に `TextDocument` / `Workspace` / `PositionCodec` / `ServerTextPosition` / `ServerTextRange`。
`TextDocument` は `offset_at_position` / `position_at_offset` 系（`client_position_at_offset` / `server_position_at_offset`）と
`position_from_client_units` / `range_to_client_units` を持つ。
**LSP の Position は 0 始まりの `line` / `character`**（`lsprotocol.types.Position(line: int, character: int)`）。

`lsprotocol.types` に `Diagnostic` / `Position` / `Range` / `DiagnosticSeverity` / `TextEdit` / `WorkspaceEdit` /
`ApplyWorkspaceEditParams` と主要 method 定数（`TEXT_DOCUMENT_DID_OPEN` = `"textDocument/didOpen"`,
`WORKSPACE_APPLY_EDIT` = `"workspace/applyEdit"`, completion / formatting / rename / codeAction / definition /
references / hover / documentSymbol）がそろっていることを実測で確認済み。
`Diagnostic.__init__` の引数: `range` / `message` / `severity` / `code` / `code_description` / `source` / `tags` /
`related_information` / `data`。→ 要件書 §5 の診断 JSON の `hint` は標準フィールドに無いので、`data`（任意 JSON）に載せるか
`message` に含める設計判断が要る。

## 2. pytest-lsp 1.0.1 — **ws のラウンドトリップは素では張れない**

```
ClientServerConfig(server_command: list[str],
                   client_factory: Callable[[], JsonRPCClient] = make_test_lsp_client,
                   server_env: dict[str, str] | None = None)
pytest_lsp.fixture(fixture_function=None, *, config: ClientServerConfig, **kwargs)
```

`LanguageClient` MRO: `LanguageClient → LanguageClient → BaseLanguageClient → JsonRPCClient → object`。
公開名: `ClientServerConfig` / `LanguageClient` / `LanguageClientProtocol` / `LspSpecificationWarning` / `checks` /
`client` / `client_capabilities` / `fixture` / `make_test_lsp_client` / `plugin` / `protocol`。

**制約（設計 Phase 4 の machine 条件「stdio と WebSocket の両方で往復」に直接効く）**:
`ClientServerConfig` が受け取るのは `server_command`（サブプロセスを起動して stdio で話す）だけで、
**WebSocket 接続用のパラメータを持たない**。したがって ws 側の往復テストは pytest-lsp のフィクスチャでは張れず、
`websockets` クライアント + `pygls.client` / `JsonRPCClient` を使った**自前ハーネスを書く必要がある**。
「pytest-lsp が ws も見てくれる」前提で計画しないこと。ws 用ハーネスは Phase 4 の成果物として明示的に作る。

## 3. lark 1.3.1

- **JSON 文法は同梱されていない**（`lark/grammars/` の中身は `lark.lark` / `python.lark` / `common.lark` / `unicode.lark` のみ）。
  → `.jin` 用の JSON 文法は自前で書く（`%import common.ESCAPED_STRING` / `SIGNED_NUMBER` / `WS` は使える）。
- `Lark(..., propagate_positions=True, parser='lalr')` で `Tree.meta` に位置が入ることを実パースで確認:
  `meta.line` / `meta.column` / `meta.end_line` / `meta.end_column`、`Token` も同名属性を持つ。
  位置が無い枝では `meta.empty` が True になるので、**参照前に `meta.empty` を確認する**こと。
- **lark は 1 始まりの line / column**、**LSP は 0 始まりの line / character**。
  要件書 §5 の診断 JSON は `{"line": 12, "col": 40}` と書いているだけで基点を規定していない。
  **どちらの基点を採るかを実装時に決めて `decision-conformance.md` に根拠付きで記録すること**（値の捏造ではなく実装判断の明示）。
  `jin check --json` の出力と LSP Diagnostic の相互変換は 1 箇所に閉じ込める。

## 4. 実測から出る依存宣言（案・実装時に確定）

```
jin-core : pydantic>=2.13,<3 / lark>=1.3,<2
jin-lsp  : pygls[ws]>=2.1,<3      # ws extra を必ず付ける。lsprotocol は pygls が ==2025.0.0 でピン
jin-adk  : google-adk>=2.8,<3
dev      : pytest / syrupy>=6 / pytest-lsp>=1.0 / ruff
```
