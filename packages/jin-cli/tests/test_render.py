"""`jin render`（要件書 §5 / Phase 3）。

書き出しの規約（tmp + `os.replace` / リンクを辿らない / 既存は `--force` 無しで拒む）は
`jin fmt` / `jin build` と同じヘルパを通る。**新しい書き込み経路を作らない。**
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from jin_cli.main import _new_file_mode, app
from typer.testing import CliRunner

from tests.conftest import requires_non_root

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"
PIPELINE = EXAMPLES / "pipeline" / "pipeline.jin"
RESEARCHER = EXAMPLES / "researcher" / "researcher.jin"
TRACE = REPO_ROOT / "tests" / "fixtures" / "traces" / "pipeline-fake.jsonl"
ERRORS = REPO_ROOT / "tests" / "fixtures" / "errors"

runner = CliRunner()


def run(*args: str):
    return runner.invoke(app, ["render", *args])


def test_render_writes_the_svg_to_stdout() -> None:
    result = run(str(PIPELINE))
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("<svg ")
    assert result.stdout.endswith("</svg>\n")


def test_stdout_and_the_output_file_are_byte_identical(tmp_path: Path) -> None:
    """`-o` の書き出しが改行変換などで stdout とずれないこと。"""
    target = tmp_path / "out.svg"
    assert run(str(PIPELINE), "-o", str(target)).exit_code == 0
    assert target.read_bytes() == run(str(PIPELINE)).stdout.encode("utf-8")


@pytest.mark.parametrize("mask", [0o022, 0o002, 0o077])
def test_the_output_file_is_created_with_the_generated_file_mode(tmp_path: Path, mask: int) -> None:
    """新規作成は `jin build` の生成物と**同じ実効モード** = `0o644 & ~umask`。

    `jin build` は `os.open(name, O_CREAT | O_EXCL, 0o644)` で作り、カーネルが umask を
    引く。`mkstemp` + `chmod 0o644` は umask を無視するので、umask 0o077 の利用者が
    `jin render -o` で作った SVG だけが group / other に読めていた（F-S-P3-004 /
    F-V-P3-015: 修正ラウンド 1 でレビューに覆された）。
    """
    previous = os.umask(mask)
    try:
        target = tmp_path / "out.svg"
        assert run(str(PIPELINE), "-o", str(target)).exit_code == 0
        assert target.stat().st_mode & 0o777 == 0o644 & ~mask
    finally:
        os.umask(previous)


def test_the_created_mode_matches_what_jin_build_writes(tmp_path: Path) -> None:
    """「`jin build` にそろえる」を**実測**で固定する（値をハードコードしない）。"""
    previous = os.umask(0o027)
    try:
        built = tmp_path / "built"
        assert runner.invoke(app, ["build", str(PIPELINE), "--out", str(built)]).exit_code == 0
        rendered = tmp_path / "out.svg"
        assert run(str(PIPELINE), "-o", str(rendered)).exit_code == 0
        expected = (built / "Pipeline" / "agent.py").stat().st_mode & 0o777
        assert rendered.stat().st_mode & 0o777 == expected
    finally:
        os.umask(previous)


def test_an_existing_file_is_not_overwritten_without_force(tmp_path: Path) -> None:
    target = tmp_path / "out.svg"
    target.write_text("元の内容\n", encoding="utf-8")
    result = run(str(PIPELINE), "-o", str(target))
    assert result.exit_code == 1
    assert "--force" in result.output
    assert target.read_text(encoding="utf-8") == "元の内容\n"


def test_force_overwrites_and_keeps_the_existing_mode(tmp_path: Path) -> None:
    target = tmp_path / "out.svg"
    target.write_text("元の内容\n", encoding="utf-8")
    target.chmod(0o640)
    assert run(str(PIPELINE), "-o", str(target), "--force").exit_code == 0
    assert target.read_text(encoding="utf-8").startswith("<svg ")
    assert target.stat().st_mode & 0o777 == 0o640


@requires_non_root
def test_a_symlinked_output_is_refused(tmp_path: Path) -> None:
    """リンク先（出力先の外かもしれない）を書き換えない。"""
    outside = tmp_path / "outside.txt"
    outside.write_text("触らない\n", encoding="utf-8")
    link = tmp_path / "out.svg"
    link.symlink_to(outside)
    result = run(str(PIPELINE), "-o", str(link), "--force")
    assert result.exit_code == 1
    assert "シンボリックリンク" in result.output
    # **どのパスが拒まれたか**が出ること。部分文字列だけを見ていたので、R2 で文言から
    # パスが消えた退行を通した（F-C-P3-202）。他の拒否条件と同じ `path: 理由` の形。
    assert str(link) in result.output, result.output
    # パスは 1 回だけ（一層目と render 側の前置で 2 回出さない・F-V-P3-104）
    assert result.output.count(str(link)) == 1, result.output
    # **並び**も固定する。パスの有無だけを見ていたので `理由: path` のまま気づかなかった
    # （F-V-P3-301）。`fmt` / ディレクトリ拒否と同じ `path: 理由` の形。
    assert result.output.startswith(f"{link}: シンボリックリンク"), result.output
    assert outside.read_text(encoding="utf-8") == "触らない\n"


def test_focus_switches_the_expanded_circle() -> None:
    root = run(str(PIPELINE)).stdout
    drafter = run(str(PIPELINE), "--focus", "Drafter").stdout
    assert root != drafter
    assert 'data-jin="/circles/2"' in drafter


def test_an_unknown_focus_exits_two_with_candidates() -> None:
    result = run(str(PIPELINE), "--focus", "Draftr")
    assert result.exit_code == 2
    assert "Drafter" in result.output


def test_upto_without_a_trace_exits_two() -> None:
    result = run(str(PIPELINE), "--upto", "3")
    assert result.exit_code == 2
    assert "--trace" in result.output


def test_a_negative_upto_exits_two() -> None:
    result = run(str(PIPELINE), "--trace", str(TRACE), "--upto", "-1")
    assert result.exit_code == 2


def test_a_trace_highlights_the_fired_elements() -> None:
    result = run(str(PIPELINE), "--trace", str(TRACE), "--upto", "1")
    assert result.exit_code == 0
    assert 'data-jin-fired="1"' in result.stdout
    assert result.stdout.count('data-jin-seq="') == 1


def test_more_upto_means_more_dots() -> None:
    few = run(str(PIPELINE), "--trace", str(TRACE), "--upto", "2").stdout
    many = run(str(PIPELINE), "--trace", str(TRACE), "--upto", "9").stdout
    assert few.count('data-jin-seq="') == 2
    assert many.count('data-jin-seq="') == 9


def test_a_broken_trace_line_exits_two_with_the_line_number(tmp_path: Path) -> None:
    """黙って読み飛ばさない（NFR-FAIL-001）。"""
    broken = tmp_path / "t.jsonl"
    broken.write_text('{"seq": 1, "pointer": null}\nこれは JSON ではない\n', encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(broken))
    assert result.exit_code == 2
    assert ":2:" in result.output


def test_a_trace_line_that_is_not_an_object_exits_two(tmp_path: Path) -> None:
    broken = tmp_path / "t.jsonl"
    broken.write_text("[1, 2, 3]\n", encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(broken))
    assert result.exit_code == 2
    assert "オブジェクト" in result.output


@pytest.mark.parametrize(
    "row",
    ['{"seq": "1", "pointer": null}', '{"pointer": null}', '{"seq": 1, "pointer": 3}'],
)
def test_a_trace_row_with_the_wrong_types_exits_two(tmp_path: Path, row: str) -> None:
    broken = tmp_path / "t.jsonl"
    broken.write_text(row + "\n", encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(broken))
    assert result.exit_code == 2


def test_blank_lines_in_the_trace_are_skipped(tmp_path: Path) -> None:
    padded = tmp_path / "t.jsonl"
    padded.write_text('{"seq": 1, "pointer": null}\n\n\n', encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(padded))
    assert result.exit_code == 0
    assert result.stdout.count('data-jin-seq="') == 1


def test_a_missing_trace_file_exits_two(tmp_path: Path) -> None:
    result = run(str(PIPELINE), "--trace", str(tmp_path / "nope.jsonl"))
    assert result.exit_code == 2


# --------------------------------------------------------------------------------------
# 行の区切りは `\n` だけ（F-C-P3-001 / F-S-P3-003）
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "separator",
    [
        pytest.param("\u2028", id="LINE-SEPARATOR"),
        pytest.param("\u2029", id="PARAGRAPH-SEPARATOR"),
        pytest.param("\u0085", id="NEL"),
    ],
)
def test_a_row_containing_a_unicode_line_break_is_read(tmp_path: Path, separator: str) -> None:
    """`jin run --trace` は `ensure_ascii=False` で書くので、これらは生のまま JSONL に載る。

    `splitlines()` で割ると 1 行が 2 行になり、正当なトレースが exit 2 で拒まれていた。
    U+000B / U+000C は `json.dumps` が必ず `\\u000b` へ逃がすので生では現れない
    （生で置くと JSON 自身が不正になる）。ここでは扱わない。
    """
    target = tmp_path / "t.jsonl"
    target.write_text(
        '{"seq": 1, "pointer": null, "name": "a' + separator + 'b"}\n', encoding="utf-8"
    )
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 0, result.output


def test_crlf_line_endings_are_accepted(tmp_path: Path) -> None:
    target = tmp_path / "t.jsonl"
    target.write_bytes(b'{"seq": 1, "pointer": null}\r\n{"seq": 2, "pointer": null}\r\n')
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 0, result.output
    assert result.stdout.count('data-jin-seq="') == 2


# --------------------------------------------------------------------------------------
# 壊れた入力で Traceback を見せない（F-S-P3-001）
# --------------------------------------------------------------------------------------
def test_a_huge_integer_seq_exits_two(tmp_path: Path) -> None:
    """5000 桁の整数は `json.loads` を通ってしまう。`seq` の上限で拒む。"""
    target = tmp_path / "t.jsonl"
    target.write_text('{"seq": ' + "9" * 5000 + ', "pointer": null}\n', encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert len(result.output) < 500


def test_a_deeply_nested_json_row_exits_two(tmp_path: Path) -> None:
    """`json.loads` は入れ子の深さで `RecursionError` を投げる（`ValueError` ではない）。"""
    target = tmp_path / "t.jsonl"
    target.write_text("[" * 100_000 + "]" * 100_000 + "\n", encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 2
    assert "Traceback" not in result.output


@pytest.mark.parametrize("seq", ["0", "-1"])
def test_a_seq_below_one_exits_two(tmp_path: Path, seq: str) -> None:
    """`jin_adk.trace` の `seq` は 1 始まりの連番（F-C-P3-004 / F-S-P3-007）。"""
    target = tmp_path / "t.jsonl"
    target.write_text('{"seq": ' + seq + ', "pointer": null}\n', encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 2
    assert "seq" in result.output


def test_a_trace_that_is_not_utf8_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "t.jsonl"
    target.write_bytes(b'{"seq": 1, "pointer": "\xff\xfe"}\n')
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 2
    assert "UTF-8" in result.output


# --------------------------------------------------------------------------------------
# 行番号は**実ファイルの行**（F-V-P3-004）
# --------------------------------------------------------------------------------------
def test_a_bad_row_reports_the_real_file_line_number(tmp_path: Path) -> None:
    """空行を読み飛ばすので、並びの位置と行番号はずれる。ずれたまま出さない。"""
    target = tmp_path / "t.jsonl"
    target.write_text(
        '{"seq": 1, "pointer": null}\n'
        "\n"
        "\n"
        '{"seq": 2, "pointer": null}\n'
        "\n"
        '{"seq": 3, "pointer": 3}\n',
        encoding="utf-8",
    )
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 2
    assert ":6:" in result.output, result.output


def test_a_file_with_error_diagnostics_is_not_rendered() -> None:
    """`jin build` / `jin run` と同じ規律（DP-IMPL-JIN-P3-RENDER-ON-ERROR-01 の推奨案）。"""
    result = run(str(ERRORS / "JIN060_root_not_found.jin"))
    assert result.exit_code == 1
    assert "JIN060" in result.output


def test_a_non_jin_file_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "a.txt"
    other.write_text("{}", encoding="utf-8")
    result = run(str(other))
    assert result.exit_code == 2


def test_the_output_is_byte_stable_across_invocations() -> None:
    assert run(str(RESEARCHER)).stdout == run(str(RESEARCHER)).stdout


def test_the_help_lists_render() -> None:
    """`jin --help` の一覧に載っていること。

    ただし文字列 "render" は他の行にも現れうる（`jin_render` の説明など）ので、
    サブコマンドとして**呼べる**ことは下のテストで見る。
    """
    result = runner.invoke(app, ["--help"])
    assert "render" in result.output


def test_render_is_a_registered_subcommand() -> None:
    """F-W-P3-005: `@app.command()` を外しても上のテストは緑のままだった。

    `jin render --help` が exit 0 で返るのは、Typer に登録されているときだけ。
    """
    result = runner.invoke(app, ["render", "--help"])
    assert result.exit_code == 0, result.output
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output).replace("\n", " ")
    for option in ("trace", "focus", "force"):
        assert option in plain, (option, plain)


def test_the_trace_fixture_is_the_committed_one() -> None:
    """テストが読むトレースがコミット済みの `jin run --model fake` の出力であること。"""
    rows = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").split("\n") if line]
    assert len(rows) == 11
    assert rows[0]["pointer"] == "/circles/2/core"
    assert rows[-1]["pointer"] == "/circles/1/flow/exit"


# --------------------------------------------------------------------------------------
# `-o` の拒否条件（A-9 / F-W-P3-007 / F-W-P3-011）
# --------------------------------------------------------------------------------------
def test_a_missing_parent_directory_is_refused_without_creating_it(tmp_path: Path) -> None:
    """親ディレクトリは**作らない**（F-W-P3-003 / F-S-P3-012 / F-C-P3-006）。

    `jin build --out` は木を作るコマンドだが、`jin render -o` は 1 ファイルを書くだけ。
    打ち間違えたパスの下にディレクトリが生えるほうが害が大きい。
    """
    target = tmp_path / "no" / "such" / "out.svg"
    result = run(str(PIPELINE), "-o", str(target))
    assert result.exit_code == 1
    assert "ディレクトリがありません" in result.output
    assert not (tmp_path / "no").exists()


def test_a_directory_as_the_output_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "adir"
    target.mkdir()
    result = run(str(PIPELINE), "-o", str(target), "--force")
    assert result.exit_code == 1
    assert "ディレクトリ" in result.output
    assert target.is_dir()


def test_writing_over_the_input_jin_is_refused(tmp_path: Path) -> None:
    """`-o` に入力の `.jin` を渡すと入力そのものが消える（`--force` でも通さない）。"""
    source = tmp_path / "copy.jin"
    source.write_text(PIPELINE.read_text(encoding="utf-8"), encoding="utf-8")
    before = source.read_bytes()
    result = run(str(source), "-o", str(source), "--force")
    assert result.exit_code == 1
    assert source.read_bytes() == before


def test_the_success_message_does_not_carry_control_characters(tmp_path: Path) -> None:
    """成功時の文言も `.jin` 由来のパスを載せるので `_safe` を通す（F-S-P3-009）。"""
    target = tmp_path / "out\u0007.svg"
    result = run(str(PIPELINE), "-o", str(target))
    assert result.exit_code == 0
    assert "\u0007" not in result.output
    assert "書き出しました" in result.output


def test_reading_the_umask_restores_it() -> None:
    """`_new_file_mode` は umask を `os.umask(0)` の往復で読む。**必ず元に戻す**。

    戻し忘れると、以降このプロセスが作るファイルが全部 0666 相当になる
    （`jin build` の生成物や `jin run` のトレースまで緩む）。`guard:` 主張
    `_new_file_mode -> os.umask(mask)` に歯を付けるテスト（F-S-P3-105 / F-V-P3-113）。
    """
    previous = os.umask(0o027)
    try:
        assert _new_file_mode() == 0o644 & ~0o027
        # 読み取りの往復で umask が変わっていないこと
        current = os.umask(0)
        os.umask(current)
        assert current == 0o027
    finally:
        os.umask(previous)


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="/dev/full が無い")
def test_a_full_stdout_is_one_line_not_a_traceback() -> None:
    """標準出力に書けないとき 1 行 + exit 1（F-S-P3-103）。

    `-o` 側は `_classify_write_failure` で一文にしているので、標準出力側もそろえる。
    CliRunner の stdout は BytesIO なので ENOSPC を再現できない。別プロセスで測る。
    """
    jin = Path(sys.executable).parent / "jin"
    with Path("/dev/full").open("wb") as full:
        result = subprocess.run(
            [str(jin), "render", str(RESEARCHER)],
            cwd=REPO_ROOT,
            stdout=full,
            stderr=subprocess.PIPE,
            check=False,
        )
    message = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 1, (result.returncode, message)
    assert "標準出力に書けません" in message, message
    assert "Traceback" not in message, message


def test_a_huge_negative_upto_does_not_fill_the_terminal() -> None:
    """`--upto` の値も `brief()` で切る（F-S-P3-106）。

    `int()` は 4300 桁で先に落ちて typer が Invalid value を出すので、ここに届くのは
    4300 桁未満である。1000 桁で見る。
    """
    result = run(str(PIPELINE), "--trace", str(TRACE), "--upto", "-" + "1" * 1000)
    assert result.exit_code == 2
    assert len(result.output) < 300, len(result.output)


# --------------------------------------------------------------------------------------
# 「空行」の定義（F-C-P3-103 / F-C-P3-203・判断は記録のみ・現状を固定する）
# --------------------------------------------------------------------------------------
def test_a_bom_only_line_is_refused(tmp_path: Path) -> None:
    """BOM だけの行は**壊れた行**として exit 2（`str.strip()` は U+FEFF を落とさない）。

    R2.2 項 5 に「空行の定義を ASCII に狭めると BOM 付き空行が壊れた行になる」と書いたが、
    BOM 行は既に exit 2 であり理由が事実と違っていた（F-C-P3-203）。判断（現状を保つ）は
    変えないが、現状がどちらなのかをテストで固定する。
    """
    target = tmp_path / "t.jsonl"
    target.write_text('{"seq": 1, "pointer": null}\n\ufeff\n', encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 2
    assert ":2:" in result.output, result.output


@pytest.mark.parametrize(
    "blank", [pytest.param("\u3000", id="U+3000"), pytest.param("\u00a0", id="U+00A0")]
)
def test_a_unicode_whitespace_only_line_is_skipped(tmp_path: Path, blank: str) -> None:
    """`str.strip()` が落とす空白だけの行は空行として読み飛ばす（現状の挙動）。"""
    target = tmp_path / "t.jsonl"
    target.write_text(f'{{"seq": 1, "pointer": null}}\n{blank}\n', encoding="utf-8")
    result = run(str(PIPELINE), "--trace", str(target))
    assert result.exit_code == 0, result.output
    assert result.stdout.count('data-jin-seq="') == 1


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="/dev/full が無い")
def test_a_full_stdout_on_the_success_message_is_one_line_not_a_traceback(
    tmp_path: Path,
) -> None:
    """`-o` 付きの**成功文言**も、書けなければ 1 行 + exit 1（F-W-P3-201）。

    `-o` 無しの経路（SVG 本体）は R2 でそろえたが、成功文言の `typer.echo` は
    rich のトレースバック + exit 120 のままだった。SVG の書き出し自体は成功するので、
    ファイルは出来ていることも確かめる。
    """
    jin = Path(sys.executable).parent / "jin"
    target = tmp_path / "out.svg"
    with Path("/dev/full").open("wb") as full:
        result = subprocess.run(
            [str(jin), "render", str(PIPELINE), "-o", str(target)],
            cwd=REPO_ROOT,
            stdout=full,
            stderr=subprocess.PIPE,
            check=False,
        )
    message = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 1, (result.returncode, message)
    assert "標準出力に書けません" in message, message
    assert "Traceback" not in message, message
    assert target.read_text(encoding="utf-8").startswith("<svg "), "SVG は書けているはず"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="preexec_fn の無い OS")
def test_a_closed_stdout_is_one_line_not_a_traceback() -> None:
    """fd 1 を閉じた状態（`jin render ... >&-`）で 1 行 + exit 1（F-W-P3-202 / F-S-P3-202）。

    Python は fd 1 が閉じていると `sys.stdout` を `None` にする。`getattr(None, "buffer")`
    は `None` を返すので `sys.stdout.write` へ落ちて `AttributeError` になっていた。
    `preexec_fn` で子プロセスの fd 1 を閉じて実測する（`subprocess` の `stdout=` では
    fd 1 は開いたままなのでこの分岐に入らない）。
    """
    jin = Path(sys.executable).parent / "jin"
    result = subprocess.run(
        [str(jin), "render", str(PIPELINE)],
        cwd=REPO_ROOT,
        stderr=subprocess.PIPE,
        preexec_fn=lambda: os.close(1),
        check=False,
    )
    message = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 1, (result.returncode, message)
    assert "標準出力が閉じています" in message, message
    assert "Traceback" not in message, message
