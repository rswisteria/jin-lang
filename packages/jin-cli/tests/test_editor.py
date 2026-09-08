"""`jin editor`（要件書 §7.3）の単体。

ブラウザを立ち上げる部分（`serve` の本体）はここでは動かさない。
Playwright のスモーク（`apps/editor/e2e/smoke.spec.ts`）が実プロセスで通す。
ここが見るのは**入口の拒否**と**URL の組み立て**である。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import pytest
from jin_cli.editor import (
    EditorError,
    RunEndpoint,
    _static_server,
    build_url,
    default_dist,
    editor_root,
    free_port,
    prepare,
)
from jin_cli.runserver import RunSlot  # noqa: F401  (serve の finally を差し替えるため)

VALID = """{
  "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
  "version": 1,
  "root": "Main",
  "circles": [
    {
      "name": "Main",
      "core": "gemini-2.5-flash"
    }
  ]
}
"""


def test_token_goes_into_the_fragment_not_the_query() -> None:
    """**トークンはフラグメントに置く**。

    フラグメントは HTTP 要求にも `Referer` にも載らないので、`jin editor` が動かす
    静的サーバのアクセスログにも、そこから遷移した先にも出ない。
    クエリに置くと 1 行目のリクエストラインに載り、ログに残る。
    """
    url = build_url(8000, 8001, Path("/tmp/a.jin"), "SECRET-TOKEN", "127.0.0.1")
    parts = urlsplit(url)
    assert parts.fragment == "token=SECRET-TOKEN"
    assert "SECRET-TOKEN" not in parts.query
    assert "SECRET-TOKEN" not in parts.path


def test_url_carries_the_ws_endpoint_and_the_file_uri(tmp_path: Path) -> None:
    target = tmp_path / "a.jin"
    target.write_text(VALID, encoding="utf-8")
    url = build_url(8000, 8001, target, "t", "127.0.0.1")
    assert "ws=ws://127.0.0.1:8001" in url
    # `uri` は**符号化して**載せる（`/` がそのまま出ると別のクエリ引数に見える）。
    assert f"uri={quote(target.resolve().as_uri(), safe='')}" in url
    assert url.startswith("http://127.0.0.1:8000/?")


def test_the_writable_root_is_the_files_own_directory() -> None:
    """`jin/open` / `jin/save` の範囲は**対象ファイルの親だけ**（それより広げない）。"""
    assert editor_root(Path("/a/b/c.jin")) == Path("/a/b")


def test_free_port_returns_a_usable_port() -> None:
    port = free_port("127.0.0.1")
    assert 1 <= port <= 65535


def test_default_dist_finds_the_built_editor() -> None:
    """リポジトリのレイアウトから `apps/editor/dist` を見つける（無ければ None）。"""
    found = default_dist()
    assert found is None or found.name == "dist"


def test_a_non_jin_file_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "a.txt"
    other.write_text("{}", encoding="utf-8")
    with pytest.raises(EditorError, match=r"\.jin"):
        prepare(other)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EditorError, match="ファイルがありません"):
        prepare(tmp_path / "none.jin")


def test_a_missing_build_is_refused(tmp_path: Path) -> None:
    """dist が無いときに 404 を配らず、何をすべきかを言って落ちる（NFR-FAIL-001）。"""
    target = tmp_path / "a.jin"
    target.write_text(VALID, encoding="utf-8")
    with pytest.raises(EditorError, match="index.html|pnpm build"):
        prepare(target, tmp_path / "nowhere")


def test_a_dist_without_index_html_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "a.jin"
    target.write_text(VALID, encoding="utf-8")
    empty = tmp_path / "dist"
    empty.mkdir()
    with pytest.raises(EditorError, match="index.html"):
        prepare(target, empty)


def test_the_static_server_only_serves_the_dist(tmp_path: Path) -> None:
    """静的配信の根は dist に固定される。**cwd を配らない**。

    `SimpleHTTPRequestHandler` は `directory=` を渡さないと cwd を配る。cwd には
    `.jin` も鍵もありうるので、これは配信範囲が黙って広がることを意味する。
    ここでは dist の外に置いたファイルが 404 になることを実際の HTTP で確かめる。
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    outside = tmp_path / "secret.jin"
    outside.write_text(VALID, encoding="utf-8")

    httpd = _static_server("127.0.0.1", dist)
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/index.html", timeout=5) as answer:
            assert answer.status == 200
        for escape in ("/secret.jin", "/../secret.jin", "/%2e%2e/secret.jin"):
            with pytest.raises(HTTPError) as caught:
                urlopen(f"http://127.0.0.1:{port}{escape}", timeout=5)
            assert caught.value.code == 404, escape
    finally:
        httpd.shutdown()
        httpd.server_close()


# ======================================================================================
# 実行エンドポイント（Issue #34・spec §4）
# ======================================================================================
@pytest.fixture
def endpoint_server(tmp_path: Path):
    """静的サーバを 1 本立てて、`(url, endpoint)` を返す。

    対象は `ref` も `builtin` も持たない `VALID`。実行は**子プロセス**で起きるので、
    `conftest.py` の `sys.path` 細工は届かない（届くのは `PYTHONPATH` だけ）。
    `examples/pipeline` を使うとその env の細工がテストに要る。
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>dist</html>", encoding="utf-8")
    target = tmp_path / "solo.jin"
    target.write_text(VALID, encoding="utf-8")

    endpoint = RunEndpoint(target=target, token="secret-token")
    httpd = _static_server("127.0.0.1", dist, endpoint)
    port = int(httpd.server_address[1])
    endpoint.origin = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", endpoint
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(url: str, *, token: str | None, origin: str | None, body: bytes) -> int:
    """`POST /run` を撃って HTTP の状態番号だけ返す。"""
    request = Request(url + "/run", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("X-Jin-Token", token)
    if origin is not None:
        request.add_header("Origin", origin)
    try:
        with urlopen(request, timeout=60) as answer:
            answer.read()
            return int(answer.status)
    except HTTPError as error:
        return int(error.code)


def test_the_static_files_are_still_served_with_the_run_endpoint(endpoint_server) -> None:
    """実行の口を足しても `GET` は従来どおり。"""
    url, _ = endpoint_server
    with urlopen(url + "/index.html", timeout=10) as answer:
        assert b"dist" in answer.read()


def test_run_without_the_token_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    assert _post(url, token=None, origin=url, body=b'{"prompt": "go"}') == 403


def test_run_with_a_wrong_token_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    assert _post(url, token="wrong", origin=url, body=b'{"prompt": "go"}') == 403


def test_run_from_another_origin_is_refused(endpoint_server) -> None:
    """`Origin` 検査。ws と違って HTTP はここを見られる。"""
    url, _ = endpoint_server
    assert (
        _post(url, token="secret-token", origin="http://evil.example", body=b'{"prompt": "go"}')
        == 403
    )


def test_options_is_refused_so_preflight_never_passes(endpoint_server) -> None:
    """CORS ヘッダを 1 つも返さない。preflight が通らなければ本要求は飛ばない。

    **これが「HTTP は ws より強い」の根拠のすべて**である（spec §3.2）。トークンを
    カスタムヘッダで要求すると preflight が必須になり、こちらが許可を返さない限り
    他オリジンのページは本要求を送れない。
    """
    url, _ = endpoint_server
    request = Request(url + "/run", method="OPTIONS")
    request.add_header("Origin", "http://evil.example")
    request.add_header("Access-Control-Request-Method", "POST")
    request.add_header("Access-Control-Request-Headers", "x-jin-token")
    with pytest.raises(HTTPError) as caught:
        urlopen(request, timeout=10)
    assert caught.value.code == 403
    assert caught.value.headers.get("Access-Control-Allow-Origin") is None


def test_a_broken_body_is_refused(endpoint_server) -> None:
    url, _ = endpoint_server
    assert _post(url, token="secret-token", origin=url, body=b"not json") == 400


def test_a_real_model_name_is_refused(endpoint_server) -> None:
    """実モデルは `.jin` の core が持つ（`jin run` と同じ規律）。"""
    url, _ = endpoint_server
    body = b'{"prompt": "go", "model": "gemini-2.0-flash"}'
    assert _post(url, token="secret-token", origin=url, body=body) == 400


def test_a_second_run_is_refused_while_one_is_going(endpoint_server) -> None:
    url, endpoint = endpoint_server
    assert endpoint.slot.try_acquire() is True
    try:
        assert _post(url, token="secret-token", origin=url, body=b'{"prompt": "go"}') == 409
    finally:
        endpoint.slot.release()


def test_run_streams_rows_and_finishes(endpoint_server) -> None:
    """正常系。`--model fake` で row が並び、最後に done が来る。"""
    url, _ = endpoint_server
    request = Request(url + "/run", data=b'{"prompt": "go", "model": "fake"}', method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Jin-Token", "secret-token")
    request.add_header("Origin", url)
    with urlopen(request, timeout=180) as answer:
        assert answer.headers.get_content_type() == "text/event-stream"
        text = answer.read().decode("utf-8")
    assert "event: row\n" in text, text
    assert text.count("event: done\n") == 1, text
    done = json.loads(text.rsplit("event: done\ndata: ", 1)[1].strip())
    assert done["exit"] == 0, done


def test_serve_terminates_the_run_slot_when_it_stops(tmp_path: Path, monkeypatch) -> None:
    """`serve` が終わるとき、走っている実行を残さない（Issue #32 と同じ規律）。"""
    from jin_cli import editor as editor_module

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    target = tmp_path / "x.jin"
    target.write_text(VALID, encoding="utf-8")

    terminated: list[bool] = []

    class _Stub:
        """`create_server` の代わり。`serve_ws` はすぐ返る（本物はブロックする）。"""

        def serve_ws(self, host: str, port: int) -> None:
            return None

    monkeypatch.setattr(editor_module, "create_server", lambda files: _Stub())
    monkeypatch.setattr(editor_module.RunSlot, "terminate", lambda self: terminated.append(True))

    editor_module.serve(target, dist=dist, open_browser=False)

    assert terminated == [True], "serve の finally が走っている実行を終わらせていない"
