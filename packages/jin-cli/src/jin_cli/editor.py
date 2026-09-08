"""`jin editor` — ビルド済みエディタを配信し、LSP(ws) を起動する（要件書 §7.3）。

**エディタ単体のサーバは持たない**（FR-EDITOR-004 / DP-COMMON-18 案 A）。ここがするのは
次の 3 つだけである:

1. `apps/editor/dist` の静的ファイルを 127.0.0.1 で配る
2. 同一プロセスで `jin lsp --ws --root <対象ファイルの親>` 相当を起動する
3. ブラウザを開く（`--no-browser` で抑止できる。Playwright と CI はこちらを使う）

**危険性**: これは `jin lsp --ws --root` と同じ口を、ユーザーが `--root` を明示せずに
開くことを意味する。WebSocket には same-origin 制限が無いので、ブラウザで開いている
任意のページが `ws://127.0.0.1:<port>` へ繋いでリクエストを打てる。`jin/open` /
`jin/save` は起動トークンの一致を要求し、対象ファイルの**親ディレクトリ配下の `.jin`**
に限られ、symlink への書き込みは拒む（`docs/spec/ops.md` §5.1 の 4 段）。それでも
**信頼しないディレクトリの `.jin` を `jin editor` で開かない**こと。

トークンは URL の**フラグメント**（`#token=...`）で渡す。フラグメントは HTTP 要求にも
`Referer` にも載らないので、ここで動かす静的サーバのアクセスログにも現れない。
残存: ブラウザの履歴には残り、同じページの JS からは読める。
"""

from __future__ import annotations

import secrets
import socket
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from jin_lsp import fileio
from jin_lsp.server import TOKEN_PREFIX, create_server

from jin_cli import runserver
from jin_cli.runserver import RunRejected, RunSlot

#: `--no-browser` のときに URL を stderr へ出す前置き。Playwright はこれを目印に読む。
URL_PREFIX = "jin editor url: "

#: 既定の dist の場所（リポジトリのレイアウト）。パッケージには同梱しない。
_DIST_FROM_REPO = ("apps", "editor", "dist")


class EditorError(Exception):
    """起動できない理由。CLI が 1 行で出して exit 1 にする。"""


@dataclass(frozen=True, slots=True)
class EditorAddress:
    http_port: int
    ws_port: int
    url: str


#: `POST /run` の body の上限（バイト）。prompt しか入らないので十分に小さくてよい。
MAX_RUN_BODY = 64 * 1024


class RunEndpoint:
    """`POST /run` が知っておくこと（Issue #34・spec §4）。

    **対象ファイルはここに固定する。** クライアントは実行するパスを指定できない。
    `origin` は待ち受けポートが決まってから `serve` が設定する（起動前は `None`）。
    """

    def __init__(self, target: Path, token: str) -> None:
        self.target = target
        self.token = token
        self.origin: str | None = None
        self.slot = RunSlot()

    def authorize(self, origin: str | None, token: str | None) -> bool:
        """`Origin` とトークンを見る。**どちらも合わなければ実行しない。**

        `Origin` が無い要求（curl など）は**通す**。ブラウザからの他オリジンの
        `fetch` には必ず `Origin` が付くので、ここで見るのは「別のページからの
        なりすまし」だけであり、端末から自分で叩く道を塞ぐ意味は無い。
        なりすましの本命の防御はカスタムヘッダ（トークン）が強制する preflight であり、
        `Origin` 検査はその上乗せである（spec §3.2）。

        guard: authorize -> secrets.compare_digest
        """
        if origin is not None and origin != self.origin:
            return False
        if token is None:
            return False
        return secrets.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))


def default_dist(start: Path | None = None) -> Path | None:
    """`apps/editor/dist` をリポジトリのレイアウトから探す。

    見つからなければ `None`。**探索結果を推測で埋めない**（無いなら無いと言う）。
    """
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        candidate = parent.joinpath(*_DIST_FROM_REPO)
        if candidate.is_dir():
            return candidate
    return None


def free_port(host: str) -> int:
    """空きポートを 1 つ borrow する。

    pygls 2.1.1 の `start_ws(host, port)` は `websockets` のサーバを内部で作り、
    **実際に bind したポートを返さない**（`pygls.server` を実測）。`port=0` を渡すと
    ポートが分からないので、こちらで開けて閉じた番号を渡す。
    **残存**: 閉じてから `start_ws` が bind するまでの窓で他プロセスに取られうる。
    その場合は `OSError` で落ちる（黙って別のポートへ移らない）。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def build_url(http_port: int, ws_port: int, file: Path, token: str, host: str) -> str:
    """エディタを開く URL。**トークンはフラグメントに置く**（要求にも Referer にも載らない）。"""
    uri = file.resolve().as_uri()
    query = f"ws=ws://{host}:{ws_port}&uri={quote(uri, safe='')}"
    return f"http://{host}:{http_port}/?{query}#token={quote(token, safe='')}"


def editor_root(target: Path) -> Path:
    """`jin/open` / `jin/save` が触れてよい範囲。**対象ファイルの親ディレクトリだけ**。

    ここを広げると、ブラウザで開いている任意のページが `ws://127.0.0.1:<port>` へ繋いで
    （トークンを知っていれば）より広い範囲の `.jin` を読み書きできるようになる。
    """
    return target.parent


def prepare(file: Path, dist: Path | None = None) -> tuple[Path, Path]:
    """対象ファイルと dist を検証して返す。**ここは待ち受けを開かない。**

    `serve` から検証だけを切り出してあるのは、テストが安全に呼べるようにするためである
    （`serve` は最後にブロックするので、入口の拒否を `serve` 経由で試すと、
    拒否が壊れた瞬間にテストがハングして「失敗」ではなく「無反応」になる）。
    """
    target = file.resolve()
    if target.suffix != ".jin":
        raise EditorError(f"`.jin` ファイルを指定してください: {file}")
    if not target.is_file():
        raise EditorError(f"ファイルがありません: {file}")
    root = dist if dist is not None else default_dist()
    if root is None:
        raise EditorError(
            "ビルド済みのエディタが見つかりません"
            "（apps/editor で `pnpm install && pnpm build` を実行するか --dist で場所を指定してください）"
        )
    if not (root / "index.html").is_file():
        raise EditorError(f"index.html がありません: {root}")
    return target, root


def serve(
    file: Path,
    *,
    dist: Path | None = None,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    announce: Callable[[str], None] | None = None,
) -> None:
    """静的配信 + LSP(ws) を起動して**ブロックする**。

    hazard: serve -> webbrowser.open
    guard: serve -> fileio.FileAccess.create
    """
    target, root = prepare(file, dist)

    # `jin/open` / `jin/save` が触れてよいのは**対象ファイルの親ディレクトリ**だけ。
    files = fileio.FileAccess.create(editor_root(target))
    server = create_server(files=files)

    # 実行の口（Issue #34）。**トークンは `jin/open` / `jin/save` と同じものを使う。**
    # 別に発行しても守るものは変わらず、URL のフラグメントに 2 つ載せる分だけ漏れ口が増える。
    endpoint = RunEndpoint(target=target, token=files.token)
    httpd = _static_server(host, root, endpoint)
    http_port = int(httpd.server_address[1])
    # `Origin` の期待値はポートが決まってからでないと書けない。
    endpoint.origin = f"http://{host}:{http_port}"
    ws_port = free_port(host)
    address = EditorAddress(
        http_port=http_port,
        ws_port=ws_port,
        url=build_url(http_port, ws_port, target, files.token, host),
    )
    thread = threading.Thread(target=httpd.serve_forever, name="jin-editor-http", daemon=True)
    thread.start()

    if announce is not None:
        # **stdout ではなく stderr へ**（`jin lsp` と同じ規律・DP-COMMON-14）。
        # トークンと URL はログであって、パイプで繋ぐ出力ではない。
        announce(f"{TOKEN_PREFIX}{files.token}")
        announce(f"{URL_PREFIX}{address.url}")
    if open_browser:
        webbrowser.open(address.url)
    try:
        # pygls の `start_ws` ではなく `serve_ws`。前者は 1 本目の接続が閉じた直後に
        # `shutdown()` を呼ぶので、**ページを再読み込みしただけでエディタが死ぬ**。
        server.serve_ws(host, address.ws_port)
    finally:
        # **走っている実行を残さない**（Issue #32 と同じ規律）。静的サーバを止める前に
        # 子を終わらせる。順序が逆だと、SSE を書いているスレッドが閉じた socket へ
        # 書き込んで例外を出す。
        endpoint.slot.terminate()
        httpd.shutdown()
        httpd.server_close()


class _StaticHandler(SimpleHTTPRequestHandler):
    """`HTTP/1.1` で応答する静的ハンドラ。

    既定の `BaseHTTPRequestHandler.protocol_version` は **HTTP/1.0** で、応答のたびに
    接続を閉じる。ブラウザが張りっぱなしのソケットを再利用しようとすると
    `ERR_CONNECTION_RESET` になる（Playwright の 2 本目のページ読み込みで実測）。
    `SimpleHTTPRequestHandler` は `Content-Length` を必ず付けるので HTTP/1.1 に上げてよい。
    """

    protocol_version = "HTTP/1.1"

    def __init__(
        self, *args: object, endpoint: RunEndpoint | None = None, **kwargs: object
    ) -> None:
        # **`super().__init__` の前に設定する。** `BaseHTTPRequestHandler.__init__` は
        # その場でリクエストを処理する（`handle()` を呼ぶ）ので、あとから代入しても間に合わない。
        self._endpoint = endpoint
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def log_message(self, format: str, *args: object) -> None:
        """アクセスログを**捨てる**。

        既定は stderr へ 1 行ずつ出す。`jin editor` の stderr はトークンと URL を
        載せる連絡路なので、そこにブラウザの要求ログを流し込まない。
        """

    def do_OPTIONS(self) -> None:
        """preflight を**通さない**。

        CORS ヘッダを 1 つも返さないので、他オリジンのページは本要求へ進めない。
        トークンをカスタムヘッダで要求しているのはこのためである（spec §3.2）。
        body や query に置くと `Content-Type` 次第で **simple request** になり、
        preflight 無しで他オリジンから実行を起こされる。
        """
        self.send_error(HTTPStatus.FORBIDDEN, "CORS preflight is not allowed")

    def do_POST(self) -> None:
        """`POST /run` だけを受ける（spec §4）。

        guard: do_POST -> endpoint.authorize
        """
        endpoint = self._endpoint
        if endpoint is None or self.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not endpoint.authorize(self.headers.get("Origin"), self.headers.get("X-Jin-Token")):
            self.send_error(HTTPStatus.FORBIDDEN, "token or origin mismatch")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "bad Content-Length")
            return
        if length > MAX_RUN_BODY:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            request = runserver.parse_request(self.rfile.read(length))
        except RunRejected as exc:
            # **理由は第 3 引数（body）へ。** 第 2 引数はステータス行に載り、
            # `send_response_only` が **latin-1** で符号化するので日本語だと
            # `UnicodeEncodeError` で接続が切れる（応答が返らない）。
            self.send_error(HTTPStatus.BAD_REQUEST, "bad request body", str(exc))
            return
        # **同時に走ってよいのは 1 本だけ。** 枠を取れなかったら 409 で断る。
        if not endpoint.slot.try_acquire():
            self.send_error(HTTPStatus.CONFLICT, "a run is already going")
            return
        try:
            self._stream_run(endpoint, request)
        finally:
            endpoint.slot.release()

    def _stream_run(self, endpoint: RunEndpoint, request: runserver.RunRequest) -> None:
        """SSE で流す。`Content-Length` を持てないので接続を閉じて区切る。"""
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for frame in runserver.stream(endpoint.target, request, slot=endpoint.slot):
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # ブラウザが離れた。走っている子は道連れにする（残すと孤児になる）。
            endpoint.slot.terminate()


def _handler_for(
    root: Path, endpoint: RunEndpoint | None = None
) -> Callable[..., SimpleHTTPRequestHandler]:
    """配信の根を `root` に固定したハンドラ。

    `directory=` を渡さないと `SimpleHTTPRequestHandler` は **cwd を配る**。
    cwd には `.jin` も鍵もありうるので、根はここで 1 回だけ固定する。
    **この関数が `directory=` を渡す唯一の場所**であり、`_static_server` が
    `guard:` でここを名指ししている（`directory=` そのものは式ではないので
    トークンにできない。固定の所在をこの 1 関数に閉じることで代える）。
    """
    return partial(_StaticHandler, directory=str(root), endpoint=endpoint)


def _static_server(
    host: str, root: Path, endpoint: RunEndpoint | None = None
) -> ThreadingHTTPServer:
    """`root` の中だけを配る HTTP サーバ。ポートは OS に選ばせて実値を読む。

    guard: _static_server -> _handler_for(root,endpoint)
    """
    # ↑ トークンに**空白を入れない**。`test_guard_claims.py` の `CLAIM` は `->\s*(\S+)` で
    # 拾うので、`_handler_for(root, endpoint)` と書くと `_handler_for(root,` で切れて
    # `ast.parse` が SyntaxError になる。AST は空白を無視するので実コードとは一致する。
    return ThreadingHTTPServer((host, 0), _handler_for(root, endpoint))


__all__ = [
    "MAX_RUN_BODY",
    "URL_PREFIX",
    "EditorAddress",
    "EditorError",
    "RunEndpoint",
    "build_url",
    "default_dist",
    "editor_root",
    "free_port",
    "prepare",
    "serve",
]
