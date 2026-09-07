"""Phase 6（デバッグモード / トレースリプレイ）の防御を 1 つずつ壊し、赤くなることを実測する。

`phase5-mutations/mutate_p5.py` と同じ流儀（隔離コピー・`node_modules` は symlink・
判定は `returncode != 0` + 失敗の印）。補助関数もそちらから引き写している。

**e2e（Playwright）は回さない。** 隔離コピーには `dist` が無く、`e2e/editor.ts` が
コピー側の root で `uv run jin editor` を起こすため、`.venv` の再作成に落ちる。
したがって machine 1 / 2 と「編集してもトレースが残る」は**この表では守られていない**
（Playwright だけが見張っている）。詳細パネル（machine 4）とフィルタ（machine 3）は
Python 側の弱い網（`tests/contract/test_editor_contract.py`）を置いたので拾える。

実行: `uv run python delivery/20260904-1445-jin/phase6-mutations/mutate_p6.py`
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
    "apps",
    "jin-requirements.md",
    "pyproject.toml",
    ".python-version",
    ".github",
]

PARSE = "apps/editor/src/trace/parse.ts"
FILTER = "apps/editor/src/trace/filter.ts"
PANEL = "apps/editor/src/debug/DebugPanel.tsx"
REPLAY = "apps/editor/src/debug/replay.ts"
APP = "apps/editor/src/App.tsx"
CANVAS = "apps/editor/src/svg/SvgCanvas.tsx"
PROTOCOL = "apps/editor/src/rpc/protocol.ts"
VIEWSTATE = "apps/editor/src/state/viewState.ts"
T_TRACE_TS = "apps/editor/test/trace.test.ts"
SPEC = "apps/editor/e2e/debug.spec.ts"
REQUESTS = "packages/jin-lsp/src/jin_lsp/requests.py"

T_CONTRACT = "tests/contract/test_editor_contract.py"
T_SESSION = "packages/jin-lsp/tests/test_session.py"

#: (名前, 対象ファイル, before, after, 検査) — 検査は ("py", [pytest 引数]) か ("pnpm", "スクリプト名")
MUTATIONS: list[tuple[str, str, str, str, tuple[str, object]]] = [
    # --- JSONL の読み取り（NFR-FAIL-001: 黙って読み飛ばさない）------------------------
    (
        # 壊れた行を飛ばすと「発火していないのに未強調」と区別できなくなる。
        "TRACE-skips-broken-lines",
        PARSE,
        (
            "      const detail = error instanceof Error ? error.message : String(error);\n"
            "      return {\n        ok: false,\n        line: number,\n"
        ),
        (
            "      const detail = error instanceof Error ? error.message : String(error);\n"
            "      if (detail) continue;\n"
            "      return {\n        ok: false,\n        line: number,\n"
        ),
        ("pnpm", "test"),
    ),
    (
        # 行番号を「受理した行の通し番号」にすると、空行のぶんだけずれる（F-V-P3-004）。
        "TRACE-line-is-the-position",
        PARSE,
        "    events.push({ line: number, row: value as TraceRow });\n",
        "    events.push({ line: events.length + 1, row: value as TraceRow });\n",
        ("pnpm", "test"),
    ),
    (
        # `splitlines()` 相当にすると、モデル出力に U+2028 を含む正当なトレースが割れる。
        "TRACE-splits-on-unicode-separators",
        PARSE,
        '  const lines = body.split("\\n");\n',
        "  const lines = body.split(/\\n|\\u2028|\\u2029|\\u0085/);\n",
        ("pnpm", "test"),
    ),
    (
        "TRACE-accepts-arrays-as-rows",
        PARSE,
        '    if (value === null || typeof value !== "object" || Array.isArray(value)) {\n',
        '    if (value === null || typeof value !== "object") {\n',
        ("pnpm", "test"),
    ),
    (
        # `seq` を「数値なら何でも」にすると `1.5` が通り、サーバの拒否と食い違う。
        "TRACE-seq-accepts-non-integers",
        PARSE,
        '  return typeof seq === "number" && Number.isInteger(seq) ? seq : null;\n',
        '  return typeof seq === "number" ? seq : null;\n',
        ("pnpm", "test"),
    ),
    # --- pointer 一致フィルタ（machine 3）--------------------------------------------
    (
        # **主対象**: 前方一致にすると `/circles/2` が `/circles/20/core` を拾う。
        "FILTER-prefix-match",
        FILTER,
        (
            "  return (\n    candidate.length < pointer.length &&\n"
            "    pointer.startsWith(candidate) &&\n"
            '    pointer[candidate.length] === "/"\n  );\n'
        ),
        "  return pointer.startsWith(candidate);\n",
        ("pnpm", "test"),
    ),
    (
        "FILTER-direction-flipped",
        FILTER,
        '  if (candidate === pointer) return true;\n  if (candidate === "") return false;\n',
        (
            '  if (candidate === pointer) return true;\n  if (pointer === "") return false;\n'
            "  [candidate, pointer] = [pointer, candidate];\n"
        ),
        ("pnpm", "test"),
    ),
    (
        "FILTER-keeps-null-pointer-rows",
        FILTER,
        "    return pointer !== null && isAncestorOrSame(selected, pointer);\n",
        "    return pointer === null || isAncestorOrSame(selected, pointer);\n",
        ("pnpm", "test"),
    ),
    (
        # 「絞り込めなければ全部」にすると、一致の意味が変わる（0 件が出せなくなる）。
        "FILTER-falls-back-to-everything",
        FILTER,
        "  if (selected === null) return events;\n  return events.filter((event) => {\n",
        (
            "  if (selected === null) return events;\n"
            "  const kept = events.filter((event) => {\n"
            "    const pointer = pointerOf(event);\n"
            "    return pointer !== null && isAncestorOrSame(selected, pointer);\n"
            "  });\n"
            "  if (kept.length === 0) return events;\n"
            "  return events.filter((event) => {\n"
        ),
        ("pnpm", "test"),
    ),
    (
        # TS 側の期待値だけを動かすと、Python 側の突合（実 fixture × overlay の規則）が落ちる。
        "FILTER-expectation-drift",
        T_TRACE_TS,
        "    expect(found.map((row) => seqOf(row))).toEqual([3, 6, 9]);\n",
        "    expect(found.map((row) => seqOf(row))).toEqual([3, 6]);\n",
        ("py", [T_CONTRACT, "-k", "agrees_with_the_overlay_rule"]),
    ),
    # --- オーバーレイを描くのはレンダラ 1 本（要件書 §0）-------------------------------
    (
        "OVERLAY-computed-in-the-editor",
        CANVAS,
        'const OVERLAY_ID = "jin-editor-overlay";\n',
        'const OVERLAY_ID = "jin-editor-overlay";\nconst FIRED = "data-jin-fired";\n',
        ("py", [T_CONTRACT, "-k", "does_not_compute_the_overlay"]),
    ),
    # --- プロトコルを増やさない（要件書 §6.3 + ADR-011 の 6 種）------------------------
    (
        "PROTOCOL-adds-a-trace-request",
        PROTOCOL,
        '  save: "jin/save",\n',
        '  save: "jin/save",\n  openTrace: "jin/openTrace",\n',
        ("py", [T_CONTRACT, "-k", "does_not_add_a_new_lsp_request"]),
    ),
    (
        "PROTOCOL-trace-read-by-the-server",
        PANEL,
        '          type="file"\n',
        '          type="text"\n',
        ("py", [T_CONTRACT, "-k", "does_not_add_a_new_lsp_request"]),
    ),
    # --- 詳細パネル（machine 4 の弱い網）---------------------------------------------
    (
        "DETAIL-drops-the-output-field",
        PANEL,
        '                <pre data-testid="jin-detail-output">{render(detail.row["output"])}</pre>\n',
        '                <pre>{render(detail.row["output"])}</pre>\n',
        ("py", [T_CONTRACT, "-k", "detail_panel_shows_the_four_fields"]),
    ),
    (
        # 値を丸めると「モデル入出力を見る」という用途に反する。
        "DETAIL-truncates-the-value",
        PANEL,
        '  return JSON.stringify(value, null, 2) ?? "";\n',
        '  return (JSON.stringify(value) ?? "").slice(0, 40);\n',
        ("py", [T_CONTRACT, "-k", "detail_panel_shows_the_four_fields"]),
    ),
    # --- 5 状態を増やさない（DP-COMMON-19）-------------------------------------------
    (
        "VIEWSTATE-absorbs-the-trace",
        VIEWSTATE,
        "export const VIEW_STATE_KINDS = [\n",
        (
            "export type TraceHolder = { readonly trace: unknown; readonly upto: number };\n\n"
            "export const VIEW_STATE_KINDS = [\n"
        ),
        ("py", [T_CONTRACT, "-k", "not_folded_into_the_view_state"]),
    ),
    # --- e2e が実トレースを読む -------------------------------------------------------
    (
        "E2E-uses-a-hand-made-trace",
        SPEC,
        'const TRACE = join(REPO_ROOT, "tests/fixtures/traces/pipeline-fake.jsonl");\n',
        'const TRACE = join(REPO_ROOT, "tmp/made-up.jsonl");\n',
        ("py", [T_CONTRACT, "-k", "committed_trace_fixture"]),
    ),
    # --- サーバはどの行が悪いのかを言う（NFR-FAIL-001）--------------------------------
    (
        "LSP-trace-row-position-dropped",
        REQUESTS,
        'f"描画できません: トレースの {exc.index + 1} 件目: {exc}",\n',
        'f"描画できません: {exc}",\n',
        ("py", [T_SESSION, "-k", "names_the_offending_trace_row"]),
    ),
    (
        # 0 始まりのまま出すと、人が数える位置と 1 ずれる。
        "LSP-trace-row-position-is-zero-based",
        REQUESTS,
        'f"描画できません: トレースの {exc.index + 1} 件目: {exc}",\n',
        'f"描画できません: トレースの {exc.index} 件目: {exc}",\n',
        ("py", [T_SESSION, "-k", "names_the_offending_trace_row"]),
    ),
]

#: 「壊しても緑のままであるべき」変異は無い（Phase 5 と違い、緩められる既定値が無い）。
EXPECT_GREEN: dict[str, str] = {}


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
    real_modules = ROOT / "apps" / "editor" / "node_modules"
    if real_modules.is_dir():
        (dest / "apps" / "editor" / "node_modules").symlink_to(real_modules)


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


def _run_pnpm(copy: pathlib.Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pnpm", "run", script],
        cwd=copy / "apps" / "editor",
        capture_output=True,
        text=True,
        env=dict(os.environ, CI="1"),
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
    )


def _run(copy: pathlib.Path, check: tuple[str, object]) -> subprocess.CompletedProcess[str]:
    kind, argument = check
    if kind == "py":
        assert isinstance(argument, list)
        return _run_pytest(copy, argument)
    assert isinstance(argument, str)
    return _run_pnpm(copy, argument)


def _summary(result: subprocess.CompletedProcess[str]) -> str:
    interesting = ("passed", "failed", "error", "Tests ", "problem")
    lines = [ln.strip() for ln in result.stdout.splitlines() if any(w in ln for w in interesting)]
    if lines:
        return lines[-1][:110]
    tail = result.stderr.strip().splitlines()
    return tail[-1][:110] if tail else "(no summary)"


def _is_red(result: subprocess.CompletedProcess[str]) -> bool:
    """失敗していること。**exit 5（0 件選択）や収集エラーは赤に数えない。**"""
    if result.returncode in (0, 5):
        return False
    blob = result.stdout + result.stderr
    return any(
        word in blob for word in ("failed", "error TS", "problem", "✘", "Failed Tests", "error")
    )


def _is_green(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0


def main() -> int:
    only = {n for n in os.environ.get("MUTATE_ONLY", "").split(",") if n}
    unknown = only - {m[0] for m in MUTATIONS}
    if unknown:
        print(f"!! MUTATE_ONLY に存在しない変異名: {sorted(unknown)}")
        return 1

    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-p6-"))
    try:
        _copy_tree(copy)
        where = (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import jin_lsp, jin_render; "
                        "print(jin_lsp.__file__); print(jin_render.__file__)"
                    ),
                ],
                cwd=copy,
                capture_output=True,
                text=True,
                env=_env(copy),
                check=False,
            )
            .stdout.strip()
            .splitlines()
        )
        print(f"copy: {copy}")
        for line in where:
            print(f"imports from: {line}")
        if not where or not all(line.startswith(str(copy)) for line in where):
            print("!! jin_lsp / jin_render が隔離コピーを指していない。中止")
            return 2

        baseline_py = _run_pytest(copy, [T_CONTRACT, T_SESSION])
        if not _is_green(baseline_py):
            print("BASELINE (pytest) NOT GREEN")
            print(baseline_py.stdout[-3000:])
            return 2
        print(f"baseline pytest: green ({_summary(baseline_py)})")

        baseline_ts = _run_pnpm(copy, "test")
        baseline_tsc = _run_pnpm(copy, "typecheck")
        if not (_is_green(baseline_ts) and _is_green(baseline_tsc)):
            print("BASELINE (pnpm) NOT GREEN")
            print(baseline_ts.stdout[-1500:])
            print(baseline_tsc.stdout[-1500:])
            return 2
        print(f"baseline pnpm:   green ({_summary(baseline_ts)})")

        caught = 0
        skipped = 0
        mutations = [m for m in MUTATIONS if not only or m[0] in only]
        for name, rel, before, after, check in mutations:
            path = copy / rel
            original = path.read_text(encoding="utf-8")
            if before not in original:
                print(f"{name:38s} SKIP (pattern not found)")
                skipped += 1
                continue
            path.write_text(original.replace(before, after, 1), encoding="utf-8")
            try:
                result = _run(copy, check)
            except subprocess.TimeoutExpired:
                print(f"{name:38s} {'TIMEOUT (!! ハングした)':30s} {RUN_TIMEOUT_SECONDS}s")
                continue
            finally:
                path.write_text(original, encoding="utf-8")
            ok = _is_red(result)
            status = "RED (expected)" if ok else f"NOT RED (!! exit {result.returncode})"
            caught += ok
            print(f"{name:38s} {status:30s} [{check[0]}] {_summary(result)}")
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
