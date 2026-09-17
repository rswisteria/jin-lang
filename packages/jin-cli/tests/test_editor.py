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
from jin_cli.main import app
from jin_cli.runserver import RunSlot  # noqa: F401  (serve の finally を差し替えるため)
from typer.testing import CliRunner

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


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


# ======================================================================================
# `/play/`（Jin v2 の実行パネル・設計書 §8）
# ======================================================================================
def _serve(dist: Path, player: Path | None):
    httpd = _static_server("127.0.0.1", dist, None, player)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{int(httpd.server_address[1])}"


def test_the_player_is_served_under_play_and_cannot_escape(tmp_path: Path) -> None:
    """`/play/…` はプレイヤーの根へ写り、`..` でエディタの `dist` にも外にも抜けない。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>editor</html>", encoding="utf-8")
    player = tmp_path / "player"
    player.mkdir()
    (player / "index.html").write_text("<html>player</html>", encoding="utf-8")
    (player / "player.js").write_text("// js", encoding="utf-8")
    (player / "wasmoon.wasm").write_bytes(b"\\0asm")
    (tmp_path / "secret.jin").write_text(VALID, encoding="utf-8")

    httpd, base = _serve(dist, player)
    try:
        with urlopen(f"{base}/play/index.html", timeout=5) as answer:
            assert answer.read() == b"<html>player</html>"
        with urlopen(f"{base}/play/", timeout=5) as answer:
            assert answer.read() == b"<html>player</html>"
        with urlopen(f"{base}/play/wasmoon.wasm", timeout=5) as answer:
            # `instantiateStreaming` は MIME を見る。Python の mimetypes が `application/wasm` を返す。
            assert answer.headers.get("Content-Type") == "application/wasm"
        with urlopen(f"{base}/index.html", timeout=5) as answer:
            assert answer.read() == b"<html>editor</html>"
        # 脱出: プレイヤーの根から上には行けない（正規化で根に戻るか 404）。
        for escape in ("/play/../secret.jin", "/play/%2e%2e/secret.jin", "/play/../index.html"):
            try:
                with urlopen(f"{base}{escape}", timeout=5) as answer:
                    assert answer.read() != VALID.encode("utf-8"), escape
                    assert answer.read() != b"<html>editor</html>", escape
            except HTTPError as caught:
                assert caught.code == 404, escape
        # `dist` 側の `play` という名前のファイルは影響を受けない（前置きが `/play/` だけ）。
        with pytest.raises(HTTPError) as caught:
            urlopen(f"{base}/player.js", timeout=5)
        assert caught.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_play_is_404_when_there_is_no_player(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>editor</html>", encoding="utf-8")
    httpd, base = _serve(dist, None)
    try:
        with pytest.raises(HTTPError) as caught:
            urlopen(f"{base}/play/index.html", timeout=5)
        assert caught.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_resolve_player_refuses_an_explicit_dir_without_index(tmp_path: Path) -> None:
    from jin_cli.editor import EditorError, resolve_player

    with pytest.raises(EditorError):
        resolve_player(tmp_path)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    assert resolve_player(tmp_path) == tmp_path.resolve()


def test_default_player_dist_prefers_the_repo_then_the_bundle(tmp_path: Path, monkeypatch) -> None:
    from jin_cli import editor as editor_module

    # リポジトリのレイアウトが無い所から探し、同梱版も無ければ None。
    monkeypatch.setattr(editor_module, "BUNDLED_PLAYER_DIR", tmp_path / "none")
    assert editor_module.default_player_dist(tmp_path / "x" / "y.py") is None
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(editor_module, "BUNDLED_PLAYER_DIR", bundled)
    assert editor_module.default_player_dist(tmp_path / "x" / "y.py") == bundled
    # リポジトリの `apps/player/dist` があればそちらが勝つ。
    repo = tmp_path / "repo"
    (repo / "apps" / "player" / "dist").mkdir(parents=True)
    (repo / "apps" / "player" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    assert (
        editor_module.default_player_dist(repo / "packages" / "x.py")
        == (repo / "apps" / "player" / "dist").resolve()
    )


# ======================================================================================
# `/stage/`（鑑賞ページ・docs/spec/v2/stage.md）
# ======================================================================================
def _serve_with_stage(dist: Path, player: Path | None, stage: Path | None):
    httpd = _static_server("127.0.0.1", dist, None, player, stage)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_the_stage_is_served_under_stage_and_cannot_escape(tmp_path: Path) -> None:
    """`/stage/…` は鑑賞ページの根へ写り、`..` でエディタの `dist` にもプレイヤーにも外にも抜けない。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>editor</html>", encoding="utf-8")
    (tmp_path / "secret.jin").write_text("{}", encoding="utf-8")
    player = tmp_path / "player"
    player.mkdir()
    (player / "index.html").write_text("<html>player</html>", encoding="utf-8")
    stage = tmp_path / "stage"
    (stage / "assets").mkdir(parents=True)
    (stage / "index.html").write_text("<html>stage</html>", encoding="utf-8")
    (stage / "assets" / "index.js").write_text("// js", encoding="utf-8")

    httpd, base = _serve_with_stage(dist, player, stage)
    try:
        with urlopen(f"{base}/stage/index.html", timeout=5) as answer:
            assert answer.read() == b"<html>stage</html>"
        with urlopen(f"{base}/stage/", timeout=5) as answer:
            assert answer.read() == b"<html>stage</html>"
        with urlopen(f"{base}/stage/assets/index.js", timeout=5) as answer:
            assert answer.read() == b"// js"
        with urlopen(f"{base}/play/index.html", timeout=5) as answer:
            assert answer.read() == b"<html>player</html>"
        for escape in (
            "/stage/../secret.jin",
            "/stage/%2e%2e/secret.jin",
            "/stage/../play/index.html",
        ):
            with pytest.raises(HTTPError) as caught:
                urlopen(f"{base}{escape}", timeout=5)
            assert caught.value.code == 404, escape
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_stage_is_404_when_there_is_no_stage(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    httpd, base = _serve_with_stage(dist, None, None)
    try:
        with pytest.raises(HTTPError) as caught:
            urlopen(f"{base}/stage/index.html", timeout=5)
        assert caught.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_resolve_stage_refuses_an_explicit_dir_without_index(tmp_path: Path) -> None:
    from jin_cli.editor import EditorError, resolve_stage

    with pytest.raises(EditorError, match="鑑賞ページ"):
        resolve_stage(tmp_path)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    assert resolve_stage(tmp_path) == tmp_path.resolve()


def test_default_stage_dist_is_the_repo_build(tmp_path: Path) -> None:
    from jin_cli import editor as editor_module

    assert editor_module.default_stage_dist(tmp_path / "x" / "y.py") is None
    repo = tmp_path / "repo"
    (repo / "apps" / "stage" / "dist").mkdir(parents=True)
    (repo / "apps" / "stage" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    assert (
        editor_module.default_stage_dist(repo / "packages" / "x.py")
        == (repo / "apps" / "stage" / "dist").resolve()
    )


def test_jin_editor_accepts_stage_dist_without_a_new_subcommand() -> None:
    result = run("editor", "--help")
    assert result.exit_code == 0
    assert "--stage-dist" in result.output
