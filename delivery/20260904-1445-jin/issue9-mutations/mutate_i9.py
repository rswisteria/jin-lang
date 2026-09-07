"""Issue #9（fix-later 7 件）で「対応する」とした 3 件の防御を壊し、赤くなることを実測する。

`phase6-mutations/mutate_p6.py` と同じ流儀（隔離コピー・判定は `returncode != 0` + 失敗の印）。
pnpm 側は関係しないので pytest だけを回す。

対象は 2026-09-07 に toyota が確定した 3 件:

- `DP-REVIEW-JIN-001` — `jin check` / `jin fmt` の**走査**が symlink を対象にしない
  （名指しは従来どおり読む・黙って飛ばさない）
- `DP-REVIEW-JIN-005` — テストがランディレクトリを直書きせず `tests.conftest.delivery_run()` で解決する
- `DP-REVIEW-JIN-006` — CI の uv コマンドを件数の下限ではなく**名前の集合**（allowlist）で見る

実行: `uv run python delivery/20260904-1445-jin/issue9-mutations/mutate_i9.py`
      `MUTATE_ONLY=NAME1,NAME2 uv run python ...` で一部だけ回す
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN_TIMEOUT_SECONDS = 600

COPY_ITEMS = [
    "packages",
    "tests",
    "examples",
    "plugins",
    "scripts",
    "docs",
    "schemas",
    "delivery",
    "jin-requirements.md",
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
    ".python-version",
    ".github",
]

MAIN = "packages/jin-cli/src/jin_cli/main.py"
CONFTEST = "tests/conftest.py"
CI_CONTRACT = "tests/contract/test_ci_contract.py"
PACKAGING = "tests/contract/test_packaging_contract.py"
ADK_VERSION = "tests/contract/test_adk_version_contract.py"

T_CLI = "packages/jin-cli/tests/test_cli.py"
T_CI = "tests/contract/test_ci_contract.py"
T_PACKAGING = "tests/contract/test_packaging_contract.py"

#: (名前, 対象ファイル, before, after, pytest 引数)
MUTATIONS: list[tuple[str, str, str, str, list[str]]] = [
    # --- DP-REVIEW-JIN-001: 走査は対象ディレクトリの外へ出ない -------------------------
    (
        "COLLECT-walks-into-symlinks",
        MAIN,
        "                if entry.is_symlink():\n",
        "                if False:\n",
        [T_CLI, "-k", "symlink_found_by_walking or filters_symlinks_only_when_walking"],
    ),
    (
        # 名指しまで落とすと、ユーザーが指したファイルが黙って検査されなくなる。
        "COLLECT-drops-named-symlinks-too",
        MAIN,
        "        elif path.exists():\n",
        "        elif path.exists() and not path.is_symlink():\n",
        [T_CLI, "-k", "named_directly or filters_symlinks_only_when_walking"],
    ),
    (
        # 黙って飛ばすと、ファイルが検査されなかったことに気づけない（NFR-FAIL-001）。
        "COLLECT-skips-silently",
        MAIN,
        (
            '                        f"シンボリックリンクなので対象にしません: {_safe(str(entry))}"\n'
            '                        "（走査は対象ディレクトリの外へ出ません。読みたいときは直接指定してください）",\n'
            "                        err=True,\n"
        ),
        '                        "",\n                        err=True,\n',
        [T_CLI, "-k", "symlink_found_by_walking"],
    ),
    # --- DP-REVIEW-JIN-005: ランディレクトリを解決する ---------------------------------
    (
        "DELIVERY-returns-the-oldest-run",
        CONFTEST,
        "        return runs[-1]\n",
        "        return runs[0]\n",
        [T_PACKAGING, "-k", "picks_the_newest_run"],
    ),
    (
        "DELIVERY-prefers-the-flat-layout",
        CONFTEST,
        "    if runs:\n        return runs[-1]\n    flat = root / slug\n",
        "    flat = root / slug\n    if flat.is_dir():\n        return flat\n    if runs:\n        return runs[-1]\n",
        [T_PACKAGING, "-k", "falls_back_to_the_flat_layout"],
    ),
    (
        # 見つからないときに黙って `delivery/` そのものを返すと、別の場所を指す。
        "DELIVERY-guesses-when-missing",
        CONFTEST,
        '    raise FileNotFoundError(f"delivery/ に *-{slug} のランディレクトリがありません: {root}")\n',
        "    return root\n",
        [T_PACKAGING, "-k", "refuses_to_guess"],
    ),
    (
        # 直書きが静かに戻る経路。走査が緩むとここが素通りになる。
        "DELIVERY-hardcoded-again",
        ADK_VERSION,
        '    probe = (DELIVERY_RUN / "adk-api-probe.md").read_text(encoding="utf-8")\n',
        '    probe = (REPO_ROOT / "delivery" / "2026'
        + '0904-1445-jin" / "adk-api-probe.md").read_text(\n'
        '        encoding="utf-8"\n    )\n',
        [T_PACKAGING, "-k", "no_test_hardcodes"],
    ),
    # --- DP-REVIEW-JIN-006: allowlist -------------------------------------------------
    (
        "UV-allowlist-loses-an-entry",
        CI_CONTRACT,
        '        "uv sync",\n',
        "",
        [T_CI, "-k", "expected_uv_commands_are_actually_found"],
    ),
    (
        # CI からコマンドが消えたら**名前で**落ちること（下限を下げて黙らせられない）。
        "UV-command-removed-from-ci",
        ".github/workflows/ci.yml",
        "      - name: Check dependency direction (import-linter)\n        run: uv run lint-imports\n",
        "      - name: Check dependency direction (import-linter)\n        run: echo skipped\n",
        [T_CI, "-k", "scanner_does_not_silently_shrink"],
    ),
]


def _copy_tree(dest: pathlib.Path) -> None:
    for item in COPY_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(
                src,
                dest / item,
                ignore=shutil.ignore_patterns(
                    "__pycache__", ".pytest_cache", "node_modules", "dist", "test-results"
                ),
            )
        else:
            shutil.copy2(src, dest / item)


def _purge_pycache(root: pathlib.Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _env(copy: pathlib.Path) -> dict[str, str]:
    src_dirs = [str(p) for p in sorted(copy.glob("packages/*/src"))]
    existing = os.environ.get("PYTHONPATH")
    path = os.pathsep.join(src_dirs + ([existing] if existing else []))
    tmp = copy / "tmp"
    tmp.mkdir(exist_ok=True)
    return dict(os.environ, PYTHONPATH=path, PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(tmp))


def _run_pytest(copy: pathlib.Path, target: list[str]) -> subprocess.CompletedProcess[str]:
    _purge_pycache(copy)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=--import-mode=importlib",
            *target,
        ],
        cwd=copy,
        capture_output=True,
        text=True,
        env=_env(copy),
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
    )


def _summary(result: subprocess.CompletedProcess[str]) -> str:
    interesting = ("passed", "failed", "error")
    lines = [ln.strip() for ln in result.stdout.splitlines() if any(w in ln for w in interesting)]
    if lines:
        return lines[-1][:110]
    tail = result.stderr.strip().splitlines()
    return tail[-1][:110] if tail else "(no summary)"


def _is_red(result: subprocess.CompletedProcess[str]) -> bool:
    """失敗していること。**exit 5（0 件選択）は赤に数えない。**"""
    if result.returncode in (0, 5):
        return False
    return any(w in result.stdout + result.stderr for w in ("failed", "error"))


def main() -> int:
    only = {n for n in os.environ.get("MUTATE_ONLY", "").split(",") if n}
    unknown = only - {m[0] for m in MUTATIONS}
    if unknown:
        print(f"!! MUTATE_ONLY に存在しない変異名: {sorted(unknown)}")
        return 1

    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-i9-"))
    try:
        _copy_tree(copy)
        where = subprocess.run(
            [sys.executable, "-c", "import jin_cli; print(jin_cli.__file__)"],
            cwd=copy,
            capture_output=True,
            text=True,
            env=_env(copy),
            check=False,
        ).stdout.strip()
        print(f"copy: {copy}")
        print(f"imports from: {where}")
        if not where.startswith(str(copy)):
            print("!! jin_cli が隔離コピーを指していない。中止")
            return 2

        baseline = _run_pytest(copy, [T_CLI, T_CI, T_PACKAGING])
        if baseline.returncode != 0:
            print("BASELINE NOT GREEN")
            print(baseline.stdout[-3000:])
            return 2
        print(f"baseline: green ({_summary(baseline)})")

        caught = 0
        skipped = 0
        mutations = [m for m in MUTATIONS if not only or m[0] in only]
        for name, rel, before, after, target in mutations:
            path = copy / rel
            original = path.read_text(encoding="utf-8")
            if before not in original:
                print(f"{name:36s} SKIP (pattern not found)")
                skipped += 1
                continue
            path.write_text(original.replace(before, after, 1), encoding="utf-8")
            try:
                result = _run_pytest(copy, target)
            except subprocess.TimeoutExpired:
                print(f"{name:36s} {'TIMEOUT (!! ハングした)':30s} {RUN_TIMEOUT_SECONDS}s")
                continue
            finally:
                path.write_text(original, encoding="utf-8")
            ok = _is_red(result)
            status = "RED (expected)" if ok else f"NOT RED (!! exit {result.returncode})"
            caught += ok
            print(f"{name:36s} {status:30s} {_summary(result)}")
        subset = f" (subset; MUTATE_ONLY={','.join(sorted(only))})" if only else ""
        print(
            f"{caught}/{len(mutations)} mutations caught{subset}"
            + (f" ({skipped} skipped)" if skipped else "")
        )
        return 0 if mutations and caught == len(mutations) and skipped == 0 else 1
    finally:
        shutil.rmtree(copy, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
