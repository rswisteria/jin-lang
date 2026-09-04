"""CLI（Phase 1: check / fmt / schema / dump）のテスト。"""

from __future__ import annotations

import ast
import errno
import importlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Self

import pytest
from jin_cli import main as main_module
from jin_cli.main import _format_human, app
from jin_cli.resolver import ImportResolver
from jin_core.canonical import dumps
from jin_core.diagnostics import Diagnostic, Position, Range
from jin_core.model import JinFile
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "errors"

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, list(args))


# --------------------------------------------------------------------------------------
# Phase 2 までに実装するのは 6 つ（render / lsp / editor は後続 Phase）
# --------------------------------------------------------------------------------------
def test_help_lists_the_implemented_commands() -> None:
    result = run("--help")
    assert result.exit_code == 0
    for name in ("check", "fmt", "schema", "dump", "build", "run"):
        assert name in result.output


@pytest.mark.parametrize("name", ["render", "lsp", "editor"])
def test_later_phase_commands_are_not_defined_yet(name: str) -> None:
    """空実装を置かない（`jin --help` が嘘をつかない）。Phase 3 以降で実装する。"""
    result = run(name, "x.jin")
    assert result.exit_code != 0


# --------------------------------------------------------------------------------------
# jin check
# --------------------------------------------------------------------------------------
def test_check_examples_exits_zero() -> None:
    result = run("check", str(EXAMPLES))
    assert result.exit_code == 0, result.output


def test_check_error_exits_one() -> None:
    result = run("check", str(FIXTURES / "JIN060_root_not_found.jin"))
    assert result.exit_code == 1
    assert "JIN060" in result.output


def test_check_warning_only_exits_zero() -> None:
    """JIN070 は warning。error が無ければ exit 0（要件書 §5「error があれば exit 1」）。"""
    result = run("check", str(FIXTURES / "JIN070_await_not_in_tools.jin"))
    assert result.exit_code == 0
    assert "JIN070" in result.output


def test_check_json_output_is_an_array_of_diagnostics() -> None:
    result = run("check", "--json", str(FIXTURES / "JIN060_root_not_found.jin"))
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert payload[0]["code"] == "JIN060"
    assert set(payload[0]["range"]["start"]) == {"line", "col"}


def test_check_json_output_is_empty_array_when_clean() -> None:
    result = run("check", "--json", str(EXAMPLES / "researcher" / "researcher.jin"))
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_check_resolve_reports_jin040() -> None:
    path = str(FIXTURES / "JIN040_python_ref_not_importable.jin")
    assert "JIN040" not in run("check", path).output
    assert "JIN040" in run("check", "--resolve", path).output


def test_check_human_output_has_file_line_col() -> None:
    result = run("check", str(FIXTURES / "JIN060_root_not_found.jin"))
    assert "JIN060_root_not_found.jin:" in result.output


def test_check_missing_path_exits_nonzero() -> None:
    result = run("check", "no/such/file.jin")
    assert result.exit_code != 0


def test_check_directory_walks_jin_files_in_sorted_order() -> None:
    result = run("check", "--json", str(FIXTURES))
    assert result.exit_code == 1
    files = [d["file"] for d in json.loads(result.output)]
    assert files == sorted(files)


# --------------------------------------------------------------------------------------
# jin fmt
# --------------------------------------------------------------------------------------
def test_fmt_check_on_canonical_examples_exits_zero() -> None:
    result = run("fmt", "--check", str(EXAMPLES))
    assert result.exit_code == 0, result.output


def test_fmt_rewrites_non_canonical_file(tmp_path: Path) -> None:
    source = EXAMPLES / "researcher" / "researcher.jin"
    target = tmp_path / "a.jin"
    document = json.loads(source.read_text(encoding="utf-8"))
    document["circles"][0]["state"][0]["out"] = False  # 既定値なので消えるはず
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert run("fmt", "--check", str(target)).exit_code == 1
    assert run("fmt", str(target)).exit_code == 0
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert run("fmt", "--check", str(target)).exit_code == 0


def test_fmt_refuses_to_write_a_file_with_errors(tmp_path: Path) -> None:
    target = tmp_path / "bad.jin"
    target.write_text(
        (FIXTURES / "JIN001_trailing_comma.jin").read_text(encoding="utf-8"), encoding="utf-8"
    )
    before = target.read_text(encoding="utf-8")
    result = run("fmt", str(target))
    assert result.exit_code == 1
    assert target.read_text(encoding="utf-8") == before
    assert "JIN001" in result.output


# --------------------------------------------------------------------------------------
# jin schema
# --------------------------------------------------------------------------------------
def test_schema_matches_committed_file() -> None:
    result = run("schema")
    assert result.exit_code == 0
    committed = (REPO_ROOT / "schemas" / "jin.schema.json").read_text(encoding="utf-8")
    assert result.output == committed


# --------------------------------------------------------------------------------------
# jin dump
# --------------------------------------------------------------------------------------
def test_dump_outputs_model_and_pointer_table() -> None:
    result = run("dump", str(EXAMPLES / "researcher" / "researcher.jin"))
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert set(payload) == {"file", "model", "pointers"}
    assert payload["model"]["root"] == "Researcher"
    assert "/circles/0/tools/2" in payload["pointers"]
    entry = payload["pointers"]["/circles/0/tools/2"]
    assert set(entry) == {"start", "end"}


def test_dump_pointers_all_resolve_in_model() -> None:
    from jin_core.pointer import resolve_pointer

    for path in sorted(EXAMPLES.glob("*/*.jin")):
        payload = json.loads(run("dump", str(path)).output)
        for pointer in payload["pointers"]:
            resolve_pointer(payload["model"], pointer)


def test_dump_is_stable() -> None:
    path = str(EXAMPLES / "pipeline" / "pipeline.jin")
    assert run("dump", path).output == run("dump", path).output


def test_dump_of_broken_file_exits_one() -> None:
    result = run("dump", str(FIXTURES / "JIN001_trailing_comma.jin"))
    assert result.exit_code == 1


# ======================================================================================
# 修正ラウンド 1 の回帰テスト
# ======================================================================================
MINIMAL = {
    "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
    "version": 1,
    "root": "A",
    "circles": [{"name": "A", "core": "gemini-2.5-flash"}],
}


def write_jin(path: Path, document: dict, *, newline: str = "\n") -> str:
    """正準形で書き出す。`newline` を変えると改行だけが違うファイルになる。"""
    text = dumps(JinFile.model_validate(document))
    if newline != "\n":
        text = text.replace("\n", newline)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return text


# ---- S2: import 先の sys.exit で fail-open しない --------------------------------------
def _install_module(tmp_path: Path, name: str, source: str) -> None:
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()


def test_import_resolver_does_not_let_system_exit_escape(tmp_path: Path) -> None:
    """S2: `except Exception` では `SystemExit` を捕まえられない。

    捕まえ損ねると `jin check --resolve` が**診断ゼロ・exit 0** で終わり、
    CI の赤が緑に化ける（fail-open）。
    """
    _install_module(tmp_path, "jin_fixture_sysexit", "import sys\n\nsys.exit(0)\n")
    try:
        reason = ImportResolver().resolve("jin_fixture_sysexit:f")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("jin_fixture_sysexit", None)
    assert reason is not None
    assert "SystemExit" in reason


def test_check_resolve_reports_a_diagnostic_when_the_module_exits(tmp_path: Path) -> None:
    """S2 の実害を CLI 端で固定する。"""
    _install_module(tmp_path, "jin_fixture_sysexit_cli", "import sys\n\nsys.exit(0)\n")
    document = json.loads(json.dumps(MINIMAL))
    document["circles"][0]["tools"] = [
        {"name": "t", "kind": "tool", "ref": "jin_fixture_sysexit_cli:f"}
    ]
    path = tmp_path / "a.jin"
    write_jin(path, document)
    try:
        result = run("check", "--resolve", str(path))
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("jin_fixture_sysexit_cli", None)
    # JIN040 は warning なので exit は 0 のまま。問題は「診断が 1 件も出ない」ことだった。
    assert "JIN040" in result.output
    assert "SystemExit" in result.output


def test_import_resolver_reports_a_module_that_raises(tmp_path: Path) -> None:
    _install_module(tmp_path, "jin_fixture_raises", "raise RuntimeError('boom')\n")
    try:
        reason = ImportResolver().resolve("jin_fixture_raises:f")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("jin_fixture_raises", None)
    assert reason is not None
    assert "RuntimeError" in reason


def test_jin_core_never_imports_importlib() -> None:
    """S1: `jin_core` のどのモジュールも `importlib` を import しないこと。

    文字列検索ではなく AST で見る（docstring の説明文に反応しないため）。
    """
    core = REPO_ROOT / "packages" / "jin-core" / "src" / "jin_core"
    offenders: list[str] = []
    for module in sorted(core.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "importlib" or name.startswith("importlib.") for name in names):
                offenders.append(f"{module.name}:{node.lineno}")
    assert offenders == []


# ---- S6: 人間向け出力への制御文字インジェクション --------------------------------------
def test_human_output_escapes_control_characters() -> None:
    """S6: メッセージに混ざった ANSI エスケープや改行で表示を偽装させない。"""
    diagnostic = Diagnostic(
        file="a.jin\x1b[2K",
        pointer="/circles/0",
        range=Range(Position(1, 1), Position(1, 2)),
        code="JIN010",
        severity="error",
        message="x\x1b[31m\ny.jin:1:1: error JIN999: 偽の行",
        hint="h\x07",
    )
    rendered = _format_human(diagnostic)
    assert "\x1b" not in rendered
    assert "\x07" not in rendered
    assert "\\u001b" in rendered
    # 本文の改行で行を増やさない（hint / pointer の 2 行だけ）。
    assert len(rendered.splitlines()) == 3


def test_human_output_of_a_file_with_control_characters_in_its_name(tmp_path: Path) -> None:
    """S6: ファイル名経由の注入も塞ぐ。"""
    path = tmp_path / "a\x1b[2Kb.jin"
    path.write_text("{", encoding="utf-8")
    result = run("check", str(path))
    assert result.exit_code == 1
    assert "\x1b" not in result.output


# ---- S5: I/O 例外を診断・使い方エラーへ落とす -------------------------------------------
def test_dump_on_a_directory_exits_two_without_a_traceback(tmp_path: Path) -> None:
    """S5: `IsADirectoryError` のトレースバックを表に出さない。

    修正前は `check_file` の `read_text` が素の `IsADirectoryError` を投げ、
    typer がトレースバック（環境変数やパスつき）を表示していた。
    """
    directory = tmp_path / "adir.jin"
    directory.mkdir()
    result = run("dump", str(directory))
    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "読み込めません" in result.output


def test_check_on_a_non_utf8_file_reports_jin001(tmp_path: Path) -> None:
    """S5: UTF-8 として読めないファイルは診断（JIN001）にする。"""
    path = tmp_path / "sjis.jin"
    path.write_bytes('{"root": "あ"}'.encode("shift_jis"))
    result = run("check", str(path))
    assert result.exit_code == 1
    assert "JIN001" in result.output
    assert "UTF-8" in result.output


def test_typer_does_not_show_locals_in_tracebacks() -> None:
    """S5: 例外が出たときに環境変数やパスをトレースバックへ載せない。"""
    assert app.pretty_exceptions_show_locals is False


# ---- D-1: 孤立サロゲート -----------------------------------------------------------------
def test_fmt_on_a_lone_surrogate_reports_a_diagnostic_instead_of_crashing(tmp_path: Path) -> None:
    """D-1: 修正前は `jin fmt` が UnicodeEncodeError で落ちていた。"""
    path = tmp_path / "surrogate.jin"
    path.write_text(
        '{"$schema": "https://x/", "version": 1, "root": "\\ud800", "circles": []}\n',
        encoding="utf-8",
    )
    result = run("fmt", str(path))
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "JIN002" in result.output


# ---- D-2: CRLF ---------------------------------------------------------------------------
def test_fmt_check_detects_a_crlf_file(tmp_path: Path) -> None:
    """D-2: 改行を LF に畳んで比較すると「差分なし」と嘘をつく。"""
    path = tmp_path / "crlf.jin"
    write_jin(path, MINIMAL, newline="\r\n")
    raw_before = path.read_bytes()
    assert b"\r\n" in raw_before

    result = run("fmt", "--check", str(path))
    assert result.exit_code == 1
    assert "差分あり" in result.output
    assert path.read_bytes() == raw_before  # --check は書き換えない

    assert run("fmt", str(path)).exit_code == 0
    assert b"\r\n" not in path.read_bytes()


def test_fmt_writes_lf_even_on_a_crlf_source(tmp_path: Path) -> None:
    path = tmp_path / "crlf2.jin"
    write_jin(path, MINIMAL, newline="\r\n")
    run("fmt", str(path))
    assert run("fmt", "--check", str(path)).exit_code == 0


# ---- S11: 原子的な書き戻し ----------------------------------------------------------------
def test_fmt_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "messy.jin"
    path.write_text(json.dumps(MINIMAL) + "\n", encoding="utf-8")
    assert run("fmt", str(path)).exit_code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["messy.jin"]


def test_fmt_keeps_the_original_when_the_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S11: 書き込み中に落ちても切り詰められたファイルを残さない。"""
    path = tmp_path / "atomic.jin"
    original = json.dumps(MINIMAL) + "\n"
    path.write_text(original, encoding="utf-8")

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jin_cli.main.os.replace", boom)
    result = run("fmt", str(path))
    assert result.exit_code != 0
    assert path.read_text(encoding="utf-8") == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["atomic.jin"]


# ---- S12: シンボリックリンク --------------------------------------------------------------
def test_fmt_does_not_follow_symlinks(tmp_path: Path) -> None:
    """S12: 対象ディレクトリの外にあるファイルを書き換えない。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "real.jin"
    original = json.dumps(MINIMAL) + "\n"  # 正準形ではない（1 行）
    target.write_text(original, encoding="utf-8")

    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "link.jin").symlink_to(target)

    result = run("fmt", str(inside))
    assert target.read_text(encoding="utf-8") == original
    # 「シンボリックリンク」を含むだけでは緩い。下位のガード（R-1）が出す
    # 「書き込みを拒みました」でも通ってしまい、この事前判定を消しても赤くならない。
    # 事前判定は**飛ばして exit 0** で終わることが持ち味なので、そこまで固定する。
    assert f"シンボリックリンクなので整形しません: {inside / 'link.jin'}" in result.output
    assert result.exit_code == 0, result.output


# ======================================================================================
# 修正ラウンド 2 の回帰テスト
# ======================================================================================
requires_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root はディレクトリのパーミッションを無視するのでこの検査が空虚になる",
)


# ---- N1: 整形でパーミッションを落とさない -------------------------------------------
@pytest.mark.parametrize("mode", [0o664, 0o644, 0o600, 0o666])
def test_fmt_preserves_the_file_mode(tmp_path: Path, mode: int) -> None:
    """N1: `mkstemp` は 0600 で作り `os.replace` は置き換える側のモードを持ち込む。

    コピーしないと group / other の読み取りビットが黙って外れる。
    git は実行ビット以外のモードを追跡しないので差分にも出ない。
    """
    path = tmp_path / "a.jin"
    path.write_text(json.dumps(MINIMAL) + "\n", encoding="utf-8")  # 正準形ではない
    os.chmod(path, mode)

    result = run("fmt", str(path))
    assert result.exit_code == 0
    assert "整形しました" in result.output
    assert stat.S_IMODE(path.stat().st_mode) == mode


def test_fmt_does_not_widen_a_restrictive_mode(tmp_path: Path) -> None:
    """N1 の逆向き: 0600 のファイルを 0644 に広げてしまわないこと。"""
    path = tmp_path / "secret.jin"
    path.write_text(json.dumps(MINIMAL) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    assert run("fmt", str(path)).exit_code == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# ---- N2: 書けないディレクトリ ---------------------------------------------------------
@requires_non_root
def test_fmt_falls_back_to_in_place_write_in_a_read_only_directory(tmp_path: Path) -> None:
    """N2: `mkstemp` / `os.replace` はディレクトリの書き込み権を要求する。

    ディレクトリが読み取り専用でもファイル自体が書けるなら整形できる（修正ラウンド 1 より前の挙動）。
    ここで諦めると機能後退になる。原子性は落ちるので必ず警告を出す。
    """
    directory = tmp_path / "ro"
    directory.mkdir()
    path = directory / "b.jin"
    path.write_text(json.dumps(MINIMAL) + "\n", encoding="utf-8")
    canonical = dumps(JinFile.model_validate(MINIMAL))
    os.chmod(directory, 0o555)
    try:
        result = run("fmt", str(path))
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert result.exit_code == 0, result.output
        assert path.read_text(encoding="utf-8") == canonical
        assert "原子的に差し替えできません" in result.output
        # 退避路でも一時ファイルを残さない。
        assert sorted(p.name for p in directory.iterdir()) == ["b.jin"]
    finally:
        os.chmod(directory, 0o755)


@requires_non_root
def test_fmt_reports_a_diagnostic_when_neither_file_nor_directory_is_writable(
    tmp_path: Path,
) -> None:
    """N2: 書けないなら**診断として**落とす。トレースバックを表に出さない（S5 と同じ経路）。"""
    directory = tmp_path / "ro2"
    directory.mkdir()
    path = directory / "c.jin"
    path.write_text(json.dumps(MINIMAL) + "\n", encoding="utf-8")
    os.chmod(path, 0o444)
    os.chmod(directory, 0o555)
    try:
        result = run("fmt", str(path))
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert result.exit_code == 1
        assert "書き込めません" in result.output
        assert "Traceback" not in result.output
    finally:
        os.chmod(directory, 0o755)
        os.chmod(path, 0o644)


# ---- D-4: `.jin` 以外を名指しで渡されたら受け付けない ---------------------------------
@pytest.mark.parametrize("command", ["check", "fmt"])
def test_named_non_jin_file_is_rejected(tmp_path: Path, command: str) -> None:
    """D-4: `jin check README.md` が Markdown を JSON として読んで JIN001 を出していた。

    「Jin のファイルとして壊れている」という嘘の診断になる。
    """
    path = tmp_path / "README.md"
    path.write_text("# 見出し\n\n本文\n", encoding="utf-8")
    result = run(command, str(path))
    assert result.exit_code == 2
    assert "JIN001" not in result.output
    assert "'.jin' ではありません" in result.output


def test_dump_rejects_a_non_jin_file(tmp_path: Path) -> None:
    """D-4: `dump` は `_collect` を通らないので同じ規則をこちらにも置く。"""
    path = tmp_path / "notes.txt"
    path.write_text("{}", encoding="utf-8")
    result = run("dump", str(path))
    assert result.exit_code == 2
    assert "'.jin' ではありません" in result.output


def test_directory_traversal_still_ignores_non_jin_files(tmp_path: Path) -> None:
    """D-4: ディレクトリ探索側の挙動は変えない（`.jin` 以外は元から拾わない）。"""
    (tmp_path / "keep.md").write_text("# x\n", encoding="utf-8")
    write_jin(tmp_path / "a.jin", MINIMAL)
    result = run("check", str(tmp_path))
    assert result.exit_code == 0
    assert "1 ファイル" in result.output


# ---- BOM: CLI 端（correctness review E-5 の残件）---------------------------------------
def _write_bom(path: Path, document: dict) -> None:
    body = dumps(JinFile.model_validate(document))
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))


def test_check_reports_a_bom_file(tmp_path: Path) -> None:
    """E-5: BOM 付きファイルを check すると JIN001 と BOM の語が出ること。"""
    path = tmp_path / "bom.jin"
    _write_bom(path, MINIMAL)
    result = run("check", str(path))
    assert result.exit_code == 1
    assert "JIN001" in result.output
    assert "BOM" in result.output


def test_fmt_check_treats_a_bom_file_as_not_canonical(tmp_path: Path) -> None:
    """E-5: BOM 付きは正準形ではない。`--check` が「差分なし」で通してはいけない。"""
    path = tmp_path / "bom2.jin"
    _write_bom(path, MINIMAL)
    raw_before = path.read_bytes()
    result = run("fmt", "--check", str(path))
    assert result.exit_code == 1
    assert path.read_bytes() == raw_before


def test_fmt_does_not_silently_strip_a_bom(tmp_path: Path) -> None:
    """E-5: `jin fmt` は頼まれていないバイト列の変更をしない。BOM は診断にして書き手に直させる。"""
    path = tmp_path / "bom3.jin"
    _write_bom(path, MINIMAL)
    raw_before = path.read_bytes()
    result = run("fmt", str(path))
    assert result.exit_code == 1
    assert path.read_bytes() == raw_before
    assert "整形できませんでした" in result.output


# ======================================================================================
# 修正ラウンド 3 の回帰テスト
# ======================================================================================
# R-1: `_write_in_place` の symlink TOCTOU。
#
# `fmt` 本体の事前 `is_symlink()`（main.py）は**判定と書き込みの間に窓がある**ので防御ではない。
# 以下のテストは、その事前判定を**外した状態**でもリンク先が書き換わらないことを固定する。
# ガードの二重化そのものが要点なので、片方を消しても守られることを見る。


def _victim_and_symlink(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """`work/swapped.jin -> ../out/victim.jin` を作る。victim は正準形でない Jin 文書。

    正準形でないと `fmt` が書き込みまで進まないので、攻撃の再現にならない。
    """
    out = tmp_path / "out"
    out.mkdir()
    victim = out / "victim.jin"
    original = json.dumps(MINIMAL) + "\n"  # 1 行なので正準形ではない
    victim.write_text(original, encoding="utf-8")

    work = tmp_path / "work"
    work.mkdir()
    swapped = work / "swapped.jin"
    swapped.symlink_to(victim)
    return work, victim, swapped, original


def test_write_in_place_refuses_a_symlink(tmp_path: Path) -> None:
    """R-1: 最下層の `_write_in_place` 自身がリンクを拒む（カーネルの `O_NOFOLLOW`）。

    `path.open("w")` はリンクを辿るので、ここが素通りすると上位のガードを外した瞬間に
    対象ディレクトリの外が書き換わる。
    """
    from jin_cli.main import SymlinkWriteRefused, _write_in_place

    _work, victim, swapped, original = _victim_and_symlink(tmp_path)
    with pytest.raises(SymlinkWriteRefused):
        _write_in_place(swapped, "書き換えた\n")
    assert victim.read_text(encoding="utf-8") == original
    assert swapped.is_symlink()


def test_fmt_does_not_write_through_a_symlink_without_the_upfront_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-1: `fmt` の事前 `is_symlink()` を外しても、原子的書き込みはリンク先へ抜けない。

    `mkstemp` は `O_CREAT | O_EXCL` でリンクを辿らず、`os.replace` はリンクの実体
    （名前）を置き換えるだけでリンク先には触れない。加えて `os.replace` の直前の
    `lstat` 判定で拒む（S12 の方針を守る）。
    """
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    _work, victim, swapped, original = _victim_and_symlink(tmp_path)
    result = run("fmt", str(swapped))
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert victim.read_text(encoding="utf-8") == original, "リンク先が書き換わった"
    assert "Traceback" not in result.output
    # Python 側のガードを全部殺した状態で残る影響は「リンクが通常ファイルに化ける」ことだけ。
    # 境界越え（リンク先の書き換え）は `os.replace` の性質そのものによって起きない。
    # `monkeypatch` で `Path.is_symlink` を殺しているので `os.path.islink` で見る。
    assert not os.path.islink(swapped)


def test_write_atomically_refuses_a_symlink(tmp_path: Path) -> None:
    """R-1: 原子的経路も**リンクを通常ファイルに化けさせない**（S12 の方針を守る）。

    `os.replace` はリンク先に書かないので境界越えは起きないが、リンクの実体は
    置き換わる。それも拒む（実測: このガードを外すと `swapped.jin` が通常ファイルになり、
    リンク先は元のまま）。この判定は競合しうるが、負けても起きるのはリンクの置き換えだけ。
    """
    from jin_cli.main import SymlinkWriteRefused, _write_atomically

    _work, victim, swapped, original = _victim_and_symlink(tmp_path)
    with pytest.raises(SymlinkWriteRefused):
        _write_atomically(swapped, "書き換えた\n")
    assert victim.read_text(encoding="utf-8") == original
    assert swapped.is_symlink()
    # 一時ファイルを残さない。
    assert sorted(p.name for p in swapped.parent.iterdir()) == ["swapped.jin"]


@requires_non_root
def test_fmt_does_not_write_through_a_symlink_on_the_fallback_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-1: 事前ガードを外し、**退避路（`_write_in_place`）まで到達させて**も守られる。

    ディレクトリを 0o555 にすると `mkstemp` が落ちて `AtomicWriteUnavailable` になり、
    `os.access` はリンクを辿るので「ファイルは書ける」と判定され、退避路へ進む。
    修正前はここでリンク先が実際に書き換わった。
    """
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    work, victim, swapped, original = _victim_and_symlink(tmp_path)
    os.chmod(work, 0o555)
    try:
        result = run("fmt", str(swapped))
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert victim.read_text(encoding="utf-8") == original, "リンク先が書き換わった"
        # 退避路まで到達したうえで拒んだこと（手前で別の理由で落ちていないこと）を示す。
        assert "シンボリックリンクなので書き込みを拒みました" in result.output
        assert result.exit_code == 1
        assert "Traceback" not in result.output
    finally:
        os.chmod(work, 0o755)


def test_collect_does_not_filter_symlinks(tmp_path: Path) -> None:
    """R-2: docstring が誤って `_collect` にガードがあると書いていた。実際は無い。

    「どこにガードがあるか」を思い込みではなくテストで固定しておく。
    `_collect` は `.jin` を集めるだけで、シンボリックリンクを落とさない。
    """
    from jin_cli.main import _collect

    _work, _victim, swapped, _original = _victim_and_symlink(tmp_path)
    assert _collect([swapped]) == [swapped]
    assert _collect([swapped.parent]) == [swapped]


# ---- R-2: 安全宣言そのものを機械で固定する -------------------------------------------
#: `guard: <関数名> -> <トークン>` の記法（`jin_cli/main.py` のモジュール docstring 参照）。
#: 散文の説明行（`guard: <関数名> -> ...`）は `<` で始まるので、この正規表現に当たらない。
GUARD_CLAIM = re.compile(r"guard:\s*([A-Za-z_][A-Za-z0-9_]*)\s*->\s*(\S+)")

#: 見つかるべき主張の最小件数。走査が壊れて 0 件になると検査が空虚になる。
MINIMUM_GUARD_CLAIMS = 4


def _function_code_without_docstring(tree: ast.Module, name: str) -> str | None:
    """関数の**実コード**を返す。docstring とコメントは含めない。

    `ast.unparse` はコメントを落とすので、docstring のノードだけ外せば
    「主張の文言そのものを見て通ってしまう」ことが無くなる。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return "\n".join(ast.unparse(statement) for statement in body)
    return None


class GuardTokenTooLoose(Exception):
    """`guard:` のトークンが構造を持たず、部分一致でたまたま当たる形（security review U-1 / E-B）。"""


def _guard_satisfied(tree: ast.Module, function_name: str, token: str) -> bool:
    """関数の実コードに `token` が**式として**現れるか（U-1 / E-B）。

    素の部分文字列一致だと `guard: fmt -> os` や `guard: fmt -> path` が素通りする
    （`os` が `diagnostic` の中の "os" に当たる、など。reviewer が実測）。
    AST どうしで突き合わせ、さらに 2 つの縛りを入れる:

    1. トークンが裸の名前（`os` / `path`）なら**主張として認めない**。ガードは属性参照か
       呼び出しであるはず。単なる変数名は「そこに何かがある」以上のことを言っていない
    2. 一致したノードが外側の属性参照の**土台**（`a.b.c` の `a.b`）である場合は数えない。
       部分的な名指しで通してしまうため
    """
    code = _function_code_without_docstring(tree, function_name)
    if code is None:
        return False
    wanted = ast.parse(token, mode="eval").body
    if isinstance(wanted, ast.Name):
        raise GuardTokenTooLoose(
            f"guard: のトークン {token!r} が裸の名前。属性参照か呼び出しで書くこと"
        )
    body = ast.parse(code)
    bases = {id(node.value) for node in ast.walk(body) if isinstance(node, ast.Attribute)}
    target = ast.dump(wanted)
    return any(ast.dump(node) == target and id(node) not in bases for node in ast.walk(body))


def test_guard_claims_point_at_real_guards() -> None:
    """R-2: 「どこで symlink を弾いているか」という主張を docstring に書きっぱなしにしない。

    R-2 の欠陥は「`_collect` が弾いている」という**実装と乖離した安全宣言**だった。
    docstring を直すだけでは、次に誰かが同じ種類の嘘を書ける。
    `guard: <関数名> -> <トークン>` の名指し先に、そのトークンが**実コードとして**
    在ることをここで検査する。名指しが嘘なら（あるいは関数が消えたら）落ちる。

    wiring review W-02 / N-01 と同型の対処（主張の存在ではなく、主張が落ちることを見る）。
    """
    from jin_cli import main as main_module

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    claims = GUARD_CLAIM.findall(source)
    assert len(claims) >= MINIMUM_GUARD_CLAIMS, f"guard: の主張が少なすぎる: {claims}"

    for function_name, token in claims:
        assert _function_code_without_docstring(tree, function_name) is not None, (
            f"guard: が存在しない関数 {function_name} を名指ししている"
            "（関数を消したか改名したなら主張も直すこと）"
        )
        assert _guard_satisfied(tree, function_name, token), (
            f"{function_name} に {token} が無いのに guard: がそこを名指ししている。"
            "R-2 と同じ「実装と乖離した安全宣言」になっている"
        )


def test_guard_claim_check_looks_at_code_not_at_the_claim_itself() -> None:
    """R-2: 主張の文言そのものを見て通る検査だと、嘘を 1 件も検出できない。

    `guard: _write_in_place -> os.O_NOFOLLOW` という**文字列は docstring にも在る**ので、
    関数のソースを丸ごと見ると常に真になる。`_function_code_without_docstring` が
    docstring を落としていることをここで固定する。
    """
    from jin_cli import main as main_module

    tree = ast.parse(Path(main_module.__file__).read_text(encoding="utf-8"))
    code = _function_code_without_docstring(tree, "_write_in_place")
    assert code is not None
    assert "guard:" not in code, "docstring が落ちていない（主張の自己参照で通ってしまう）"
    assert "os.O_NOFOLLOW" in code, "実コードのほうの O_NOFOLLOW が見えていない"

    # docstring にしかトークンが無い関数は「ガード無し」と判定されること。
    synthetic = ast.parse('def f():\n    """guard: f -> os.O_NOFOLLOW"""\n    return 1\n')
    assert "O_NOFOLLOW" not in (_function_code_without_docstring(synthetic, "f") or "")


# ======================================================================================
# 修正ラウンド 4 の回帰テスト
# ======================================================================================
# T-1: `PermissionError` 以外の `OSError` が未捕捉トレースバックになる。
# S5 → N2 → T-1 と 3 度出た同型の欠陥。CLI から決定的に踏む経路は無いが、
# Phase 4 の LSP では現実的な頻度になるので型として閉じる。


def _noncanonical_file(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "t1.jin"
    original = json.dumps(MINIMAL) + "\n"  # 1 行なので正準形ではない
    path.write_text(original, encoding="utf-8")
    return path, original


@pytest.mark.parametrize(
    ("number", "message", "expected"),
    [
        (errno.ENOSPC, "No space left on device", "ディスクの空き容量がありません"),
        (errno.EROFS, "Read-only file system", "読み取り専用のファイルシステムです"),
        (errno.EIO, "Input/output error", "入出力エラーが起きました"),
    ],
)
def test_fmt_reports_a_diagnostic_when_mkstemp_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, number: int, message: str, expected: str
) -> None:
    """T-1: 一時ファイルを作れない理由が権限以外でも、トレースバックにしない。

    修正前は `except PermissionError` しか無く、`fmt` は `WriteRefused` しか捕まえないため
    `OSError` がそのまま表に出ていた。`errno` の別も利用者に伝える。
    """
    path, original = _noncanonical_file(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError(number, message)

    monkeypatch.setattr(main_module.tempfile, "mkstemp", explode)
    result = run("fmt", str(path))
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert expected in result.output, result.output
    # 退避（直接書き込み）へ落として内容を壊していないこと。
    assert path.read_text(encoding="utf-8") == original


def test_a_full_disk_does_not_fall_back_to_a_truncating_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-1: 容量不足で退避すると `_write_in_place` が `O_TRUNC` で**元の内容を消してから**失敗する。

    退避してよいのは `PermissionError`（ディレクトリに書けないだけ）のときに限る。
    ここが崩れると N2 の救済策が T-1 の被害を広げる側に回る。
    """
    path, original = _noncanonical_file(tmp_path)
    calls: list[str] = []

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(main_module.tempfile, "mkstemp", explode)
    monkeypatch.setattr(main_module, "_write_in_place", lambda *a, **k: calls.append("fallback"))
    result = run("fmt", str(path))
    assert calls == [], "容量不足なのに直接書き込みへ退避した"
    assert path.read_text(encoding="utf-8") == original
    assert result.exit_code == 1


def test_fmt_reports_a_diagnostic_when_the_file_disappears_before_the_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-1: 書き込み直前にファイルが消えても診断にする。一時ファイルも残さない。"""
    path, _original = _noncanonical_file(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(main_module.os, "replace", explode)
    result = run("fmt", str(path))
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "書き込む直前にファイルが消えました" in result.output, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t1.jin"], "一時ファイルが残った"


def test_write_in_place_reports_a_diagnostic_when_the_write_itself_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-1: 退避路の書き込み中の失敗（容量不足など）も診断にする。

    ここまで来ると `O_TRUNC` で元の内容は既に消えているので、**黙って諦めない**。
    """
    path, _original = _noncanonical_file(tmp_path)

    class Exploding:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def write(self, _text: str) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(main_module.os, "fdopen", lambda *a, **k: Exploding())
    with pytest.raises(main_module.WriteRefused, match="ディスクの空き容量がありません"):
        main_module._write_in_place(path, "書き換えた\n")


def test_keyboard_interrupt_still_propagates_from_the_atomic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-1 / S2: `OSError` へ広げても `KeyboardInterrupt` を握り潰さない。

    `except BaseException` は後始末をして**再送出する**だけであること。
    """
    path, _original = _noncanonical_file(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module.os, "replace", explode)
    with pytest.raises(KeyboardInterrupt):
        main_module._write_atomically(path, "書き換えた\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t1.jin"], "一時ファイルが残った"


# ---- U-1 / E-B: 緩いトークンが素通りしないこと -----------------------------------------
@pytest.fixture(scope="module")
def main_tree() -> ast.Module:
    from jin_cli import main as main_module

    return ast.parse(Path(main_module.__file__).read_text(encoding="utf-8"))


@pytest.mark.parametrize("token", ["os", "path", "Path", "text"])
def test_a_bare_name_is_not_accepted_as_a_guard(main_tree: ast.Module, token: str) -> None:
    """U-1 / E-B: `guard: fmt -> os` のような裸の名前は主張として認めない。

    修正前は `token in code` の**素の部分文字列一致**だったので、`os` が `diagnostic` の
    中の "os" に当たって素通りしていた（reviewer が実測）。裸の名前は「そこに何かがある」
    以上のことを言っておらず、ガードの名指しとして意味を成さない。
    """
    with pytest.raises(GuardTokenTooLoose):
        _guard_satisfied(main_tree, "fmt", token)


@pytest.mark.parametrize(
    "token",
    [
        "os.path",  # `os.path.islink(...)` の土台。部分的な名指し
        "shutil.rmtree",  # 実在しない呼び出し
        "os.O_NOFOLLOW",  # `_write_in_place` には在るが `fmt` には無い
    ],
)
def test_a_token_absent_from_the_function_is_rejected(main_tree: ast.Module, token: str) -> None:
    """U-1 / E-B: 構造を持っていても、その関数に無いトークンは通さない。

    `os.path` は `os.path.islink(...)` の土台になっているだけで、それ自体はガードではない。
    外側の属性参照の土台になっているノードは数えない。
    """
    assert not _guard_satisfied(main_tree, "fmt", token)


@pytest.mark.parametrize(
    ("function_name", "token"),
    [
        ("fmt", "path.is_symlink"),
        ("_write_in_place", "os.O_NOFOLLOW"),
        ("_write_atomically", "os.replace"),
        ("_write_atomically", "Path(path).is_symlink"),
    ],
)
def test_a_real_guard_is_accepted(main_tree: ast.Module, function_name: str, token: str) -> None:
    """U-1 / E-B: 締めすぎて本物のガードまで落とさないこと（検査が空虚にならない側の確認）。"""
    assert _guard_satisfied(main_tree, function_name, token)


def test_the_substring_shortcut_would_have_let_a_loose_token_through() -> None:
    """U-1 / E-B: 修正前の照合（素の部分文字列一致）なら通っていたことを示す。

    「直したつもりで実は元から通らなかった」を防ぐため、欠陥の存在自体をここで固定する。
    """
    from jin_cli import main as main_module

    tree = ast.parse(Path(main_module.__file__).read_text(encoding="utf-8"))
    code = _function_code_without_docstring(tree, "fmt")
    assert code is not None
    assert "os" in code, "部分文字列一致なら `guard: fmt -> os` が通っていた"
    assert "path" in code, "部分文字列一致なら `guard: fmt -> path` が通っていた"


def test_a_partial_attribute_name_is_not_accepted_as_a_guard() -> None:
    """U-1 / E-B: `a.b.c` の `a.b` だけを名指しした部分的な主張を通さない。

    現在の `main.py` には入れ子の属性参照（`os.path.islink` のような形）が 1 つも無いので、
    実コードではこの縛りが一度も発火しない。**発火しない縛りは検証できていないのと同じ**なので、
    合成入力で直接固定する。
    """
    tree = ast.parse("def f():\n    return os.path.islink(p)\n")
    assert _guard_satisfied(tree, "f", "os.path.islink")
    assert not _guard_satisfied(tree, "f", "os.path"), "土台だけの名指しが通った"


# ======================================================================================
# 修正ラウンド 5 の回帰テスト
# ======================================================================================
# V-1: 退避路の書き込みが途中で失敗するとファイルが 0 バイトになるのに、それが伝わらない。
# 修正前の実出力（reviewer / 実装者とも CLI 経由で再現）:
#   w/a.jin: 書き込めません（w/a.jin: ディスクの空き容量がありません（No space left on device））
#   整形できませんでした（診断を先に直してください）: 1 件
#   整形後のファイルの中身の長さ: 0 バイト
# 「書き込めません」は「何も書かれなかった」と読め、要約行は「.jin を直せばよい」と誤導する。


class _ExplodingHandle:
    """`write` だけが失敗するファイルハンドル。開くところまでは成功させる（= `O_TRUNC` が効く）。"""

    def __init__(self, handle: object) -> None:
        self._handle = handle

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> bool:
        self._handle.close()  # type: ignore[attr-defined]
        return False

    def write(self, _text: str) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")


@pytest.fixture
def failing_write(monkeypatch: pytest.MonkeyPatch):
    """書き込みモードで開いたハンドルだけを ENOSPC で失敗させる。"""
    real_fdopen = os.fdopen

    def fake(descriptor: int, *args: object, **kwargs: object) -> object:
        handle = real_fdopen(descriptor, *args, **kwargs)  # type: ignore[arg-type]
        if args and args[0] == "w":
            return _ExplodingHandle(handle)
        return handle

    monkeypatch.setattr(main_module.os, "fdopen", fake)


@requires_non_root
def test_fmt_says_the_content_was_lost_when_the_fallback_write_fails(
    tmp_path: Path, failing_write: None
) -> None:
    """V-1: 内容が失われたことと、やるべきこと（復元）を文言として固定する。

    `_write_in_place` は `O_TRUNC` で開くので、開けた時点で元の内容は消えている。
    ここで「書き込めません」とだけ言うのは、起きたことを伝えていない。
    """
    directory = tmp_path / "w"
    directory.mkdir()
    path = directory / "a.jin"
    path.write_text(json.dumps(MINIMAL) + "\n", encoding="utf-8")
    os.chmod(directory, 0o555)
    try:
        result = run("fmt", str(path))
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output
        # 実際に内容が失われていること（この前提が崩れたら文言のほうが嘘になる）。
        assert path.read_bytes() == b""
        # 何が起きたか。
        assert "ファイルの内容が失われています" in result.output, result.output
        # 何をすればよいか。
        assert "バックアップから復元してください" in result.output, result.output
        # 誤導する要約行を出さないこと。直すべきは `.jin` の中身ではない。
        assert "診断を先に直してください" not in result.output, result.output
        # パスが二重に出ないこと（V-1 の問題 3）。
        assert result.output.count(str(path)) == 1, result.output
    finally:
        os.chmod(directory, 0o755)


@requires_non_root
def test_fmt_says_the_content_is_intact_when_it_could_not_start_writing(
    tmp_path: Path,
) -> None:
    """V-1: **書き始める前**に失敗した場合は、内容が無傷であることを言う。

    失われた場合と同じ文言にしてしまうと、無傷のファイルまで復元させることになる。
    2 つの経路の文言がはっきり分かれていることを固定する。
    """
    directory = tmp_path / "ro3"
    directory.mkdir()
    path = directory / "d.jin"
    original = json.dumps(MINIMAL) + "\n"
    path.write_text(original, encoding="utf-8")
    os.chmod(path, 0o444)
    os.chmod(directory, 0o555)
    try:
        result = run("fmt", str(path))
        assert result.exit_code == 1, result.output
        assert "ファイルの内容は元のままです" in result.output, result.output
        assert "失われ" not in result.output, result.output
        assert "診断を先に直してください" not in result.output, result.output
        # パスが二重に出ないこと（V-1 の問題 3）。例外の文言にパスを入れると重複する。
        assert result.output.count(str(path)) == 1, result.output
        assert path.read_text(encoding="utf-8") == original
    finally:
        os.chmod(directory, 0o755)
        os.chmod(path, 0o644)


def test_a_diagnostic_failure_still_says_to_fix_the_diagnostics(tmp_path: Path) -> None:
    """V-1: 診断由来の失敗では従来どおりの要約行が出ること（出し分けの反対側）。"""
    path = tmp_path / "broken.jin"
    path.write_text("{ではない", encoding="utf-8")
    result = run("fmt", str(path))
    assert result.exit_code == 1, result.output
    assert "診断を先に直してください" in result.output, result.output
    assert "失われ" not in result.output, result.output
