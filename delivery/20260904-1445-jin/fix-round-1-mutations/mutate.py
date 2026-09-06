"""各修正を 1 つずつ元に戻し、対応するテストが赤くなることを実測する（30 パターン）。

強めのミューテーションが必要だった 8 件（S8 / A-4 / S3 / S1-contract / S-1 / S-3 / S-4 / W-08）は
mutate2.py が担当する。どちらも対象ファイルを一時的に書き換えて必ず元へ戻す。
"""

import os, pathlib, shutil, subprocess

ROOT = pathlib.Path("/Users/toyota/PycharmProjects/jin-lang")


# --- 偽 green 対策（修正ラウンド 4 で発見・security review T-1 の作業中） ---------------
# Python の .pyc は「元ファイルの mtime（秒）とサイズ」で無効化を判定する。
# 連続する 2 つの変異が**同じサイズ**のファイルを生み、かつ同じ秒内に走ると、
# 2 本目が 1 本目のバイトコードを再利用して**緑になってしまう**。
# 実際に mutate4.py の T-1-replace で発生した（T-1-mkstemp と変異後サイズが 16574 で一致）。
# 毎回 __pycache__ を消し、新たに書かせない。
def _purge_pycache(root):
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _run_pytest(root, target):
    _purge_pycache(root / "packages")
    _purge_pycache(root / "tests")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        ["uv", "run", "pytest", "-q", "-p", "no:randomly", "--no-header", *target],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


MUTATIONS = [
    (
        "S2",
        "packages/jin-cli/src/jin_cli/resolver.py",
        "        except KeyboardInterrupt:\n            raise\n        except BaseException as exc:",
        "        except Exception as exc:",
        "packages/jin-cli/tests/test_cli.py -k system_exit",
    ),
    (
        "S9",
        "packages/jin-core/src/jin_core/ops.py",
        "    if not 0 <= index < len(circles):",
        "    if False:",
        "packages/jin-core/tests/test_ops.py -k out_of_range_circle_index",
    ),
    (
        "S10",
        "packages/jin-core/src/jin_core/pointer.py",
        "    if not (token.isascii() and token.isdigit()):\n"
        "        return False\n"
        '    return token == "0" or not token.startswith("0")',
        "    return token.lstrip('-').isdigit()",
        "packages/jin-core/tests/test_pointer.py",
    ),
    (
        "S4-parser",
        "packages/jin-core/src/jin_core/parser.py",
        "    if depth >= MAX_NESTING_DEPTH:",
        "    if False:",
        "packages/jin-core/tests/test_parser.py -k deep_nesting",
    ),
    (
        "S6",
        "packages/jin-cli/src/jin_cli/main.py",
        "    return text.translate(_CONTROL_TRANSLATION)",
        "    return text",
        "packages/jin-cli/tests/test_cli.py -k control_characters",
    ),
    (
        "S11",
        "packages/jin-cli/src/jin_cli/main.py",
        "                warning = _write_canonical(path, canonical)",
        '                warning = None\n                path.write_text(canonical, encoding="utf-8")',
        "packages/jin-cli/tests/test_cli.py -k replace_fails",
    ),
    (
        "S12",
        "packages/jin-cli/src/jin_cli/main.py",
        "        if path.is_symlink():",
        "        if False:",
        "packages/jin-cli/tests/test_cli.py -k symlink",
    ),
    (
        "S13",
        "packages/jin-core/src/jin_core/model.py",
        "        if is_control and not (allow_whitespace and ch in _ALLOWED_CONTROL):",
        "        if False:",
        "packages/jin-core/tests/test_model.py -k control_character packages/jin-core/tests/test_canonical.py -k "
        "rejected_by_the_model",
    ),
    (
        "A-1",
        "packages/jin-core/src/jin_core/ops.py",
        '        inverse["index"] = position',
        "        pass",
        "packages/jin-core/tests/test_ops.py -k toggle_await_inverse",
    ),
    (
        "A-2",
        "packages/jin-core/src/jin_core/ops.py",
        '    if op.get("pruneBoundary") is not True:\n        return',
        "    if True:\n        return",
        "packages/jin-core/tests/test_ops.py -k without_boundary_round_trips",
    ),
    (
        "A-3",
        "packages/jin-core/src/jin_core/ops.py",
        '    _require_segment(op, 2, "tools")\n    tools = _at(doc, f"/circles/{circle_index}/tools")',
        '    tools = _at(doc, f"/circles/{circle_index}/tools")',
        "packages/jin-core/tests/test_ops.py -k wrong_array",
    ),
    (
        "C-1",
        "packages/jin-core/src/jin_core/parser.py",
        "    elif char is not None:\n        found = repr(str(char))",
        "    elif False:\n        found = repr(str(char))",
        "packages/jin-core/tests/test_parser.py -k unexpected_characters",
    ),
    (
        "C-1-hint",
        "packages/jin-core/src/jin_core/parser.py",
        "    labels = [_readable(name) for name in expected]",
        "    labels = list(expected)",
        "packages/jin-core/tests/test_parser.py -k lark_terminal",
    ),
    (
        "C-2",
        "packages/jin-core/src/jin_core/parser.py",
        "            if key in seen:",
        "            if False:",
        "packages/jin-core/tests/test_parser.py -k duplicate_key tests/spec/test_spec_consistency.py -k "
        "duplicate_keys",
    ),
    (
        "D-1",
        "packages/jin-core/src/jin_core/canonical.py",
        "        elif 0xD800 <= ord(ch) <= 0xDFFF:",
        "        elif False:",
        "packages/jin-core/tests/test_canonical.py -k surrogate_is_rejected_by_the_writer",
    ),
    (
        "D-2",
        "packages/jin-core/src/jin_core/check.py",
        '        with path.open("r", encoding="utf-8", newline="") as handle:',
        '        with path.open("r", encoding="utf-8") as handle:',
        "packages/jin-cli/tests/test_cli.py -k crlf packages/jin-core/tests/test_check.py -k newlines",
    ),
    (
        "B-1",
        "packages/jin-core/src/jin_core/semantic.py",
        "            if len(unique_owners) == 1:",
        "            if False:",
        "packages/jin-core/tests/test_semantic.py -k same_parent_twice",
    ),
    (
        "B-2",
        "packages/jin-core/src/jin_core/semantic.py",
        "                if circle.flow.exit.key not in reachable:",
        "                if False:",
        "packages/jin-core/tests/test_semantic.py -k exit_key tests/spec/test_spec_consistency.py -k exit",
    ),
    (
        "B-3",
        "packages/jin-core/src/jin_core/model.py",
        '        if self.kind != "loop":',
        "        if False:",
        "packages/jin-core/tests/test_model.py -k loop tests/spec/test_spec_consistency.py -k loop_only",
    ),
    (
        "B-8",
        "packages/jin-core/src/jin_core/semantic.py",
        '            if match is not None and match.end() < n and rune[match.end()] == "}":',
        '            if (match is not None and match.end() < n and rune[match.end()] == "}"\n'
        '                    and not (match.end() + 1 < n and rune[match.end() + 1] == "}")):',
        "packages/jin-core/tests/test_semantic.py -k rune_keys tests/spec/test_spec_consistency.py -k "
        "rune_escape_rule",
    ),
    (
        "W-01",
        ".github/workflows/ci.yml",
        '      UV_LOCKED: "1"',
        '      OTHER: "1"',
        "tests/contract/test_ci_contract.py -k uv_locked",
    ),
    (
        "W-04",
        ".github/workflows/ci.yml",
        "      - name: Test\n        run: uv run pytest\n",
        "",
        "tests/contract/test_ci_contract.py -k drift",
    ),
    (
        "W-06a",
        ".python-version",
        "3.14",
        "latest",
        "tests/contract/test_ci_contract.py -k python_version",
    ),
    (
        "W-06b",
        ".github/workflows/ci.yml",
        "      - name: Install uv\n        uses: astral-sh/setup-uv@v5\n",
        "      - name: Install uv\n        uses: astral-sh/setup-uv@v5\n        with:\n          python-version-file: .python-version\n",
        "tests/contract/test_ci_contract.py -k nonexistent_input",
    ),
    (
        "W-06c",
        ".github/workflows/ci.yml",
        "      - name: Install uv\n        uses: astral-sh/setup-uv@v5\n",
        '      - name: Install uv\n        uses: astral-sh/setup-uv@v5\n        with:\n          python-version: "3.11"\n',
        "tests/contract/test_ci_contract.py -k hardcode",
    ),
    (
        "W-11",
        ".github/workflows/ci.yml",
        "    timeout-minutes: 15\n",
        "",
        "tests/contract/test_ci_contract.py -k timeout",
    ),
    (
        "W-03",
        "pyproject.toml",
        'testpaths = ["tests", "packages"]',
        'testpaths = ["tests", "packages/jin-core/tests"]',
        "tests/contract/test_packaging_contract.py -k collected",
    ),
    (
        "CONV-A1",
        "pyproject.toml",
        'addopts = "-q --import-mode=importlib"',
        'addopts = "-q"',
        "tests/contract/test_packaging_contract.py -k import_mode",
    ),
    (
        "S-2",
        "docs/spec/diagnostics.md",
        "| `flow.exit.key` が可視な state に無い | JIN011 | — |",
        "",
        "tests/spec/test_spec_consistency.py -k precedence",
    ),
    (
        "S-5",
        "docs/spec/model.md",
        "> **未確認**:",
        "> **確認済み**:",
        "tests/spec/test_spec_consistency.py -k unverified",
    ),
    (
        "S-6",
        "docs/spec/layout.md",
        "例: n=5 → k=2（{5/2}）、n=6 → k=1、",
        "例: n=5 → k=2（{5/2}）、n=6 → k=1（2 と 3 は gcd≠1）、",
        "tests/spec/test_spec_consistency.py -k star_polygon",
    ),
    (
        "ADR-014",
        "packages/jin-core/src/jin_core/semantic.py",
        '            elif parent.flow.kind == "loop":\n'
        "                siblings = [s for s in parent.flow.steps if s != current]",
        '            elif parent.flow.kind == "loop":\n                siblings = parent.flow.steps[:index]',
        "packages/jin-core/tests/test_semantic.py -k sibling tests/spec/test_spec_consistency.py -k "
        "upstream_rule_matches",
    ),
]


results = []
for name, rel, old, new, target in MUTATIONS:
    path = ROOT / rel
    original = path.read_text()
    if old not in original:
        results.append((name, "PATTERN-NOT-FOUND", ""))
        continue
    path.write_text(original.replace(old, new, 1))
    proc = _run_pytest(ROOT, ["-x", *target.split()])
    path.write_text(original)
    tail = [ln for ln in proc.stdout.splitlines() if "passed" in ln or "failed" in ln]
    if proc.returncode == 5:
        # pytest の「テストが 1 件も収集されなかった」。赤と誤認しない。
        verdict = "!!! 対象テストが無い !!!"
    else:
        verdict = "赤 (期待どおり)" if proc.returncode != 0 else "!!! 緑のまま !!!"
    results.append((name, verdict, tail[-1] if tail else ""))

width = max(len(r[0]) for r in results)
for name, verdict, tail in results:
    print(f"{name:<{width}}  {verdict:<18} {tail}")
