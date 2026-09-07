"""Phase 4（jin-lsp）の主要な防御を 1 つずつ壊し、対応テストが赤くなることを実測する。

`phase3-mutations/mutate_p3.py` と同じ流儀:

**隔離コピー上で変異する**。`packages/` `tests/` `examples/` `plugins/` `scripts/` `docs/`
`schemas/` `pyproject.toml` を一時ディレクトリへ複製し、`PYTHONPATH` にコピー側の `src` を
並べて pytest を走らせる。実ツリーは 1 バイトも書き換えない（起動時に `jin_lsp.__file__` が
コピー側を指すことを印字して確かめる）。

判定: 「赤」は **`returncode == 1` かつ summary に `failed`** があるとき。`-k` が 0 件を選ぶ exit 5 /
ファイル欠落 exit 4 / collection error は赤に数えない。`SKIP (pattern not found)` も caught に
数えず、1 件でもあれば exit 1。

実行: `uv run python delivery/20260904-1445-jin/phase4-mutations/mutate_p4.py`
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
#: 隔離コピーへ持っていくもの。**`tests/spec/` は要件書と `delivery/` を読む**ので
#: それらも要る（足りないと baseline が FileNotFoundError で赤くなる）。
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
    "pyproject.toml",
]

POSITIONS = "packages/jin-lsp/src/jin_lsp/positions.py"
SESSION = "packages/jin-lsp/src/jin_lsp/session.py"
SERVER = "packages/jin-lsp/src/jin_lsp/server.py"
LOGS = "packages/jin-lsp/src/jin_lsp/logs.py"
FILEIO = "packages/jin-lsp/src/jin_lsp/fileio.py"
PROTOCOL = "packages/jin-lsp/src/jin_lsp/protocol.py"
EDITS = "packages/jin-lsp/src/jin_lsp/features/edits.py"
REQUESTS = "packages/jin-lsp/src/jin_lsp/requests.py"
CHECK = "packages/jin-core/src/jin_core/check.py"

T_POSITIONS = "packages/jin-lsp/tests/test_positions.py"
T_SESSION = "packages/jin-lsp/tests/test_session.py"
T_STDIO = "packages/jin-lsp/tests/test_stdio_roundtrip.py"
T_WS = "packages/jin-lsp/tests/test_ws_roundtrip.py"
T_FEATURES = "packages/jin-lsp/tests/test_features.py"
T_APPLY = "packages/jin-lsp/tests/test_apply_ops_roundtrip.py"
T_PERF = "packages/jin-lsp/tests/test_performance.py"
T_LSP_CONTRACT = "tests/contract/test_lsp_contract.py"
T_PLUGIN = "tests/contract/test_plugin_contract.py"
T_GUARD = "tests/contract/test_guard_claims.py"
T_SPEC = "tests/spec/test_spec_consistency.py"
T_CORE_CHECK = "packages/jin-core/tests/test_check.py"

#: (名前, 対象ファイル, before, after, pytest 引数)
MUTATIONS: list[tuple[str, str, str, str, list[str]]] = [
    # --- DP-COMMON-14: stdio の stdout は JSON-RPC の通信路である ----------------------
    (
        "LOG-stdout",
        LOGS,
        "    handler = logging.StreamHandler(stream=sys.stderr)\n",
        "    handler = logging.StreamHandler(stream=sys.stdout)\n",
        [T_GUARD, "-k", "guard_claims_point_at_real_guards"],
    ),
    (
        "LOG-print-to-stdout",
        SERVER,
        "            sys.stderr.write(f\"{TOKEN_PREFIX}{files.token}\\n\")\n",
        "            print(f\"{TOKEN_PREFIX}{files.token}\")\n",
        [T_LSP_CONTRACT, "-k", "never_prints_to_stdout"],
    ),
    # --- DP-COMMON-07 / NFR-AVAIL-001: last-good モデル 1 世代 -------------------------
    (
        "LASTGOOD-drop",
        SESSION,
        "            last_good=previous.last_good if previous is not None else None,\n",
        "            last_good=None,\n",
        [T_SESSION, T_STDIO, "-k", "last_good or falls_back"],
    ),
    (
        "LASTGOOD-semantic-error-discarded",
        SESSION,
        "        if result.model is not None and result.table is not None:\n",
        "        if result.model is not None and result.table is not None and not result.diagnostics:\n",
        [T_SESSION, "-k", "semantic_error_still_updates"],
    ),
    # --- 位置変換（docs/spec/diagnostics.md §5.1）--------------------------------------
    (
        "POS-off-by-one",
        POSITIONS,
        "    server_position = types.Position(line=position.line - 1, character=position.col - 1)\n",
        "    server_position = types.Position(line=position.line, character=position.col)\n",
        [T_POSITIONS, "-k", "ascii_only or one_based"],
    ),
    (
        "POS-no-utf16",
        POSITIONS,
        "    return _CODEC.position_to_client_units(lines, server_position)\n",
        "    return server_position\n",
        [T_POSITIONS, T_GUARD, "-k", "astral or guard_claims_point_at_real_guards"],
    ),
    (
        "POS-hint-not-in-message",
        POSITIONS,
        '        message = f"{message}\\n{diagnostic.hint}"\n',
        "        pass\n",
        [T_POSITIONS, "-k", "carries_code_severity_and_hint"],
    ),
    # --- 段階診断（前段が通らなければ後段を出さない）------------------------------------
    (
        # 段階診断そのもの（構文 → スキーマ → 意味の early return）は `jin_core.check` に
        # あり、Phase 1 の網が見ている。ここで壊すと `parsed` が未定義のままサーバが
        # 起動時に落ち、クライアントが `wait_for_notification` で**永久に待つ**
        # （= ハングであって赤ではない・実測で踏んだ）。
        # Phase 4 の関心事は「診断が LSP に載って届くこと」なので、そちらを壊す。
        "DIAG-not-published",
        SERVER,
        "                diagnostics=[\n"
        "                    positions.to_lsp_diagnostic(state.lines, diagnostic)\n"
        "                    for diagnostic in state.diagnostics\n"
        "                ],\n",
        "                diagnostics=[],\n",
        [T_STDIO, "-k", "jin001 or jin002 or stage_three or hint"],
    ),
    # --- ADR-011: jin/open と jin/save の 4 段の防御 -------------------------------------
    (
        "FILE-no-root-check",
        FILEIO,
        "            raw.resolve().relative_to(self.root)\n",
        "            pass\n",
        [T_WS, "-k", "outside_the_root"],
    ),
    (
        "FILE-follow-symlink",
        FILEIO,
        "        if raw.is_symlink():\n",
        "        if False:\n",
        [T_WS, "-k", "symlink"],
    ),
    (
        "FILE-token-always-ok",
        FILEIO,
        "        if not isinstance(presented, str) or not secrets.compare_digest(\n"
        '            presented.encode("utf-8"), self.token.encode("utf-8")\n'
        "        ):\n",
        "        if False:\n",
        [T_WS, "-k", "wrong_token"],
    ),
    (
        "FILE-enabled-without-root",
        FILEIO,
        "        if not self.enabled:\n",
        "        if False:\n",
        [T_WS, "-k", "without_a_root"],
    ),
    (
        "FILE-any-suffix",
        FILEIO,
        "        if raw.suffix != ALLOWED_SUFFIX:\n",
        "        if False:\n",
        [T_WS, "-k", "non_jin_suffix"],
    ),
    (
        "FILE-save-broken-text",
        SERVER,
        "        if state.model is None:\n            raise requests.RequestError(\n"
        '                "JIN001",\n                "構文エラーのあるテキストは保存しません",\n',
        "        if False:\n            raise requests.RequestError(\n"
        '                "JIN001",\n                "構文エラーのあるテキストは保存しません",\n',
        [T_WS, "-k", "refuses_a_syntax_error"],
    ),
    # --- プロトコル: 未知メソッドの params / result を素の JSON で受ける -----------------
    (
        "PROTO-default-converter",
        PROTOCOL,
        "    converter.register_structure_hook(JsonRPCRequestMessage, keep_params_plain)\n",
        "    pass\n",
        [T_APPLY, "-k", "reparse_matches or restores_the_canonical"],
    ),
    # --- codeAction: JIN020 の抽出は JIN020 を解消しなければならない ----------------------
    (
        "EXTRACT-keeps-twelve",
        EDITS,
        "    keep = MAX_ELEMENTS - 1\n",
        "    keep = MAX_ELEMENTS\n",
        [T_FEATURES, "-k", "extracts_the_overflowing"],
    ),
    # --- jin/model の対応表は配列（pygls の rename=True で鍵が消えない形）----------------
    (
        "POINTERS-as-object",
        REQUESTS,
        '        {"pointer": pointer, **range_.to_json_dict()}\n',
        '        {**range_.to_json_dict()}\n',
        [T_STDIO, "-k", "jin_model_returns"],
    ),
    # --- jin/ops は 19 件（20 個目を足さない）--------------------------------------------
    (
        "OPS-twentieth",
        REQUESTS,
        '    {"name": "rename", "target": "対象要素（circle / tool / state）", "inverse": "rename"},\n',
        '    {"name": "rename", "target": "対象要素（circle / tool / state）", "inverse": "rename"},\n'
        '    {"name": "explode", "target": "/circles", "inverse": "explode"},\n',
        [T_SPEC, T_STDIO, "-k", "jin_ops or twentieth"],
    ),
    # --- 判別共用体（Annotated）を剥がす ------------------------------------------------
    (
        "UNWRAP-no-annotated",
        CHECK,
        "    if origin is Annotated:\n        args = get_args(annotation)\n"
        "        return _unwrap(args[0]) if args else []\n",
        "    if False:\n        args = get_args(annotation)\n"
        "        return _unwrap(args[0]) if args else []\n",
        [T_CORE_CHECK, T_FEATURES, "-k", "discriminated_union or tool_keys or enum_values"],
    ),
    # --- デバウンス（打鍵の連打で計算を積み上げない）--------------------------------------
    (
        "DEBOUNCE-no-cancel",
        SERVER,
        "        self.cancel_pending(uri)\n"
        "        self._pending[uri] = asyncio.create_task(self._debounced(uri, text, version))\n",
        "        self._pending[uri] = asyncio.create_task(self._debounced(uri, text, version))\n",
        [T_PERF, "-k", "burst_of_edits"],
    ),
    (
        "DEBOUNCE-on-did-open",
        SERVER,
        "        ls.analyze_now(document.uri, document.text, document.version)\n",
        "        ls.schedule_analysis(document.uri, document.text, document.version)\n",
        [T_PERF, T_STDIO, "-k", "within_a_second or not_debounced"],
    ),
    # --- プラグインの reference は正典のコピー -------------------------------------------
    (
        "PLUGIN-stale-reference",
        "plugins/claude-code/jin/skills/jin-lang/reference/model.md",
        "# Jin モデル仕様（model.md）",
        "# 古い写し",
        [T_PLUGIN, "-k", "reference_copy_matches"],
    ),
]

#: 変異させても**緑のままであるべき**もの（そういう主張をテストにしていない）。
EXPECT_GREEN: set[str] = set()
EXPECT_GREEN_REASON: dict[str, str] = {}


def _copy_tree(dest: pathlib.Path) -> None:
    for item in COPY_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(
                src, dest / item, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
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


#: 1 変異あたりの上限（秒）。**これが無いとハングが「実行中」に見えて気づけない。**
#: Phase 4 の変異は LSP サーバをサブプロセスで起こすものが多く、変異によっては
#: サーバが起動時にクラッシュして、クライアントが `wait_for_notification` で
#: **永久に待つ**（実測で踏んだ）。時間切れは「赤」ではなく別の状態として報告する。
RUN_TIMEOUT_SECONDS = 300


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
    lines = [
        ln for ln in result.stdout.splitlines() if "passed" in ln or "failed" in ln or "error" in ln
    ]
    if lines:
        return lines[-1]
    tail = result.stderr.strip().splitlines()
    return tail[-1] if tail else "(no summary)"


def _is_red(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 1 and "failed" in _summary(result)


def _is_green(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0 and "passed" in _summary(result)


def main() -> int:
    # `MUTATE_ONLY` の綴り違いは baseline の**前**に落とす（F-W-P3-009）。
    # 隔離コピーと baseline に数秒かけてから「0 件が緑」で終わると成功に見える。
    only = {n for n in os.environ.get("MUTATE_ONLY", "").split(",") if n}
    unknown = only - {m[0] for m in MUTATIONS}
    if unknown:
        print(f"!! MUTATE_ONLY に存在しない変異名: {sorted(unknown)}")
        return 1

    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-p4-"))
    try:
        _copy_tree(copy)
        where = (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import jin_lsp, jin_cli; print(jin_lsp.__file__); print(jin_cli.__file__)",
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
            print("!! jin_lsp / jin_cli が隔離コピーを指していない。中止")
            return 2
        baseline = _run_pytest(
            copy,
            [
                "packages/jin-lsp/tests",
                T_CORE_CHECK,
                T_GUARD,
                T_LSP_CONTRACT,
                T_PLUGIN,
                T_SPEC,
            ],
        )
        if not _is_green(baseline):
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
                print(f"{name:28s} SKIP (pattern not found)")
                skipped += 1
                continue
            mutated = original.replace(before, after, 1)
            path.write_text(mutated, encoding="utf-8")
            try:
                result = _run_pytest(copy, target)
            except subprocess.TimeoutExpired:
                path.write_text(original, encoding="utf-8")
                print(f"{name:32s} {'TIMEOUT (!! ハングした)':34s} {RUN_TIMEOUT_SECONDS}s")
                continue
            finally:
                path.write_text(original, encoding="utf-8")
            if name in EXPECT_GREEN:
                ok = _is_green(result)
                why = EXPECT_GREEN_REASON.get(name, "期待どおり")
                status = f"GREEN (expected: {why})" if ok else f"RED (!! {why} が成立しない)"
            else:
                ok = _is_red(result)
                if ok:
                    status = "RED (expected)"
                elif result.returncode == 0:
                    status = "GREEN (!! not caught)"
                else:
                    status = f"NOT RED (!! exit {result.returncode})"
            caught += ok
            print(f"{name:28s} {status:34s} {_summary(result)}")
        subset = (
            f" (subset of {len(MUTATIONS)}; MUTATE_ONLY={','.join(sorted(only))})" if only else ""
        )
        print(
            f"{caught}/{len(mutations)} mutations caught{subset}"
            + (f" ({skipped} skipped)" if skipped else "")
        )
        return 0 if mutations and caught == len(mutations) and skipped == 0 else 1
    finally:
        shutil.rmtree(copy, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
