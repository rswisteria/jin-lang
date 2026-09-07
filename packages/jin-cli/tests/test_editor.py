"""`jin editor`（要件書 §7.3）の単体。

ブラウザを立ち上げる部分（`serve` の本体）はここでは動かさない。
Playwright のスモーク（`apps/editor/e2e/smoke.spec.ts`）が実プロセスで通す。
ここが見るのは**入口の拒否**と**URL の組み立て**である。
"""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

import pytest
from jin_cli.editor import (
    EditorError,
    _static_server,
    build_url,
    default_dist,
    editor_root,
    free_port,
    prepare,
)

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
