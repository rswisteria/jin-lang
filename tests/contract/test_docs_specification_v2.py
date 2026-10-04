"""`docs/specification-v2/`(Jin v2 の言語マニュアル・本)の例と演習が、言語の実装とずれないことを固定する。

本全体の検証(本文に引用した出力の照合・図の検査・概念の順序)は explainer の `verify-book.mjs` が行う(Node / d2 /
Chromium が要るので CI では回さない・本の README の「手元で確かめる」)。ここで見るのは、言語を直したときに本が
黙って嘘になる経路だけ:

- 例と演習の答えは `jin check` を通り、正準形である(`messy.jin` は正準形でない例なので check だけ)
- 演習の出発点は、本文が説明している診断で落ちる
- 図の事実シートは、正本(スキーマ・runtime.md §2・examples-v2/tetris-plus)から作り直したものと一致する
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOK = REPO_ROOT / "docs" / "specification-v2"
EXAMPLES = BOOK / "examples"
STARTERS = {
    "ex-out/start.jin": ["JIN203"],
    "ex-fix/start.jin": ["JIN202", "JIN230"],
}
NOT_CANONICAL = {"steps/messy.jin"}


def jin(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "jin_cli.main", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=EXAMPLES,
    )


def example_names() -> list[str]:
    return sorted(
        str(p.relative_to(EXAMPLES))
        for p in EXAMPLES.rglob("*.jin")
        if str(p.relative_to(EXAMPLES)) not in STARTERS
    )


def test_the_book_has_the_examples_it_quotes() -> None:
    assert {"hello/hello.jin", "score/score.jin", "ex-out/answer.jin", "ex-fix/answer.jin"} <= set(
        example_names()
    )


@pytest.mark.parametrize("name", example_names())
def test_every_example_and_answer_passes_check(name: str) -> None:
    result = jin("check", name)
    assert result.returncode == 0, result.stdout + result.stderr
    if name not in NOT_CANONICAL:
        formatted = jin("fmt", "--check", name)
        assert formatted.returncode == 0, formatted.stdout + formatted.stderr


@pytest.mark.parametrize(("name", "codes"), sorted(STARTERS.items()))
def test_every_exercise_starter_fails_with_the_diagnostics_the_book_explains(
    name: str, codes: list[str]
) -> None:
    result = jin("check", name)
    assert result.returncode == 1
    found = [
        line.split("error ", 1)[1].split(":", 1)[0]
        for line in result.stdout.splitlines()
        if " error JIN" in line
    ]
    assert found == codes


def test_the_figure_fact_sheets_match_their_sources() -> None:
    result = subprocess.run(
        [sys.executable, str(BOOK / "tools" / "facts.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
