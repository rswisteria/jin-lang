"""修正ラウンド 2 の各修正を 1 つずつ元に戻し、対応テストが赤くなることを実測する。

ラウンド 1 の mutate.py / mutate2.py と同じ形式。対象ファイルは必ず元へ戻す。
ディレクトリ操作（N-02）だけは別扱いで `packages/<pkg>/tests` を退避して戻す。
"""
import os, pathlib, shutil, subprocess, tempfile

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
        cwd=root, capture_output=True, text=True, env=env)

MUTATIONS = [
 ("N-01a", ".github/workflows/ci.yml",
  "        run: uv sync\n",
  "        run: uv sync --frozen\n",
  ["tests/contract/test_ci_contract.py", "-k", "defeats or verifies_the_lock"]),

 ("N-01b", ".github/workflows/ci.yml",
  '      UV_LOCKED: "1"\n',
  '      UV_LOCKED: "1"\n      UV_FROZEN: "1"\n',
  ["tests/contract/test_ci_contract.py", "-k", "uv_frozen"]),

 ("N-01c", ".github/workflows/ci.yml",
  '          version: "0.12.9"\n',
  "",
  ["tests/contract/test_ci_contract.py", "-k", "uv_version_is_pinned"]),

 ("W-05", "pyproject.toml",
  'layers = [\n  "jin_cli",\n  "jin_core",\n]',
  'layers = [\n  "jin_cli",\n  "jin_adk",\n  "jin_render",\n  "jin_core",\n]',
  ["tests/contract/test_packaging_contract.py", "-k", "sibling_packages_in_one_element"]),

 ("W-05-parser", "tests/contract/test_packaging_contract.py",
  "        indexes = {element_of[name] for name in pair if name in element_of}\n        if len(indexes) < 2:",
  "        indexes = {element_of[name] for name in pair if name in element_of}\n        if True:",
  ["tests/contract/test_packaging_contract.py", "-k", "naive_serial"]),

 ("N1", "packages/jin-cli/src/jin_cli/main.py",
  "        shutil.copymode(path, temporary)\n",
  "",
  ["packages/jin-cli/tests/test_cli.py", "-k", "preserves_the_file_mode or widen"]),

 # 修正ラウンド 4（T-1）で except 節が OSError へ広がったのでパターンを更新した。
 # 狙いは変えていない: AtomicWriteUnavailable への変換を壊すと N2 の退避が働かなくなる。
 ("N2a", "packages/jin-cli/src/jin_cli/main.py",
  "    except OSError as exc:\n        raise _classify_write_failure(exc, path) from exc\n    try:",
  "    except OSError as exc:\n        raise OSError(str(exc)) from exc\n    try:",
  ["packages/jin-cli/tests/test_cli.py", "-k", "read_only_directory or neither_file_nor_directory"]),

 ("N2b", "packages/jin-cli/src/jin_cli/main.py",
  "        if not os.access(path, os.W_OK):\n            raise\n        _write_in_place(path, text)",
  "        raise\n        _write_in_place(path, text)",
  ["packages/jin-cli/tests/test_cli.py", "-k", "read_only_directory"]),

 ("D-4", "packages/jin-cli/src/jin_cli/main.py",
  '            if path.suffix != ".jin":',
  "            if False:",
  ["packages/jin-cli/tests/test_cli.py", "-k", "named_non_jin"]),

 ("D-4-dump", "packages/jin-cli/src/jin_cli/main.py",
  '    if file.is_file() and file.suffix != ".jin":',
  "    if False:",
  ["packages/jin-cli/tests/test_cli.py", "-k", "dump_rejects"]),

 ("E-1", "packages/jin-core/src/jin_core/canonical.py",
  'INDENT = "  "',
  'INDENT = "    "',
  ["tests/contract/test_canonical_contract.py", "-k", "rule1"]),

 ("E-2", "packages/jin-core/src/jin_core/canonical.py",
  '        elif ord(ch) < 0x20:\n            out.append(f"\\\\u{ord(ch):04x}")',
  '        elif ord(ch) < 0x20 or ord(ch) == 0xE9:\n            out.append(f"\\\\u{ord(ch):04x}")',
  ["tests/contract/test_canonical_contract.py", "-k", "rule5"]),

 ("E-3", "packages/jin-core/src/jin_core/canonical.py",
  "def _is_default(field: Any, value: Any) -> bool:",
  "def _is_default(field: Any, value: Any) -> bool:\n    if isinstance(value, bool):\n        return True",
  ["tests/contract/test_canonical_contract.py", "-k", "rule7"]),

 ("E-5-bom", "packages/jin-core/src/jin_core/parser.py",
  '    if text.startswith("\\ufeff"):',
  "    if False:",
  ["packages/jin-core/tests/test_parser.py", "-k", "bom"]),

 ("E-5-steps", "packages/jin-core/src/jin_core/ops.py",
  '                flow["steps"] = [new_name if s == old else s for s in flow.get("steps") or []]',
  "                pass",
  ["packages/jin-core/tests/test_ops.py", "-k", "follows_flow_steps"]),

 ("E-5-delegate", "packages/jin-core/src/jin_core/ops.py",
  '            other["delegate"] = [new_name if d == old else d for d in other.get("delegate") or []]',
  "            pass",
  ["packages/jin-core/tests/test_ops.py", "-k", "follows_delegate"]),

 ("N-2a", "docs/spec/model.md",
  "### 3.6 文字列の制約",
  "### 3.6 （削除）",
  ["tests/spec/test_spec_consistency.py", "-k", "string_constraints or control_character_rule"]),

 ("N-2b", "docs/spec/model.md",
  "| 識別子 | `root` / `circles[].name`",
  "| 識別子 | `circles[].name`",
  ["tests/spec/test_spec_consistency.py", "-k", "every_string_field"]),

 ("N-2c", "docs/spec/model.md",
  "> **受理範囲との関係**（§3.6）",
  "> **参考**",
  ["tests/spec/test_spec_consistency.py", "-k", "reconciles_the_writer"]),

 ("N-3", "docs/spec/model.md",
  "<!-- machine-readable: schema-gaps -->",
  "<!-- machine-readable: schema-gaps-removed -->",
  ["tests/spec/test_spec_consistency.py", "-k", "schema_gaps"]),
]

results = []
for name, rel, old, new, target in MUTATIONS:
    path = ROOT / rel
    original = path.read_text()
    if old not in original:
        results.append((name, "PATTERN-NOT-FOUND", ""))
        continue
    path.write_text(original.replace(old, new, 1))
    proc = _run_pytest(ROOT, target)
    path.write_text(original)
    tail = [ln for ln in proc.stdout.splitlines() if "passed" in ln or "failed" in ln]
    if proc.returncode == 5:
        # pytest の「テストが 1 件も収集されなかった」。赤と誤認しない。
        verdict = "!!! 対象テストが無い !!!"
    else:
        verdict = "赤 (期待どおり)" if proc.returncode != 0 else "!!! 緑のまま !!!"
    results.append((name, verdict, tail[-1] if tail else ""))

# N-02 はディレクトリを消す変異なので別扱い。
backup = pathlib.Path(tempfile.mkdtemp()) / "tests"
target_dir = ROOT / "packages" / "jin-cli" / "tests"
shutil.copytree(target_dir, backup)
try:
    shutil.rmtree(target_dir)
    proc = _run_pytest(ROOT, ["tests/contract/test_packaging_contract.py"])
finally:
    if not target_dir.exists():
        shutil.copytree(backup, target_dir)
    shutil.rmtree(backup.parent, ignore_errors=True)
tail = [ln for ln in proc.stdout.splitlines() if "passed" in ln or "failed" in ln]
skipped = "skipped" in proc.stdout
results.append(("N-02", "赤 (期待どおり)" if proc.returncode != 0 and not skipped
                else "!!! 緑のまま !!!", tail[-1] if tail else ""))

width = max(len(r[0]) for r in results)
for name, verdict, tail in results:
    print(f"{name:<{width}}  {verdict:<18} {tail}")
