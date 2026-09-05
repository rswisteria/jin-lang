"""生成物を `<out>/<root_name>/` へ書く（要件書 §3.1）。

```
<out>/
  <root_name>/
    __init__.py
    agent.py
  .env.example
```

## 安全の約束（design.yaml review_axes_note (1) / Phase 1 の fmt と同じ規律）

- **既存ファイルを黙って上書きしない**: `O_CREAT | O_EXCL` で開く。存在すれば `WriteRefused`。
  `--force` のときも既存ファイルは**開かない**: 同じディレクトリに `.<name>.jin-tmp` を `O_EXCL` で作って
  全部書き、3 つとも書けたあとで `os.replace`（`dir_fd` 相対）で差し替える。途中で `os.write` が
  ENOSPC で失敗しても既存の内容は 1 バイトも変わらない（F-S-P2-104。`ftruncate` 方式では 0 バイトが残った）。
- **`<out>` の外へ書かない**: `root_name` を `_check_root_name` で再検査したうえで、
  ディレクトリ fd 相対（`dir_fd`）で `mkdir` / `open` する。パス文字列の連結で外へ出る経路が無い。
- **シンボリックリンクを辿らない**: `<out>` 自体・パッケージディレクトリ・ファイルのいずれも
  `O_NOFOLLOW` で開く（`--trace` と同じ規律・F-S-P2-007）。リンクなら拒む。
- **中途半端に残さない**: 3 ファイルすべてを開け、**本文を UTF-8 に encode できる**ことを
  確かめてから書く（encode は open より前・F-S-P2-005）。途中で何が起きても（`WriteRefused` に
  限らず `BaseException`）今作ったファイル / 一時ファイル / ディレクトリだけを片付け、既存ファイルの
  内容は無傷のまま残す。
- **`OSError` をトレースバックにしない**: `--out` が通常ファイル / dangling symlink /
  `ENAMETOOLONG` などは `WriteRefused` に包む（Phase 1 の T-1 と同型・F-S-P2-004）。

    guard: _check_root_name -> root_name.isidentifier()
    guard: _check_root_name -> unicodedata.normalize
    guard: _open_out_dir -> os.O_DIRECTORY
    guard: _open_out_dir -> os.O_NOFOLLOW
    guard: _open_package_dir -> os.O_NOFOLLOW
    guard: _open_for_write -> os.O_EXCL
    guard: _open_for_write -> os.O_NOFOLLOW
    guard: _open_for_write -> stat.S_ISLNK
    guard: _open_for_write -> os.fchmod
    guard: _move_into_place -> os.replace
    guard: write_project -> text.encode("utf-8")
"""

from __future__ import annotations

import contextlib
import errno
import keyword
import os
import stat
import unicodedata
from pathlib import Path

from jin_adk.codegen import GeneratedProject


class WriteRefused(Exception):
    """安全に書けないので書き込みを拒んだ（トレースバックではなく利用者向けの文で伝える）。"""


def _check_root_name(root_name: str) -> None:
    """`root_name` を **書き込み直前に**もう一度検査する。

    `JinFile.root` は `Ident`（制御文字だけを禁じる）なので `../x` や `a/b` を通す。
    `jin_adk.codegen.generate` が識別子であることを検査しているが、`GeneratedProject` を
    手で組んだ経路（テスト・将来の呼び出し元）にも耐えるよう、ここで二重に閉じる。

    guard: _check_root_name -> root_name.isidentifier()
    guard: _check_root_name -> unicodedata.normalize
    """
    if (
        not root_name.isidentifier()
        or unicodedata.normalize("NFKC", root_name) != root_name
        or keyword.iskeyword(root_name)
        or os.sep in root_name
        or (os.altsep and os.altsep in root_name)
        or root_name in (".", "..")
    ):
        raise WriteRefused(
            f"root '{root_name}' はディレクトリ名に使えません"
            "（Python の識別子で、パス区切りを含まないこと）"
        )


def _open_package_dir(out_fd: int, root_name: str, *, force: bool) -> tuple[int, bool]:
    """`<out>/<root_name>/` を作って開く。リンクなら拒む。戻り値は `(fd, 今作ったか)`。

    リンクの防御は二層ある。**本体は `O_NOFOLLOW`**（カーネルが拒む・競合しない）で、
    `lstat` の `S_ISLNK` 判定は利用者向けの文言を出すための事前判定にすぎない
    （変異検証: 事前判定だけを消しても `O_NOFOLLOW` が ELOOP で拒む。両方消すと落ちる）。

    guard: _open_package_dir -> os.O_NOFOLLOW
    """
    created = False
    try:
        os.mkdir(root_name, mode=0o755, dir_fd=out_fd)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        # ENAMETOOLONG（非 ASCII 86 文字以上の root は UTF-8 で 255 バイトを超える）など
        raise WriteRefused(f"{root_name}/ を作れません: {exc.strerror}") from exc
    if not created:
        info = os.stat(root_name, dir_fd=out_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise WriteRefused(
                f"{root_name}/ がシンボリックリンクなので書き込みを拒みました"
                "（リンク先は出力先の外かもしれません）"
            ) from None
        if not stat.S_ISDIR(info.st_mode):
            raise WriteRefused(f"{root_name} がディレクトリではありません") from None
        if not force:
            raise WriteRefused(
                f"{root_name}/ が既にあります。上書きするなら --force を付けてください"
            ) from None
    try:
        fd = os.open(root_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=out_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise WriteRefused(
                f"{root_name}/ がシンボリックリンクなので書き込みを拒みました"
            ) from exc
        raise WriteRefused(f"{root_name}/ を開けません: {exc.strerror}") from exc
    return fd, created


#: `--force` で既存ファイルを差し替えるときの一時ファイル名（同じディレクトリ・`.<name>.jin-tmp`）。
TMP_SUFFIX = ".jin-tmp"


def _open_for_write(dir_fd: int, name: str, *, force: bool, shown: Path) -> tuple[int, str]:
    """ファイルを開く。既存なら拒む（`--force` のときだけ、隣の一時ファイルを開く）。リンクは辿らない。

    戻り値は `(fd, 実際に開いた名前)`。新規なら `name` そのもの、既存を差し替えるなら
    `.<name>.jin-tmp`（`O_EXCL`・残骸があれば拒む）。既存ファイル自体は**開かない**ので、
    `O_TRUNC` も `ftruncate` も無く、書き込みが途中で失敗しても既存の内容は変わらない（F-S-P2-104）。
    差し替えは `write_project` が 3 つとも書けたあとに `_move_into_place`（`os.replace`）で行う。

    既存がシンボリックリンクなら `--force` でも拒む（`lstat`）。`os.replace` はリンクを辿らず
    リンク自体を置き換えるので、この事前判定はリンク先を守るためではなく、利用者が意図しない
    「リンクの消滅」を起こさないための判定。

    guard: _open_for_write -> os.O_EXCL
    guard: _open_for_write -> os.O_NOFOLLOW
    guard: _open_for_write -> stat.S_ISLNK
    guard: _open_for_write -> os.fchmod
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
        fd = os.open(tmp, create, 0o644, dir_fd=dir_fd)
    except FileExistsError:
        raise WriteRefused(
            f"{shown.parent / tmp} が残っています（前回の書き込みの残骸）。"
            "中身を確認して消してから、もう一度 --force で実行してください"
        ) from None
    except OSError as exc:
        raise WriteRefused(f"{shown.parent / tmp} を開けません: {exc.strerror}") from exc
    # 既存ファイルのモードを引き継ぐ（利用者の chmod 600 を umask の既定に戻さない・Phase 1 の N1 と同じ規律。
    # F-S-P2-204 / F-C-P2-201: 旧 ftruncate 方式は同じ inode に書くので保たれていた）。
    # 失敗したら tmp と fd をここで片付ける: 呼び出し側の `opened` にまだ積まれていないので、
    # 放置すると `.<name>.jin-tmp` が残り次の --force が「残骸」で拒まれる（F-S-P2-301）
    try:
        os.fchmod(fd, stat.S_IMODE(info.st_mode))
    except OSError as exc:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp, dir_fd=dir_fd)
        raise WriteRefused(
            f"{shown} のモード（{stat.S_IMODE(info.st_mode):04o}）を一時ファイルへ引き継げません: {exc.strerror}。"
            "既存のファイルは変わっていません"
        ) from exc
    return fd, tmp


def _partial_apply_note(replaced: list[Path], planned: list[Path]) -> str:
    """差し替えが途中で止まったときの状態を文で言う（F-S-P2-203）。原子性は追求しない。"""
    if not replaced:
        return "既存のファイルはどれも変わっていません。jin build --force を再実行してください"
    stale = [p for p in planned if p not in replaced]
    return (
        f"{' / '.join(map(str, replaced))} は新しい内容、{' / '.join(map(str, stale))} は前の内容のままです"
        "（部分適用）。jin build --force を再実行してください"
    )


def _move_into_place(dir_fd: int, opened_name: str, name: str) -> None:
    """一時ファイルを本来の名前へ差し替える（新規ファイルは既に本来の名前なので何もしない）。

    guard: _move_into_place -> os.replace
    """
    if opened_name != name:
        os.replace(opened_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)


def _open_out_dir(out: Path) -> int:
    """`<out>` を作って開く。通常ファイル / dangling symlink / リンクは `WriteRefused`。

    guard: _open_out_dir -> os.O_DIRECTORY
    guard: _open_out_dir -> os.O_NOFOLLOW
    """
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WriteRefused(f"{out} を出力先ディレクトリにできません: {exc.strerror}") from exc
    try:
        return os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        # Linux はリンクに O_DIRECTORY | O_NOFOLLOW で open すると ENOTDIR を返す（ELOOP ではない・実測）
        if exc.errno in (errno.ELOOP, errno.ENOTDIR) and out.is_symlink():
            raise WriteRefused(
                f"{out} がシンボリックリンクなので書き込みを拒みました（リンク先を直接指定してください）"
            ) from exc
        raise WriteRefused(f"{out} を開けません: {exc.strerror}") from exc


def write_project(project: GeneratedProject, out: Path, *, force: bool = False) -> list[Path]:
    """生成物を書き出し、書いたファイルのパスを返す。

    順序: encode → 3 ファイル（既存なら隣の一時ファイル）を開く → 全部書く → 一時ファイルを差し替える。
    encode の失敗（孤立サロゲート）・open の拒否・書き込みの失敗のどれも、既存ファイルに一切触れる前に起きる。

    guard: write_project -> text.encode("utf-8")
    """
    _check_root_name(project.root_name)
    out = Path(out)
    plan_text = [
        ("__init__.py", project.init_py),
        ("agent.py", project.agent_py),
        (".env.example", project.env_example),
    ]
    encoded: list[bytes] = []
    for name, text in plan_text:
        try:
            encoded.append(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise WriteRefused(
                f"{name} の内容を UTF-8 に encode できません（{exc.reason}）。"
                "ファイル名などに不正なバイト列が含まれていないか確認してください"
            ) from exc
    out_fd = _open_out_dir(out)
    written: list[Path] = []
    try:
        pkg_fd, created = _open_package_dir(out_fd, project.root_name, force=force)
        try:
            pkg = out / project.root_name
            plan = [
                (pkg_fd, "__init__.py", encoded[0], pkg / "__init__.py"),
                (pkg_fd, "agent.py", encoded[1], pkg / "agent.py"),
                (out_fd, ".env.example", encoded[2], out / ".env.example"),
            ]
            #: (fd, 開いた名前, 本文, 表示用パス, dir_fd, 本来の名前)
            opened: list[tuple[int, str, bytes, Path, int, str]] = []
            open_fds: list[int] = []
            try:
                for dir_fd, name, data, path in plan:
                    fd, opened_name = _open_for_write(dir_fd, name, force=force, shown=path)
                    opened.append((fd, opened_name, data, path, dir_fd, name))
                    open_fds.append(fd)
                for fd, opened_name, data, path, dir_fd, name in opened:
                    view = memoryview(data)
                    while view:
                        view = view[os.write(fd, view) :]
                    os.close(fd)
                    open_fds.remove(fd)
                # 3 つとも書けた。ここで初めて既存ファイルに触る（一時ファイルを差し替える）。
                # 3 つを 1 つのトランザクションにはできない（F-S-P2-203）。agent.py を最後にして、
                # 途中で失敗したとき「agent.py だけ新しい」より害の少ない組み合わせにする
                for _, opened_name, _, path, dir_fd, name in sorted(
                    opened, key=lambda o: o[5] == "agent.py"
                ):
                    try:
                        _move_into_place(dir_fd, opened_name, name)
                    except OSError as exc:
                        raise WriteRefused(
                            f"{path} の差し替えに失敗しました: {exc.strerror}。"
                            + _partial_apply_note(written, [o[3] for o in opened])
                        ) from exc
                    written.append(path)
            except BaseException:
                # 途中まで作ったものを片付ける（今作ったファイル / 一時ファイル / ディレクトリだけ。
                # 既存物は触らない）。`WriteRefused` に限らない: ENOSPC の `os.write` や
                # KeyboardInterrupt でも同じ。差し替え済みの一時ファイルはもう無い（FileNotFoundError を無視）
                for fd in open_fds:
                    os.close(fd)
                for _, opened_name, _, _, dir_fd, _ in opened:
                    try:
                        os.unlink(opened_name, dir_fd=dir_fd)
                    except FileNotFoundError:
                        pass
                if created:
                    os.close(pkg_fd)
                    pkg_fd = -1
                    os.rmdir(project.root_name, dir_fd=out_fd)
                raise
        finally:
            if pkg_fd != -1:
                os.close(pkg_fd)
    except OSError as exc:
        raise WriteRefused(f"{out} への書き込みに失敗しました: {exc.strerror}") from exc
    finally:
        os.close(out_fd)
    return written


__all__ = ["TMP_SUFFIX", "WriteRefused", "write_project"]
