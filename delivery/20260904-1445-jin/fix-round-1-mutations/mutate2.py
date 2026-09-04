"""緑のままだった 8 件について、ミューテーションを強めて再実測する。"""
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
        cwd=root, capture_output=True, text=True, env=env)

MUTATIONS = [
 ("S8", "packages/jin-core/src/jin_core/semantic.py",
  '    out: list[str] = []\n    last = 0\n    for start, end, key in rune_key_spans(rune):',
  '    import re as _re\n\n    return _re.compile(r"(?<!\\{)\\{" + _re.escape(old) + r"\\}(?!\\})").sub(\n        "{" + new + "}", rune\n    )\n    out: list[str] = []\n    last = 0\n    for start, end, key in rune_key_spans(rune):',
  ["packages/jin-core/tests/test_semantic.py", "-k", "replace_rune_key_treats"]),

 ("A-4", "packages/jin-core/src/jin_core/ops.py",
  "        circle_index = _circle_index(doc, op, 2)",
  "        circle_index = _circle_index(doc, op, len(tokens))",
  ["packages/jin-core/tests/test_ops.py", "-k", "literal_expected_depth"]),

 ("S3", "packages/jin-core/src/jin_core/semantic.py",
  "        distance = levenshtein(target, candidate, limit=threshold)",
  "        distance = levenshtein(target, candidate)",
  ["packages/jin-core/tests/test_semantic.py", "-k", "threshold_as_a_limit"]),

 ("S1-contract", "pyproject.toml",
  'forbidden_modules = ["jin_cli.resolver"]',
  'forbidden_modules = ["jin_cli.nonexistent_typo"]',
  ["tests/contract/test_dependency_direction.py", "-k", "bites"]),

 ("S-1", "docs/spec/ops.md",
  "| `toggleAwait`（外す） | `boundary.await[]` における要素の位置 | `index` |\n",
  "",
  ["tests/spec/test_spec_consistency.py", "-k", "restore_conditions"]),

 ("S-3", "docs/spec/model.md",
  "**段 2 で JIN002 として落とす**",
  "無視する",
  ["tests/spec/test_spec_consistency.py", "-k", "loop_only_keys"]),

 ("S-4", "docs/spec/model.md",
  "- **1 つの pointer は 1 つの値だけを指す**。RFC 8259 は同一オブジェクト内の重複キーの扱いを未定義に\n  しているが、Jin は**重複キーを段 1 の構文エラー（JIN001）として落とす**。後勝ちにすると\n  同じ pointer に 2 つの range が対応し、この項が成り立たなくなる\n",
  "",
  ["tests/spec/test_spec_consistency.py", "-k", "pointer_denotes"]),

 ("W-08", "tests/conftest.py",
  'return sorted(root.rglob("*.jin"))',
  'return sorted(root.glob("*/*.jin"))',
  ["tests/contract/test_packaging_contract.py", "-k", "discover"]),

 ("S3-budget", "packages/jin-core/src/jin_core/semantic.py",
  "    budget = DistanceBudget()",
  "    budget = DistanceBudget(total=10**9)",
  ["packages/jin-core/tests/test_semantic.py", "-k", "large_document_stays_fast"]),

 ("CONV-C1", "delivery/20260904-1445-jin/version-matrix.md",
  "`packages/jin-core/src/jin_core/parser.py` のインライン定数 `JIN_JSON_GRAMMAR` として自作した",
  "`jin_core/grammar/jin_json.lark` を自作した",
  ["tests/spec/test_spec_consistency.py", "-k", "version_matrix"]),

 ("S14", "delivery/20260904-1445-jin/decision-conformance.md",
  "現在は import 実装を `jin_cli.resolver.ImportResolver` へ移し",
  "現在は import 実装を（記述削除）へ移し",
  ["tests/spec/test_spec_consistency.py", "-k", "decision_conformance"]),
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

width = max(len(r[0]) for r in results)
for name, verdict, tail in results:
    print(f"{name:<{width}}  {verdict:<18} {tail}")
