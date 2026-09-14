"""`jin build`（v2）のバンドル書き出し（runtime.md §9）。

```
<out>/
  game.lua              # JIL
  game.manifest.json    # { file, stage, namespaces, assets, debug, jil }
  assets/               # stage.assets の実体をコピー（manifest の path は assets/<ファイル名> に書き換える）
  index.html / player.js / wasmoon.wasm   # apps/player のビルド物。同梱されていなければ書かず、その旨を返す
```

`--single` は `index.html` **1 本**だけを書く（`player.js` をインラインにし、JIL / manifest / wasm（base64）を
`window.JIN_BUNDLE` に埋める。runtime.md §9）。asset は埋められないので、`assets` があれば拒む（設計書 §11 #34）。

`--target wasm-gc`（jil.md §6.8・v2.1 Issue #53）は `program=("game.wasm", bytes)` で本体ファイルを差し替える。
そのときはプレイヤーのビルド物を書かず（`WasmGcHost` の配線は #76）、`--single` も拒む。書き出しの規律は同じ。

プレイヤーのビルド物は `jin_wasm/player/`（gitignore。`scripts/sync_player.py` が `apps/player/dist` から複製する。
wheel には入る）。

## 安全の約束（`jin_adk.build` と同じ規律）

- **既存ファイルを黙って上書きしない**: `O_CREAT | O_EXCL` で開く。存在すれば `WriteRefused`。
  `--force` のときは隣に `.<name>.jin-tmp` を `O_EXCL` で作って書き、全部書けたあとで `os.replace`
- **`<out>` の外へ書かない**: ディレクトリ fd 相対（`dir_fd`）で開く。ファイル名は固定
  （`game.lua` / `game.manifest.json`）か、asset のファイル名（パス区切りを含まない basename）
- **シンボリックリンクを辿らない**: `<out>` / `assets/` / 各ファイルを `O_NOFOLLOW` で開く
- **asset は `.jin` の親ディレクトリの中だけ**: `Asset.path` は `Ident`（制御文字だけを禁じる）なので
  `../etc/passwd` がモデルを通る。絶対パスと `..` を拒み、`realpath` が `.jin` の親の中に留まることを
  `os.path.commonpath` で確かめ、`O_NOFOLLOW` で開いて通常ファイルであることを見る
- **中途半端に残さない**: 失敗したら今作ったファイル / 一時ファイル / ディレクトリだけを片付ける

**残存**: asset の `realpath` の検査と `O_NOFOLLOW` の open の間には窓がある（TOCTOU）。
その間に中間ディレクトリのリンクを差し替えられると、検査を通った別のファイルを読む。
v1 の `jin check <dir>` / `fmt` の読み取りと同じ種類の残存で、最後の open が symlink 自体を
辿らないことまでは保証する。**信頼しないディレクトリの `.jin` を `jin build` しない**

    guard: _open_out_dir -> os.O_NOFOLLOW
    guard: _open_out_dir -> os.O_DIRECTORY
    guard: _open_for_write -> os.O_EXCL
    guard: _open_for_write -> os.O_NOFOLLOW
    guard: _asset_source -> os.path.commonpath
    guard: _asset_source -> os.O_NOFOLLOW
    guard: _asset_source -> stat.S_ISREG
    guard: _move_into_place -> os.replace
    guard: single_index_html -> _escape_inline_json(bundle)
"""

from __future__ import annotations

import base64
import errno
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from jin_wasm.codegen import GeneratedGame


class Bundleable(Protocol):
    """`write_bundle` が読む生成物の形（`GeneratedGame` と `jin_wasmgc.assemble.GeneratedWasm`）。"""

    @property
    def manifest(self) -> dict[str, Any]: ...

    @property
    def debug(self) -> bool: ...


TMP_SUFFIX = ".jin-tmp"
GAME_LUA = "game.lua"
GAME_MANIFEST = "game.manifest.json"
ASSETS_DIR = "assets"
INDEX_HTML = "index.html"
#: apps/player のビルド物（`scripts/sync_player.py` が `jin_wasm/player/` に複製する）。
PLAYER_FILES = ("index.html", "player.js", "wasmoon.wasm")
PLAYER_DIR = Path(__file__).with_name("player")
#: `apps/player/public/index.html` の目印。`--single` はここを置き換える（`apps/player` 側と 1:1）。
BUNDLE_MARKER = "<!-- jin:bundle -->"
PLAYER_SCRIPT_TAG = '<script src="player.js"></script>'
#: プレイヤーが同梱されていないときの補足（`jin build` が stderr に出す）。
PLAYER_MISSING_NOTE = (
    "プレイヤー（index.html / player.js / wasmoon.wasm）が同梱されていません。"
    "`cd apps/player && pnpm install && pnpm build` のあと "
    "`uv run python scripts/sync_player.py` で同梱できます"
)


class WriteRefused(Exception):
    """安全に書けないので書き込みを拒んだ（トレースバックではなく利用者向けの文で伝える）。"""


@dataclass(slots=True)
class BundleResult:
    written: list[Path]
    #: 利用者に伝える補足（プレイヤーが無い、など）。
    notes: list[str] = field(default_factory=list)


def player_available() -> bool:
    return all((PLAYER_DIR / name).is_file() for name in PLAYER_FILES)


def _escape_inline_json(text: str) -> str:
    """`<script>` の中に置く JSON。`</` を `<\\/` にして `</script>` で閉じられないようにする。

    JSON は文字列の中の `\\/` を `/` と読むので意味は変わらない（JIL / manifest に `</script>` が
    入っていても HTML を壊せない）。
    """
    return text.replace("</", "<\\/")


def single_index_html(
    game: GeneratedGame, manifest: dict, *, player_dir: Path | None = None
) -> bytes:
    """`--single` の `index.html`: `player.js` をインラインにし、JIL / manifest / wasm を埋める。

    `apps/player/public/index.html` の `<!-- jin:bundle -->` を `window.JIN_BUNDLE = {...}` に、
    `<script src="player.js">` を `<script>` + 本文に置き換える。`player.js` は自前のビルド物なので
    `</script` を含まないはずだが、含んでいたら（インラインにすると HTML が壊れる）拒む。

    guard: single_index_html -> _escape_inline_json(bundle)
    """
    if player_dir is None:
        player_dir = PLAYER_DIR
    html = (player_dir / "index.html").read_text(encoding="utf-8")
    player_js = (player_dir / "player.js").read_text(encoding="utf-8")
    wasm = base64.b64encode((player_dir / "wasmoon.wasm").read_bytes()).decode("ascii")
    if BUNDLE_MARKER not in html or PLAYER_SCRIPT_TAG not in html:
        raise WriteRefused(
            f"同梱された index.html に {BUNDLE_MARKER} か {PLAYER_SCRIPT_TAG} がありません"
            "（apps/player のビルド物と jin_wasm の版がずれています）"
        )
    if "</script" in player_js.lower():
        raise WriteRefused("同梱された player.js に </script が含まれるのでインラインにできません")
    bundle = json.dumps({"jil": game.lua, "manifest": manifest, "wasm": wasm}, ensure_ascii=False)
    html = html.replace(
        BUNDLE_MARKER, f"<script>window.JIN_BUNDLE = {_escape_inline_json(bundle)};</script>", 1
    )
    html = html.replace(PLAYER_SCRIPT_TAG, f"<script>\n{player_js}\n</script>", 1)
    return html.encode("utf-8")


def _asset_source(source_dir: Path, rel: str) -> tuple[int, str]:
    """asset の実体を開く（fd）。`.jin` の親ディレクトリの外・リンク・通常ファイル以外は拒む。

    guard: _asset_source -> os.path.commonpath
    guard: _asset_source -> os.O_NOFOLLOW
    guard: _asset_source -> stat.S_ISREG
    """
    if not rel or os.path.isabs(rel) or ".." in Path(rel).parts:
        raise WriteRefused(f"asset のパス '{rel}' は .jin からの相対パスで、'..' を含めません")
    base = os.path.realpath(source_dir)
    target = os.path.realpath(os.path.join(base, rel))
    if os.path.commonpath([base, target]) != base:
        raise WriteRefused(f"asset のパス '{rel}' は .jin のディレクトリの外を指しています")
    try:
        fd = os.open(os.path.join(base, rel), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise WriteRefused(f"asset '{rel}' がシンボリックリンクなので拒みました") from exc
        raise WriteRefused(f"asset '{rel}' を開けません: {exc.strerror}") from exc
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise WriteRefused(f"asset '{rel}' が通常ファイルではありません")
    return fd, Path(rel).name


def _open_out_dir(out: Path) -> tuple[int, bool]:
    """`<out>` を作って開く。戻りは `(fd, 今作ったか)`。リンク / 通常ファイルは拒む。

    guard: _open_out_dir -> os.O_NOFOLLOW
    guard: _open_out_dir -> os.O_DIRECTORY
    """
    created = False
    try:
        out.mkdir(parents=True)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise WriteRefused(f"{out} を出力先ディレクトリにできません: {exc.strerror}") from exc
    try:
        return os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW), created
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR) and out.is_symlink():
            raise WriteRefused(
                f"{out} がシンボリックリンクなので書き込みを拒みました（リンク先を直接指定してください）"
            ) from exc
        raise WriteRefused(f"{out} を開けません: {exc.strerror}") from exc


def _open_subdir(dir_fd: int, name: str, shown: Path) -> tuple[int, bool]:
    created = False
    try:
        os.mkdir(name, mode=0o755, dir_fd=dir_fd)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise WriteRefused(f"{shown}/ を作れません: {exc.strerror}") from exc
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise WriteRefused(
                f"{shown}/ がシンボリックリンクか通常ファイルなので拒みました"
            ) from exc
        raise WriteRefused(f"{shown}/ を開けません: {exc.strerror}") from exc
    return fd, created


def _open_for_write(dir_fd: int, name: str, *, force: bool, shown: Path) -> tuple[int, str]:
    """新規なら `name`、既存なら（`--force` のときだけ）隣の `.<name>.jin-tmp` を `O_EXCL` で開く。

    guard: _open_for_write -> os.O_EXCL
    guard: _open_for_write -> os.O_NOFOLLOW
    """
    create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        return os.open(name, create, 0o644, dir_fd=dir_fd), name
    except FileExistsError:
        if not force:
            raise WriteRefused(
                f"{shown} が既にあります。上書きするなら --force を付けてください"
            ) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise WriteRefused(f"{shown} がシンボリックリンクなので書き込みを拒みました") from exc
        raise WriteRefused(f"{shown} を開けません: {exc.strerror}") from exc
    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise WriteRefused(f"{shown} がシンボリックリンクなので書き込みを拒みました") from None
    tmp = f".{name}{TMP_SUFFIX}"
    try:
        return os.open(tmp, create, 0o644, dir_fd=dir_fd), tmp
    except FileExistsError:
        raise WriteRefused(
            f"{shown.parent / tmp} が残っています（前回の書き込みの残骸）。"
            "中身を確認して消してから、もう一度 --force で実行してください"
        ) from None
    except OSError as exc:
        raise WriteRefused(f"{shown.parent / tmp} を開けません: {exc.strerror}") from exc


def _move_into_place(dir_fd: int, opened_name: str, name: str) -> None:
    """一時ファイルを本来の名前へ差し替える（新規ファイルは既に本来の名前なので何もしない）。

    guard: _move_into_place -> os.replace
    """
    if opened_name != name:
        os.replace(opened_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


@dataclass(slots=True)
class _Plan:
    dir_fd: int
    name: str
    data: bytes | int  # bytes か、コピー元の fd
    shown: Path


def write_bundle(
    game: GeneratedGame | Bundleable,
    out: Path,
    *,
    source: Path,
    force: bool = False,
    single: bool = False,
    program: tuple[str, bytes] | None = None,
) -> BundleResult:
    """バンドルを `<out>/` に書く。`single` は `<out>/index.html` 1 本（プレイヤーの同梱が要る）。

    `program` は本体ファイルの差し替え `(ファイル名, バイト列)`（`--target wasm-gc` の `game.wasm`。
    jil.md §6.8）。与えたときは `game.lua` を書かず、プレイヤーのビルド物も書かない（#76 で配線する）。
    """
    if program is not None and single:
        raise WriteRefused(
            "--single の wasm-gc 版は #76（Sub-Issue D）で入ります。--single 無しで書き出してください"
        )
    if single and not player_available():
        raise WriteRefused(
            "--single はプレイヤー（index.html / player.js / wasmoon.wasm）を埋め込みます。"
            + PLAYER_MISSING_NOTE
        )
    if single and game.manifest["assets"]:
        raise WriteRefused(
            "--single は asset（stage.assets）を埋め込めません（設計書 §11 #34）。"
            "--single 無しで書き出して assets/ ごと配ってください"
        )

    manifest = json.loads(json.dumps(game.manifest))
    source_dir = Path(source).parent
    asset_fds: list[int] = []
    notes: list[str] = []
    try:
        plans_assets: list[tuple[int, str]] = []
        seen: set[str] = set()
        for asset in manifest["assets"]:
            fd, basename = _asset_source(source_dir, asset["path"])
            asset_fds.append(fd)
            if basename in seen:
                raise WriteRefused(
                    f"asset のファイル名 '{basename}' が重複しています（assets/ には同名を置けません）"
                )
            seen.add(basename)
            plans_assets.append((fd, basename))
            asset["path"] = f"{ASSETS_DIR}/{basename}"
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        program_name, program_bytes = (
            program if program is not None else (GAME_LUA, game.lua.encode("utf-8"))
        )
        manifest_bytes = manifest_text.encode("utf-8")

        out = Path(out)
        out_fd, out_created = _open_out_dir(out)
        assets_fd = -1
        assets_created = False
        written: list[Path] = []
        opened: list[tuple[int, str, Path, int, str]] = []  # (fd, opened_name, shown, dir_fd, name)
        open_fds: list[int] = []
        try:
            try:
                plans: list[_Plan] = []
                if single:
                    plans.append(
                        _Plan(
                            out_fd, INDEX_HTML, single_index_html(game, manifest), out / INDEX_HTML
                        )
                    )
                else:
                    plans.append(_Plan(out_fd, program_name, program_bytes, out / program_name))
                    plans.append(_Plan(out_fd, GAME_MANIFEST, manifest_bytes, out / GAME_MANIFEST))
                    if plans_assets:
                        assets_fd, assets_created = _open_subdir(
                            out_fd, ASSETS_DIR, out / ASSETS_DIR
                        )
                        for fd, basename in plans_assets:
                            plans.append(
                                _Plan(assets_fd, basename, fd, out / ASSETS_DIR / basename)
                            )
                    if program is not None:
                        pass  # wasm-gc: プレイヤーは #76 で `WasmGcHost` を配線してから同梱する
                    elif player_available():
                        for name in PLAYER_FILES:
                            plans.append(
                                _Plan(out_fd, name, (PLAYER_DIR / name).read_bytes(), out / name)
                            )
                    else:
                        notes.append(
                            f"{PLAYER_MISSING_NOTE}。{GAME_LUA} / {GAME_MANIFEST} を書きました"
                        )
                for plan in plans:
                    fd, opened_name = _open_for_write(
                        plan.dir_fd, plan.name, force=force, shown=plan.shown
                    )
                    opened.append((fd, opened_name, plan.shown, plan.dir_fd, plan.name))
                    open_fds.append(fd)
                for (fd, _opened_name, _shown, _dir_fd, _name), plan in zip(
                    opened, plans, strict=True
                ):
                    if isinstance(plan.data, bytes):
                        _write_all(fd, plan.data)
                    else:
                        while True:
                            chunk = os.read(plan.data, 1 << 16)
                            if not chunk:
                                break
                            _write_all(fd, chunk)
                    os.close(fd)
                    open_fds.remove(fd)
                for _fd, opened_name, shown, dir_fd, name in opened:
                    _move_into_place(dir_fd, opened_name, name)
                    written.append(shown)
            except BaseException:
                for fd in open_fds:
                    os.close(fd)
                for _fd, opened_name, _shown, dir_fd, _name in opened:
                    try:
                        os.unlink(opened_name, dir_fd=dir_fd)
                    except FileNotFoundError:
                        pass
                if assets_created and assets_fd != -1:
                    os.close(assets_fd)
                    assets_fd = -1
                    os.rmdir(ASSETS_DIR, dir_fd=out_fd)
                if out_created:
                    os.close(out_fd)
                    out_fd = -1
                    try:
                        out.rmdir()
                    except OSError:
                        pass
                raise
        except OSError as exc:
            raise WriteRefused(f"{out} への書き込みに失敗しました: {exc.strerror}") from exc
        finally:
            if assets_fd != -1:
                os.close(assets_fd)
            if out_fd != -1:
                os.close(out_fd)
    finally:
        for fd in asset_fds:
            os.close(fd)
    return BundleResult(written, notes)


__all__ = [
    "ASSETS_DIR",
    "BUNDLE_MARKER",
    "GAME_LUA",
    "GAME_MANIFEST",
    "INDEX_HTML",
    "PLAYER_DIR",
    "PLAYER_FILES",
    "PLAYER_MISSING_NOTE",
    "PLAYER_SCRIPT_TAG",
    "BundleResult",
    "WriteRefused",
    "player_available",
    "single_index_html",
    "write_bundle",
]
