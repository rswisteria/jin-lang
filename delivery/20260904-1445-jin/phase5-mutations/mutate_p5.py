"""Phase 5（apps/editor + `jin editor`）の主要な防御を 1 つずつ壊し、赤くなることを実測する。

`phase4-mutations/mutate_p4.py` と同じ流儀だが、**検査が 2 系統ある**のが違う:

- Python 側（pytest）— `jin editor` の入口・ws の再接続・契約テスト
- **TS 側（pnpm）** — 5 状態の網羅（tsc）/ 選択再解決（vitest）/
  schema からのフォーム生成（vitest）/ 依存方向（eslint の注入テスト）

隔離コピー上で変異する。`apps/editor` もコピーし、`node_modules` だけは
**実ツリーへの symlink** にする（数万ファイルの複製を避けるため。変異するのは
`src/` `test/` `eslint.config.js` だけなので、実ツリーの `node_modules` は書き換わらない）。

判定: 「赤」は **`returncode != 0` かつ出力に失敗の印**があるとき。
`SKIP (pattern not found)` は caught に数えず、1 件でもあれば exit 1。

実行: `uv run python delivery/20260904-1445-jin/phase5-mutations/mutate_p5.py`
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

EDITOR_PY = "packages/jin-cli/src/jin_cli/editor.py"
SERVER = "packages/jin-lsp/src/jin_lsp/server.py"
CI = ".github/workflows/ci.yml"
ESLINT = "apps/editor/eslint.config.js"
VIEWSTATE = "apps/editor/src/state/viewState.ts"
SELECTION = "apps/editor/src/state/selection.ts"
SCHEMAFORM = "apps/editor/src/form/schemaForm.ts"
DISPATCH = "apps/editor/src/form/dispatch.ts"
CANVAS = "apps/editor/src/svg/SvgCanvas.tsx"
FIXTURE = "apps/editor/test/exhaustiveness.fixture.ts"
PACKAGE_JSON = "apps/editor/package.json"
MAIN_TSX = "apps/editor/src/main.tsx"

T_EDITOR = "packages/jin-cli/tests/test_editor.py"
T_WS = "packages/jin-lsp/tests/test_ws_roundtrip.py"
T_GUARD = "tests/contract/test_guard_claims.py"
T_CONTRACT = "tests/contract/test_editor_contract.py"
T_DEPS = "tests/contract/test_dependency_direction.py"
T_CI = "tests/contract/test_ci_contract.py"

#: (名前, 対象ファイル, before, after, 検査) — 検査は ("py", [pytest 引数]) か ("pnpm", "スクリプト名")
MUTATIONS: list[tuple[str, str, str, str, tuple[str, object]]] = [
    # --- `jin editor` の入口（要件書 §7.3）------------------------------------------
    (
        "EDITOR-serves-cwd",
        EDITOR_PY,
        "    return partial(_StaticHandler, directory=str(root))\n",
        "    return partial(_StaticHandler)\n",
        ("py", [T_EDITOR, "-k", "only_serves_the_dist"]),
    ),
    (
        "EDITOR-token-in-query",
        EDITOR_PY,
        "    return f\"http://{host}:{http_port}/?{query}#token={quote(token, safe='')}\"\n",
        "    return f\"http://{host}:{http_port}/?{query}&token={quote(token, safe='')}\"\n",
        ("py", [T_EDITOR, "-k", "fragment"]),
    ),
    (
        "EDITOR-accepts-any-suffix",
        EDITOR_PY,
        '    if target.suffix != ".jin":\n',
        "    if False:\n",
        ("py", [T_EDITOR, "-k", "non_jin"]),
    ),
    (
        "EDITOR-root-is-grandparent",
        EDITOR_PY,
        "    return target.parent\n",
        "    return target.parent.parent\n",
        ("py", [T_EDITOR, "-k", "writable_root"]),
    ),
    (
        "EDITOR-missing-dist-ignored",
        EDITOR_PY,
        '    if not (root / "index.html").is_file():\n',
        "    if False:\n",
        ("py", [T_EDITOR, "-k", "index_html or missing_build"]),
    ),
    (
        # `_static_server` が `_handler_for` を経由しなくなると、配信の根の固定が
        # 1 箇所に閉じているという `guard:` の主張が成り立たない。
        "EDITOR-guard-claim-bypassed",
        EDITOR_PY,
        "    return ThreadingHTTPServer((host, 0), _handler_for(root))\n",
        "    return ThreadingHTTPServer((host, 0), _StaticHandler)\n",
        ("py", [T_GUARD, "-k", "guard_claims_point_at_real_guards"]),
    ),
    (
        "EDITOR-uses-pygls-start-ws",
        EDITOR_PY,
        "        server.serve_ws(host, address.ws_port)\n",
        "        server.start_ws(host, address.ws_port)\n",
        ("py", [T_CONTRACT, "-k", "pygls_start_ws"]),
    ),
    # --- ws の再接続（Phase 5 で直した欠陥）------------------------------------------
    (
        "WS-shutdown-after-one-client",
        SERVER,
        "        async def run() -> None:\n",
        "        self.start_ws(host, port)\n        return\n\n        async def run() -> None:\n",
        ("py", [T_WS, "-k", "reconnect"]),
    ),
    (
        "WS-shared-stop-event",
        SERVER,
        "                stop_event=threading.Event(),\n",
        "                stop_event=_SHARED_STOP,\n",
        ("py", [T_WS, "-k", "reconnect"]),
    ),
    # --- 依存方向（DP-COMMON-11 の 2 本目）-------------------------------------------
    (
        "DEPS-eslint-rule-removed",
        ESLINT,
        '      "no-restricted-imports": ["error", { patterns: FORBIDDEN_IMPORT_PATTERNS }],\n',
        "",
        ("py", [T_DEPS, "-k", "pnpm_side"]),
    ),
    (
        "DEPS-eslint-rule-removed-ts",
        ESLINT,
        '      "no-restricted-imports": ["error", { patterns: FORBIDDEN_IMPORT_PATTERNS }],\n',
        "",
        ("pnpm", "test"),
    ),
    (
        "DEPS-packages-pattern-removed",
        ESLINT,
        '    group: ["**/packages/**"],\n',
        '    group: ["**/__never__/**"],\n',
        ("pnpm", "test"),
    ),
    (
        "DEPS-editor-imports-python",
        MAIN_TSX,
        'import { App } from "./App";\n',
        'import { App } from "./App";\nimport * as core from "../../../packages/jin-core/src/jin_core/model";\n',
        ("py", [T_DEPS, "-k", "sources"]),
    ),
    # --- DP-COMMON-19: 5 状態と網羅性 ------------------------------------------------
    (
        "VIEWSTATE-three-states",
        VIEWSTATE,
        '  "ready",\n  "stale",\n  "unavailable",\n',
        '  "ready",\n',
        ("py", [T_CONTRACT, "-k", "five_view_states"]),
    ),
    (
        "VIEWSTATE-kinds-renamed",
        VIEWSTATE,
        '  "disconnected",\n',
        '  "offline",\n',
        ("py", [T_CONTRACT, "-k", "five_view_states"]),
    ),
    (
        "VIEWSTATE-exhaustiveness-tripwire-removed",
        FIXTURE,
        "  // @ts-expect-error 分岐が 1 つ欠けているので state は never にならない\n",
        "",
        ("py", [T_CONTRACT, "-k", "exhaustiveness_tripwire"]),
    ),
    (
        "VIEWSTATE-exhaustiveness-off",
        VIEWSTATE,
        '  | { readonly kind: "unavailable"; readonly uri: string; readonly message: string };\n',
        (
            '  | { readonly kind: "unavailable"; readonly uri: string; readonly message: string }\n'
            "  | { readonly kind: string };\n"
        ),
        ("pnpm", "typecheck"),
    ),
    (
        "VIEWSTATE-fixture-branch-added",
        FIXTURE,
        "    // `unavailable` を書かない。\n",
        '    case "unavailable":\n      return "5";\n',
        ("pnpm", "typecheck"),
    ),
    # --- DP-COMMON-16: 選択の再解決 ---------------------------------------------------
    (
        "SELECTION-raw-index",
        SELECTION,
        (
            "  const index = circles(model).findIndex("
            '(circle) => nameOf(circle, "name") === selection.circle);\n'
        ),
        "  const index = 0;\n",
        ("pnpm", "test"),
    ),
    (
        "SELECTION-ignores-circle-scope",
        SELECTION,
        "  return list.findIndex((item) => nameOf(item, key) === name);\n",
        "  return 0;\n",
        ("pnpm", "test"),
    ),
    (
        "SELECTION-rename-not-followed",
        SELECTION,
        "    return { ...selection, name: op.name };\n",
        "    return selection;\n",
        ("pnpm", "test"),
    ),
    # --- 要件書 §7.1: フォームは JSON Schema から生成する -------------------------------
    (
        "FORM-hard-coded-fields",
        SCHEMAFORM,
        "  const properties = objectSchema.properties ?? {};\n",
        '  const properties = { name: { type: "string" } } as Record<string, JsonSchema>;\n',
        ("pnpm", "test"),
    ),
    (
        "FORM-drops-enum-options",
        SCHEMAFORM,
        "      options: schema.enum === undefined ? null : schema.enum.map((value) => String(value)),\n",
        "      options: null,\n",
        ("pnpm", "test"),
    ),
    (
        "FORM-schema-copy-in-editor",
        PACKAGE_JSON,
        '    "vite": "8.2.2"',
        '    "vite": "^8.2.2"',
        ("py", [T_CONTRACT, "-k", "pinned_to_an_exact_version"]),
    ),
    # --- 20 個目のオペレーションを作らない / 陣を描かない -------------------------------
    (
        "OPS-twentieth-operation",
        DISPATCH,
        '      return [{ op: "setCore", pointer: circlePointer, value }];\n',
        '      return [{ op: "setToolRef", pointer: circlePointer, value }];\n',
        ("py", [T_CONTRACT, "-k", "twentieth"]),
    ),
    (
        "RENDER-editor-draws-a-path",
        CANVAS,
        '  const badge = document.createElementNS(ns, "circle");\n',
        '  const badge = document.createElementNS(ns, "path");\n',
        ("py", [T_CONTRACT, "-k", "never_draws"]),
    ),
    # --- CI の受け皿（DP-REVIEW-JIN-003 / Issue #9）-----------------------------------
    (
        "CI-no-editor-job",
        CI,
        "  editor:\n",
        "  editor_disabled:\n",
        ("py", [T_CI, "-k", "editor_gates"]),
    ),
    (
        "CI-no-pnpm",
        CI,
        "      - uses: pnpm/action-setup@v4\n",
        "",
        ("py", [T_CI, "-k", "node_toolchain"]),
    ),
    (
        "CI-no-smoke",
        CI,
        "        run: pnpm e2e\n",
        "        run: echo skip\n",
        ("py", [T_CI, "-k", "editor_gates"]),
    ),
    (
        "CI-lockfile-not-frozen",
        CI,
        "        run: pnpm install --frozen-lockfile\n",
        "        run: pnpm install\n",
        ("py", [T_CI, "-k", "editor_gates"]),
    ),
]

#: 壊しても緑のまま**であるべき**もの（二層防御が効いていることの確認）。
EXPECT_GREEN: dict[str, str] = {}

RUN_TIMEOUT_SECONDS = 600


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
    # `node_modules` は**実ツリーへの symlink**。数万ファイルを複製しないため。
    # 変異するのは `src/` `test/` `eslint.config.js` `package.json` だけなので、
    # 実ツリーの `node_modules` は書き換わらない。
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
    if result.returncode == 0:
        return False
    if result.returncode == 5:
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

    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-p5-"))
    try:
        _copy_tree(copy)
        where = (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import jin_cli, jin_lsp; print(jin_cli.__file__); print(jin_lsp.__file__)",
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
            print("!! jin_cli / jin_lsp が隔離コピーを指していない。中止")
            return 2

        baseline_py = _run_pytest(copy, [T_EDITOR, T_WS, T_GUARD, T_CONTRACT, T_DEPS, T_CI])
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
            if name in EXPECT_GREEN:
                ok = _is_green(result)
                status = (
                    f"GREEN (expected: {EXPECT_GREEN[name]})"
                    if ok
                    else f"RED (!! {EXPECT_GREEN[name]} が成立しない)"
                )
            else:
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
