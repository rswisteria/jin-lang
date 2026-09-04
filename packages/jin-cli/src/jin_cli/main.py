"""Jin CLI。

**Phase 1 で実装するのは check / fmt / schema / dump の 4 つだけ。**
要件書 §5 の残り 5 コマンドは後続 Phase の担当であり、**あえて未定義のままにしてある**:

| コマンド | 実装 Phase | 担当パッケージ |
|---|---|---|
| `jin build` | Phase 2 | jin-adk |
| `jin run` | Phase 2 | jin-adk |
| `jin render` | Phase 3 | jin-render |
| `jin lsp` | Phase 4 | jin-lsp |
| `jin editor` | Phase 5 | apps/editor |

空実装のサブコマンドを先に置くと「あるのに動かない」状態になり、`jin --help` が嘘をつく。
未定義なら typer が "No such command" で落ちるので、未実装であることが利用者に正しく伝わる。

## `guard:` 記法（security review R-2 の再発防止）

「どこでシンボリックリンクを弾いているか」のような**実装依存の安全宣言**を散文で書くと、
実装が動いたときに宣言だけが取り残される。R-2 はまさにそれで、docstring が
「`_collect` が弾いている」と書いていたが `_collect` にフィルタは無かった。

そこで、そういう主張は docstring / コメントの中に

    guard: <関数名> -> <その関数に在るべきトークン>

の形で併記する。`test_guard_claims_point_at_real_guards` が全ての `guard:` 行を集め、
**名指しされた関数の実コード**（docstring とコメントを除いたもの）にそのトークンが
実在することを検査する。嘘を書くとテストが落ちる。
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from jin_core.canonical import dumps
from jin_core.check import CheckResult, JinReadError, check_file, read_source
from jin_core.diagnostics import Diagnostic, has_error
from jin_core.schema_export import render as render_schema

from jin_cli.resolver import ImportResolver

app = typer.Typer(
    name="jin",
    help="Jin(陣) — 魔法陣型エージェント記述言語のツールチェーン（Phase 1: check / fmt / schema / dump）",
    no_args_is_help=True,
    add_completion=False,
    # 例外のトレースバックにローカル変数（環境変数・パスなど）を載せない（security review S5）。
    pretty_exceptions_show_locals=False,
)

#: 端末表示を偽装しうる文字（C0 / DEL / C1）。診断のメッセージ・hint に混ざると、
#: ANSI エスケープで既存の行を消したり、改行で偽の診断行を差し込んだりできる（S6）。
#: 段 2 のモデル検証でも弾いているが、表示側でも閉じる（多重防御）。
_CONTROL_TRANSLATION = {code: f"\\u{code:04x}" for code in [*range(0x20), 0x7F, *range(0x80, 0xA0)]}


def _safe(text: str) -> str:
    """人間向け出力に載せる前に制御文字を可視表現へ置き換える。"""
    return text.translate(_CONTROL_TRANSLATION)


def _collect(paths: list[Path]) -> list[Path]:
    """引数のパス（ファイル / ディレクトリ）から `.jin` を集める。順序は決定的。

    **名指しで渡されたファイルも拡張子を見る**（correctness review D-4）。
    見ないと `jin check README.md` が Markdown を JSON として解析して JIN001 を出し、
    「Jin のファイルとして壊れている」という嘘の診断になる。
    ディレクトリ探索側は元から `*.jin` しか拾わない。
    """
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob("*.jin")))
        elif path.exists():
            if path.suffix != ".jin":
                typer.echo(
                    f"'.jin' ではありません: {path}"
                    "（Jin が読むのは拡張子 .jin のファイルだけです）",
                    err=True,
                )
                raise typer.Exit(code=2)
            found.append(path)
        else:
            typer.echo(f"ファイルがありません: {path}", err=True)
            raise typer.Exit(code=2)
    return sorted(dict.fromkeys(found), key=str)


def _default_paths(paths: list[Path] | None) -> list[Path]:
    return paths if paths else [Path(".")]


def _format_human(diagnostic: Diagnostic) -> str:
    start = diagnostic.range.start
    head = (
        f"{_safe(diagnostic.file)}:{start.line}:{start.col}: "
        f"{diagnostic.severity} {diagnostic.code}"
    )
    body = f"{head}: {_safe(diagnostic.message)}"
    if diagnostic.hint:
        body += f"\n  hint: {_safe(diagnostic.hint)}"
    body += f"\n  pointer: {_safe(diagnostic.pointer) or '(root)'}"
    return body


def _run_checks(paths: list[Path], resolve: bool) -> list[CheckResult]:
    # `--resolve` を渡したときだけ、実際に import する解決器を注入する。
    # `jin_core` はこの実装を知らない（security review S1 / jin_cli.resolver の docstring）。
    resolver = ImportResolver() if resolve else None
    out: list[CheckResult] = []
    for path in _collect(paths):
        try:
            out.append(check_file(path, resolver=resolver))
        except JinReadError as exc:
            typer.echo(_safe(str(exc)), err=True)
            raise typer.Exit(code=2) from exc
    return out


class WriteRefused(Exception):
    """安全に書けないので書き込みを拒む。`fmt` は診断として扱う（トレースバックを出さない）。"""


class AtomicWriteUnavailable(WriteRefused):
    """ディレクトリに書けないので原子的な差し替えができない（security review N2）。

    `tempfile.mkstemp` と `os.replace` は**ファイルではなくディレクトリ**の書き込み権を要求する。
    読み取り専用ディレクトリの中にある書き込み可能なファイルはこの経路では整形できない。
    """


class SymlinkWriteRefused(WriteRefused):
    """書き込み先がシンボリックリンクだった（security review R-1 / S12）。"""


class ContentLostOnWrite(WriteRefused):
    """非原子的な書き込みの**途中で**失敗し、元の内容が失われた（security review V-1）。

    `_write_in_place` は `O_TRUNC` で開くので、開けた時点で元の内容は消えている。
    そのあとの書き込みが失敗すると、ファイルは中途半端（多くは 0 バイト）になる。
    「書き込めません」では「何も書かれなかった」と読めてしまうため、
    **内容が失われたこと**と**やるべきこと（バックアップからの復元）**を名指しで伝える。
    """


#: `errno` を利用者向けの言葉にする（security review T-1）。
#: 「書き込めません（[Errno 28] No space left on device）」だけでは、何を直せばいいのか
#: 伝わらない。ここに無い errno は `strerror` をそのまま出す（捏造しない）。
_WRITE_ERRNO_HINTS: dict[int, str] = {
    errno.ENOSPC: "ディスクの空き容量がありません",
    errno.EDQUOT: "ディスク使用量の上限に達しています",
    errno.ENOENT: "書き込む直前にファイルが消えました",
    errno.EROFS: "読み取り専用のファイルシステムです",
    errno.EIO: "入出力エラーが起きました",
}


def _describe_write_failure(exc: OSError) -> str:
    """`errno` を利用者向けの一文にする。表に無い `errno` は `strerror` をそのまま出す。"""
    hint = _WRITE_ERRNO_HINTS.get(exc.errno or -1)
    return f"{hint}（{exc.strerror}）" if hint else str(exc.strerror or exc)


def _classify_write_failure(exc: OSError, path: Path) -> WriteRefused:
    """`OSError` を診断にできる例外へ変える（security review T-1）。

    **`PermissionError` だけを退避可能として扱う。** ディレクトリに書けないだけなら
    直接書き込みで救えるが（N2）、容量不足や「書く直前に消えた」で退避すると、
    `_write_in_place` が `O_TRUNC` で**元の内容を消してから**同じ理由で失敗しうる。
    退避が被害を広げる側の失敗は退避させない。

    S5 → N2 → T-1 と 3 度出た同型の欠陥（`PermissionError` 以外の `OSError` が
    未捕捉トレースバックになる）を、ここで型として閉じる。
    """
    _ = path  # 文言にパスは入れない。表示側（fmt）が付けるので二重になる（V-1）。
    detail = _describe_write_failure(exc)
    if isinstance(exc, PermissionError):
        return AtomicWriteUnavailable(detail)
    return WriteRefused(detail)


def _write_in_place(path: Path, text: str) -> None:
    """既存ファイルへ直接書き込む（原子的ではない）。

    `_write_atomically` が使えないときの退避路。**黙って諦めない**ための経路であり、
    呼び出し側が必ず警告を出す（decision-conformance.md §2.11）。

    **`os.O_NOFOLLOW` でシンボリックリンクを辿らない**（security review R-1）。
    `path.open("w")` はリンクを辿るので、`fmt` 側の事前 `is_symlink()` 判定と
    書き込みの間の窓（TOCTOU）で、対象ディレクトリの外のファイルを書き換えられる。
    事前判定は**外せる**ガードなので、ここではカーネルに拒ませる（競合が無い）。
    `getattr(os, "O_NOFOLLOW", 0)` のような握り潰しはしない。0 に落ちると
    防御が黙って消えるため。

    `O_CREAT` はファイルが競合で消えた場合にしか効かない。モードは `0o666`（umask 適用）を
    渡すが、通常経路（ファイルが在る）ではモード引数は無視される。
    改行は変換しない（`newline=""` / correctness review D-2）。

    guard: _write_in_place -> os.O_NOFOLLOW
    """
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SymlinkWriteRefused(
                f"シンボリックリンクなので書き込みを拒みました: {path}"
            ) from exc
        # ELOOP 以外（ENOENT: 競合で消えた / EACCES など）はリンクの話ではないので基底で投げる。
        raise WriteRefused(f"書き込みを開けません: {exc.strerror}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except OSError as exc:
        # 書き込み中の容量不足など（T-1）。ここまで来ると元の内容は `O_TRUNC` で
        # 既に消えているので、**失われたこと**まで含めて知らせる（V-1）。
        raise ContentLostOnWrite(
            f"原子的でない書き込みの途中で失敗したため、ファイルの内容が失われています。"
            f"バックアップから復元してください（{_describe_write_failure(exc)}）"
        ) from exc


def _write_atomically(path: Path, text: str) -> None:
    """同じディレクトリに一時ファイルを作ってから `os.replace` で差し替える。

    直接 `write_text` すると、書き込み中に落ちたときに**内容が切り詰められたファイル**が
    残る（security review S11）。`os.replace` は同一ファイルシステム内で原子的。
    改行は変換しない（`newline=""`）。正準形は LF 固定であり、実行環境によって
    CRLF に変換されると正準形とバイト一致しなくなる（correctness review D-2）。

    **元ファイルのパーミッションを引き継ぐ**。`mkstemp` は 0600 で作り `os.replace` は
    置き換える**側**のモードを持ち込むので、コピーしないと group / other の読み取りビットが
    黙って外れる（security review N1。git は実行ビット以外のモードを追跡しないので差分にも出ない）。

    ディレクトリに書けないときは `AtomicWriteUnavailable` を投げる（N2）。

    `shutil.copymode` は `st_mode & 0o7777` を丸ごと引き継ぐので setuid / setgid /
    sticky も残る。`.jin` にそれらが付いている状況は想定外だが、**引き継ぐ側は元より
    権限を広げない**ので、外すよりこちらが安全側。

    シンボリックリンクについて（security review R-1 の確認結果）:
    この経路には**リンク先へ書き抜ける窓は無い**。`mkstemp` は `O_CREAT | O_EXCL` で
    新しい名前を作るのでリンクを辿らず、`os.replace` は**リンクの実体（名前）のほうを**
    置き換えるので、リンク先のファイルには一切触れない。
    残るのは「シンボリックリンクだった `.jin` が黙って通常ファイルに化ける」ことだけで、
    これは境界越えではなく S12 の方針違反。`os.replace` の直前に `lstat` で拒む
    （このチェックは競合しうるが、負けても起きるのはリンクの置き換えだけで、
    リンク先が書き換わることはない）。

    **この判定は `Path(...).is_symlink` で書くこと**（security review 点 3 の訂正）。
    退避路の回帰テストは `monkeypatch.setattr(Path, "is_symlink", ...)` で
    `Path.is_symlink` を丸ごと殺し、`_write_in_place` の `O_NOFOLLOW` だけが残った
    状態を作って検査する。ここを `os.path.islink()` に書き換えると
    monkeypatch が効かなくなり、**`O_NOFOLLOW` を消す変異が捕まらなくなる**。
    「`os.replace` の前か後か」という配置は効いておらず、効いているのは
    `Path.is_symlink` を使っていることのほうである（reviewer が実測で確認）。

    `OSError` の扱い（security review T-1）: `PermissionError` 以外
    （容量不足 / 書く直前の削除 / 読み取り専用 FS）も `_classify_write_failure` で
    診断にできる例外へ変える。素通しすると `fmt` が `WriteRefused` しか捕まえないため
    トレースバックが表に出る。

    guard: _write_atomically -> Path(path).is_symlink
    """
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
    except OSError as exc:
        raise _classify_write_failure(exc, path) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        shutil.copymode(path, temporary)
        # `Path(...).is_symlink` であること自体が意味を持つ（下の docstring 参照）。
        if Path(path).is_symlink():
            raise SymlinkWriteRefused(f"シンボリックリンクなので書き込みを拒みました: {path}")
        os.replace(temporary, path)
    except OSError as exc:
        Path(temporary).unlink(missing_ok=True)
        raise _classify_write_failure(exc, path) from exc
    except BaseException:
        # `KeyboardInterrupt` / `SystemExit` はここで**握り潰さず**再送出する（S2 の教訓）。
        # 一時ファイルの後始末だけを行う。`SymlinkWriteRefused` もここを通る。
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_canonical(path: Path, text: str) -> str | None:
    """正準形を書き戻す。原子的に書けなかったときは理由の文言を返す。

    ディレクトリに書けないだけでファイル自体は書ける場合は**直接書き込みへ退避する**。
    ここで諦めると、修正ラウンド 1 より前は整形できていたケースが整形できなくなる
    （機能後退・security review N2）。原子性は落ちるので必ず警告を出す。

    シンボリックリンクについて（security review R-2 で訂正）:
    **`_collect` はシンボリックリンクを弾かない。** 事前判定は `fmt` 本体の 1 箇所
    （`is_symlink()`）にしか無く、判定と書き込みの間には窓がある（TOCTOU）。
    ここで使う `os.access` もリンクを辿るので、この関数の判定は防御ではない。
    実際の防御は下位の 2 つで、どちらも競合しない。**主張は機械で固定する**（下記）。

    - `_write_in_place` が `os.O_NOFOLLOW` でカーネルに拒ませる（R-1）
    - `_write_atomically` の `os.replace` はリンクの実体を置き換えるだけで
      リンク先には触れない

    したがって `fmt` の事前判定を外しても、リンク先が書き換わることはない。

    guard: _write_in_place -> os.O_NOFOLLOW
    guard: _write_atomically -> os.replace
    guard: fmt -> path.is_symlink
    """
    try:
        _write_atomically(path, text)
    except AtomicWriteUnavailable as exc:
        if not os.access(path, os.W_OK):
            raise
        _write_in_place(path, text)
        return (
            f"{path}: ディレクトリに書けないため原子的に差し替えできませんでした。"
            f"直接書き込みました（中断すると内容が壊れる可能性があります）: {exc}"
        )
    return None


@app.command()
def check(
    paths: Annotated[list[Path] | None, typer.Argument(help="ファイルまたはディレクトリ")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="診断を JSON 配列で出す")] = False,
    resolve: Annotated[
        bool,
        typer.Option(
            "--resolve",
            help=(
                "Python 参照を実際に import して JIN040 を検査する。"
                "【危険】import は対象モジュールのトップレベルを実行する。"
                "信頼できる .jin にだけ使うこと"
            ),
        ),
    ] = False,
) -> None:
    """診断（JSON 構文・スキーマ・意味）。error があれば exit 1。"""
    results = _run_checks(_default_paths(paths), resolve)
    diagnostics = [d for r in results for d in r.diagnostics]

    if json_output:
        typer.echo(
            json.dumps([d.to_json_dict() for d in diagnostics], ensure_ascii=False, indent=2)
        )
    else:
        for diagnostic in diagnostics:
            typer.echo(_format_human(diagnostic))
        errors = sum(1 for d in diagnostics if d.severity == "error")
        warnings = len(diagnostics) - errors
        typer.echo(
            f"{len(results)} ファイル / error {errors} 件 / warning {warnings} 件",
            err=True,
        )

    raise typer.Exit(code=1 if has_error(diagnostics) else 0)


@app.command()
def fmt(
    paths: Annotated[list[Path] | None, typer.Argument(help="ファイルまたはディレクトリ")] = None,
    check_only: Annotated[
        bool,
        typer.Option("--check", help="書き換えずに差分の有無だけを見る（差分があれば exit 1）"),
    ] = False,
) -> None:
    """正準形へ正規化する。`--check` は差分があれば exit 1。"""
    targets = _collect(_default_paths(paths))
    changed: list[Path] = []
    failed: list[Path] = []
    # 書き込みに失敗したものは `failed` と分ける（security review V-1）。
    # 「診断を先に直してください」は診断由来の失敗にしか当てはまらず、
    # ディスク由来の失敗に付けると「`.jin` の中身を直せばよい」と誤導する。
    unwritable: list[Path] = []
    damaged: list[Path] = []
    skipped: list[Path] = []
    warnings: list[str] = []

    for path in targets:
        if path.is_symlink():
            # シンボリックリンクを追うと、対象ディレクトリの外にあるファイルを書き換える
            # （security review S12）。整形はせず、飛ばしたことを必ず知らせる。
            #
            # **この判定は利便性であって防御の本体ではない**（security review R-1 / R-2）。
            # 判定と書き込みの間には窓があり（TOCTOU）、`_collect` にもフィルタは無い。
            # 実際の防御は競合しない下位の 2 つ:
            #   guard: _write_in_place -> os.O_NOFOLLOW
            #   guard: _write_atomically -> os.replace
            # ここを外してもリンク先は書き換わらない
            # （`test_fmt_does_not_write_through_a_symlink_on_the_fallback_path` で固定）。
            skipped.append(path)
            continue
        try:
            result = check_file(path)
        except JinReadError as exc:
            typer.echo(_safe(str(exc)), err=True)
            raise typer.Exit(code=2) from exc
        if result.model is None:
            # 構文 / スキーマ違反のファイルはモデルにならないので整形できない。黙って飛ばさない。
            failed.append(path)
            for diagnostic in result.diagnostics:
                typer.echo(_format_human(diagnostic), err=True)
            continue
        try:
            canonical = dumps(result.model)
        except ValueError as exc:
            # 正準形にできない値（孤立サロゲートなど・correctness review D-1）。
            failed.append(path)
            typer.echo(f"{_safe(str(path))}: 正準形にできません（{_safe(str(exc))}）", err=True)
            continue
        current = read_source(path)
        if canonical == current:
            continue
        changed.append(path)
        if not check_only:
            try:
                warning = _write_canonical(path, canonical)
            except ContentLostOnWrite as exc:
                # 書き始めたあとで失敗した。**元の内容は既に無い**（V-1）。
                changed.pop()
                damaged.append(path)
                typer.echo(f"{_safe(str(path))}: {_safe(str(exc))}", err=True)
                continue
            except WriteRefused as exc:
                # 書けない（ファイルにもディレクトリにも権限が無い / 書き込み先が
                # シンボリックリンクだった / 容量不足）。ここへ来る経路では
                # **元の内容は無傷**である。診断として扱い、
                # トレースバックを表に出さない（security review S5 / R-1 と同じ経路）。
                changed.pop()
                unwritable.append(path)
                typer.echo(
                    f"{_safe(str(path))}: 書き込めません"
                    f"（ファイルの内容は元のままです: {_safe(str(exc))}）",
                    err=True,
                )
                continue
            if warning is not None:
                warnings.append(warning)

    for path in changed:
        typer.echo(f"{'差分あり' if check_only else '整形しました'}: {path}")
    for path in skipped:
        typer.echo(f"シンボリックリンクなので整形しません: {path}", err=True)
    for warning in warnings:
        typer.echo(_safe(warning), err=True)
    if failed:
        typer.echo(f"整形できませんでした（診断を先に直してください）: {len(failed)} 件", err=True)
    if unwritable:
        typer.echo(
            f"書き込めませんでした（ファイルの内容は元のままです）: {len(unwritable)} 件",
            err=True,
        )
    if damaged:
        # 直すべきは `.jin` の中身ではない。やるべきことを名指しで書く（V-1）。
        typer.echo(
            f"**書き込みの途中で失敗し、ファイルの内容が失われました。"
            f"バックアップから復元してください**: {len(damaged)} 件",
            err=True,
        )

    if failed or unwritable or damaged or (check_only and changed):
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


@app.command()
def schema() -> None:
    """JSON Schema を標準出力に書く。`schemas/jin.schema.json` とバイト一致する。"""
    sys.stdout.write(render_schema())


@app.command()
def dump(file: Annotated[Path, typer.Argument(help="対象の .jin")]) -> None:
    """モデル JSON と pointer→range 対応表を出す。"""
    if not file.exists():
        typer.echo(f"ファイルがありません: {file}", err=True)
        raise typer.Exit(code=2)
    if file.is_file() and file.suffix != ".jin":
        # `_collect` と同じ規則（correctness review D-4）。dump は `_collect` を通らないので
        # ここにも置く。片方だけ塞ぐと `jin dump README.md` が残る。
        typer.echo(
            f"'.jin' ではありません: {file}（Jin が読むのは拡張子 .jin のファイルだけです）",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        result = check_file(file)
    except JinReadError as exc:
        typer.echo(_safe(str(exc)), err=True)
        raise typer.Exit(code=2) from exc
    if result.model is None or result.table is None:
        for diagnostic in result.diagnostics:
            typer.echo(_format_human(diagnostic), err=True)
        typer.echo("モデルを作れないため dump できません", err=True)
        raise typer.Exit(code=1)

    payload = {
        "file": str(file),
        # 正準形 writer と同じ「既定値を出さない」表現にそろえる（json.loads で素の値に戻す）。
        "model": json.loads(dumps(result.model)),
        "pointers": {
            pointer: range_.to_json_dict()
            for pointer, range_ in sorted(result.table.value_ranges.items())
        },
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover
    app()
