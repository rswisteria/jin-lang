"""CI ワークフローの契約（wiring review W-01 / W-04 / W-06 / W-11）。

CI の設定は**壊れても手元のテストが緑のまま**なので、ここで固定する。
PyYAML を依存に足さないため、行単位の構造検査で見る（対象が 1 ファイル・73 行なので十分）。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_lines() -> list[str]:
    assert CI.is_file(), f"{CI} が無い"
    return CI.read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def ci_text() -> str:
    return CI.read_text(encoding="utf-8")


def step_names(lines: list[str]) -> list[str]:
    """`      - name: X` の並び（= ステップの実行順）。"""
    return [m.group(1).strip() for line in lines if (m := re.match(r"\s+- name: (.+)$", line))]


def uv_commands(lines: list[str]) -> list[str]:
    """ワークフロー内で実行される `uv ...` コマンドを 1 つずつ返す。

    `run: |` の複数行ブロックも展開し、`&&` / `;` / `|` で連結されたものも分解する。
    1 行の `run:` しか見ないと、複数行ブロックに紛れ込んだ打ち消しフラグを見逃す。

    既知の限界（意図的に埋めていない）:

    - 区切り文字の分解は素の正規表現なので、**引用符の中の `|` や `;` でも切る**。
      現に `uv run python -c "import sys; print(...)"` は `uv run python -c "import sys` に
      切り詰められる。切り詰めで**見落とす**方向にしか壊れないため打ち消しフラグの検出には
      効くが、`sh -c 'uv sync --frozen'` のような入れ子は原理的に見つけられない。
    - この関数自体が壊れて走査対象が減ると全テストが黙って緑になるので、
      `test_the_uv_command_scanner_does_not_silently_shrink` で件数の下限を固定する。
    """
    commands: list[str] = []
    block_indent: int | None = None
    for raw in lines:
        stripped = raw.strip()
        if block_indent is not None:
            indent = len(raw) - len(raw.lstrip(" "))
            if stripped and indent <= block_indent:
                block_indent = None
            elif stripped and not stripped.startswith("#"):
                commands.append(stripped)
                continue
        inline = re.match(r"(\s*)(?:- )?run:\s*(.*)$", raw)
        if inline is None:
            continue
        body = inline.group(2).strip()
        if body in {"|", ">", "|-", ">-"}:
            block_indent = len(inline.group(1))
            continue
        if body and not body.startswith("#"):
            commands.append(body)
    out: list[str] = []
    for command in commands:
        for part in re.split(r"&&|\|\||;|\|", command):
            part = part.strip()
            if part.startswith("uv ") or part == "uv":
                out.append(part)
    return out


# --------------------------------------------------------------------------------------
# W-01: uv.lock の整合
# --------------------------------------------------------------------------------------
def test_uv_locked_is_set_for_the_whole_job(ci_lines: list[str]) -> None:
    """W-01: `uv sync --frozen` は stale な lock を素通りし、後続の裸 `uv run` が lock を書き換える。

    ステップごとに付けると足し忘れるので、**job の env** に置く。
    """
    in_env = False
    found = False
    for line in ci_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"\s{4}env:\s*$", line):
            in_env = True
            continue
        if in_env:
            if re.match(r"\s{0,4}\S", line):  # env ブロックの終わり
                break
            if stripped.startswith("UV_LOCKED"):
                found = True
                value = stripped.split(":", 1)[1].strip().strip("\"'")
                assert value == "1", f"UV_LOCKED の値が 1 ではない: {stripped}"
    assert found, "job の env に UV_LOCKED が無い"


#: `UV_LOCKED` を打ち消すフラグ。実測で確認したものだけを挙げる（2026-09-04 / uv 0.12.9）。
#: `--frozen` → `warning: Ignoring UV_LOCKED because --frozen was provided` で lock 検証が飛ぶ。
#: `--offline` は lock 検証を飛ばさないので挙げない。`--no-locked` は uv sync に存在しない。
UV_LOCKED_DEFEATING_FLAGS = ("--frozen",)


def test_no_uv_command_defeats_uv_locked(ci_lines: list[str]) -> None:
    """N-01: `UV_LOCKED` が env にあることと、それが**効いていること**は別（W-02 と同型）。

    実測（2026-09-04）:

    | コマンド | uv 0.7.8 | uv 0.12.9 |
    |---|---|---|
    | `UV_LOCKED=1 uv sync --frozen`（clean） | EXIT=2（usage エラー） | EXIT=0（lock 検証が飛ぶ） |
    | `UV_LOCKED=1 uv sync --frozen`（stale） | EXIT=2 | **EXIT=0** |
    | `UV_LOCKED=1 uv sync`（clean） | EXIT=0 | EXIT=0 |
    | `UV_LOCKED=1 uv sync`（stale） | EXIT=2 | EXIT=1 |

    どちらの版でも `--frozen` 付きでは lock を検証していない。
    """
    commands = uv_commands(ci_lines)
    assert commands, "ワークフローに uv コマンドが 1 つも見つからない（走査が壊れている）"
    for command in commands:
        for flag in UV_LOCKED_DEFEATING_FLAGS:
            assert flag not in command.split(), f"{flag} が UV_LOCKED を打ち消す: {command!r}"


def test_uv_frozen_is_not_set_anywhere(ci_text: str) -> None:
    """N-01: 環境変数の形の打ち消しも塞ぐ。

    実測: `UV_FROZEN=1 UV_LOCKED=1 uv sync` は
    `error: the argument UV_LOCKED cannot be used with UV_FROZEN` で落ちる。
    """
    for line in ci_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.match(r"UV_FROZEN\s*:", stripped), line


def test_uv_version_is_pinned(ci_text: str) -> None:
    """N-01: uv の版が浮いていると lock 検証の挙動が版によって変わる。

    実測: uv 0.7.8 は `UV_LOCKED=1 uv sync --frozen` がクリーンでも EXIT=2、
    uv 0.12.9 は同じコマンドが EXIT=0。`--frozen` を外したうえで版も固定する。
    値の根拠は decision-conformance.md §2.12。
    """
    match = re.search(r'^\s*version:\s*"([^"]+)"\s*$', ci_text, re.MULTILINE)
    assert match is not None, "setup-uv に version: の固定が無い"
    assert re.fullmatch(r"\d+\.\d+\.\d+", match.group(1)), match.group(1)


#: 走査で見つかるべき `uv ...` コマンドの最小件数（2026-09-04 実測は 9 件）。
#: 走査が壊れて件数が落ちると、打ち消しフラグを見ていないのに全テストが緑になる。
MINIMUM_UV_COMMANDS = 9


def test_the_uv_command_scanner_does_not_silently_shrink(ci_lines: list[str]) -> None:
    """N-01: 走査関数自体が壊れると、上の 3 本が「何も検査しないまま緑」になる。

    ステップを減らしたなら、この定数も一緒に下げること（そのとき何を検査しなくなったかを
    考える機会になる）。
    """
    commands = uv_commands(ci_lines)
    assert len(commands) >= MINIMUM_UV_COMMANDS, (
        f"uv コマンドの検出が {len(commands)} 件に減っている"
        f"（下限 {MINIMUM_UV_COMMANDS}）: {commands}"
    )


def test_the_uv_command_scanner_reads_multiline_run_blocks() -> None:
    """N-01: `run: |` ブロックに紛れ込ませた打ち消しフラグを拾えることを直接示す。

    本物の ci.yml には現在 `run: |` ブロックが 1 つしかないので、
    ブロック処理が壊れても実データでは気づけない。合成入力で固定する。
    """
    lines = [
        "      - name: Sync",
        "        run: |",
        "          uv sync --frozen",
        "          uv run pytest && uv run ruff check .",
        "          # uv sync --frozen  <- コメントは無視する",
        "      - name: Next",
        "        run: echo done",
    ]
    assert uv_commands(lines) == [
        "uv sync --frozen",
        "uv run pytest",
        "uv run ruff check .",
    ]


def test_the_sync_step_actually_verifies_the_lock(ci_lines: list[str]) -> None:
    """N-01: 依存の同期ステップが lock 検証の入口であること。"""
    sync = [c for c in uv_commands(ci_lines) if c.split()[1:2] == ["sync"]]
    assert sync, "uv sync のステップが無い"
    for command in sync:
        assert "--frozen" not in command, command


# --------------------------------------------------------------------------------------
# W-04: 2 重の網の独立性
# --------------------------------------------------------------------------------------
def test_schema_drift_check_runs_after_the_tests(ci_lines: list[str]) -> None:
    """W-04: ドリフト検出のステップがテストより先にツリーを書き換えてはいけない。

    先に書き換えると、テスト側のドリフト検出は常に整形済みのツリーを見ることになり、
    2 枚あるはずの網が 1 枚に縮む。
    """
    names = step_names(ci_lines)
    assert "Test" in names, names
    drift = [n for n in names if "drift" in n.lower()]
    assert drift, names
    assert names.index("Test") < names.index(drift[0]), f"ドリフト検出がテストより前にある: {names}"


def test_schema_drift_check_does_not_rewrite_the_tree(ci_text: str) -> None:
    """W-04: 検出は比較で行う（生成スクリプトでツリーを書き換えてから git diff しない）。"""
    drift_step = ci_text.split("Detect JSON Schema drift", 1)[1]
    assert "generate_schema.py" not in drift_step.split("- name:", 1)[0]
    assert "diff" in drift_step.split("- name:", 1)[0]


# --------------------------------------------------------------------------------------
# W-06: Python を浮かせない
# --------------------------------------------------------------------------------------
def test_python_version_file_exists_and_is_used(ci_text: str) -> None:
    """W-06: CI の Python バージョンが runner の既定に依存しないこと。

    版の指定は `.python-version` 1 箇所に置く。uv がこれをネイティブに読むので、
    `setup-uv` 側へ版を渡すと二重管理になる。
    """
    version_file = REPO_ROOT / ".python-version"
    assert version_file.is_file(), ".python-version が無い"
    version = version_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", version), version
    # 実際に使った版がログに残ること（浮いていたら気づけるようにする）。
    assert 'uv run python -c "import sys; print(sys.version)"' in ci_text


def test_ci_does_not_pass_a_nonexistent_input_to_setup_uv(ci_text: str) -> None:
    """W-06: `setup-uv@v5` に `python-version-file` 入力は**存在しない**（2026-09-04 実測）。

    Actions は未知の入力を警告するだけで失敗させないので、書いても効かないまま
    「固定したつもり」になる。書かないことをテストで固定する。
    """
    for line in ci_text.splitlines():
        if line.strip().startswith("#"):
            continue  # 実測の根拠をコメントに残してあるので、コメントは対象外
        assert "python-version-file" not in line, line


def test_ci_does_not_hardcode_a_python_version(ci_text: str) -> None:
    """W-06: 版を CI にも書くと `.python-version` と二重管理になり、片方だけ動く。"""
    for line in ci_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.match(r"python-version:\s*\S", stripped), line


def test_pinned_python_satisfies_requires_python() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requires = config["project"]["requires-python"]
    floor = tuple(int(part) for part in requires.removeprefix(">=").split("."))
    pinned_text = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    pinned = tuple(int(part) for part in pinned_text.split("."))
    assert pinned >= floor, f".python-version({pinned_text}) が requires-python({requires}) 未満"


# --------------------------------------------------------------------------------------
# W-11: 権限・並行・タイムアウト
# --------------------------------------------------------------------------------------
def test_workflow_declares_least_privilege(ci_text: str) -> None:
    """W-11: 既定の書き込み権限を渡さない（最小権限）。"""
    assert re.search(r"^permissions:\s*$", ci_text, re.MULTILINE), "permissions: が無い"
    assert "contents: read" in ci_text


def test_workflow_declares_concurrency(ci_text: str) -> None:
    """W-11: 同じ ref への push が重なったら古い実行を捨てる。"""
    assert re.search(r"^concurrency:\s*$", ci_text, re.MULTILINE), "concurrency: が無い"
    assert "cancel-in-progress: true" in ci_text


def test_every_job_has_a_timeout(ci_lines: list[str]) -> None:
    """W-11: ぶら下がったジョブが既定の 6 時間まで走り続けないようにする。"""
    start = next(i for i, line in enumerate(ci_lines) if line.rstrip() == "jobs:")
    jobs = [
        line.strip().rstrip(":")
        for line in ci_lines[start + 1 :]
        if re.fullmatch(r"\s{2}[\w-]+:", line.rstrip())
    ]
    timeouts = [
        line for line in ci_lines if "timeout-minutes:" in line and not line.strip().startswith("#")
    ]
    assert jobs, "jobs: の下にジョブが見つからない"
    assert len(timeouts) >= len(jobs), f"timeout-minutes が無いジョブがある: {jobs}"
