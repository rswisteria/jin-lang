"""修正ラウンド 3 の各修正を 1 つずつ元に戻し、対応テストが赤くなることを実測する。

mutate.py / mutate2.py / mutate3.py と同じ形式。対象ファイルは必ず元へ戻す。
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
        cwd=root, capture_output=True, text=True, env=env)
CLI = "packages/jin-cli/src/jin_cli/main.py"
TEST = "packages/jin-cli/tests/test_cli.py"

MUTATIONS = [
 # R-1: 最下層のカーネルガードを消す。ここが本丸。
 ("R-1-nofollow", CLI,
  "os.O_WRONLY | os.O_TRUNC | os.O_CREAT | os.O_NOFOLLOW, 0o666",
  "os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o666",
  [TEST, "-k", "write_in_place_refuses or fallback_path"]),

 # R-1: `getattr(os, "O_NOFOLLOW", 0)` 型の握り潰し（0 に落ちると防御が黙って消える）。
 ("R-1-getattr", CLI,
  "os.O_WRONLY | os.O_TRUNC | os.O_CREAT | os.O_NOFOLLOW, 0o666",
  'os.O_WRONLY | os.O_TRUNC | os.O_CREAT | getattr(os, "O_NOFOLLOW_X", 0), 0o666',
  [TEST, "-k", "write_in_place_refuses or fallback_path"]),

 # R-1: ELOOP を握り潰して素通りさせる。
 ("R-1-swallow", CLI,
  "        if exc.errno == errno.ELOOP:\n",
  "        if False:\n",
  [TEST, "-k", "write_in_place_refuses or fallback_path"]),

 # R-1: 原子的経路の lstat ガード（S12 の方針・境界越えではない残余）。
 ("R-1-atomic", CLI,
  "        if Path(path).is_symlink():\n"
  '            raise SymlinkWriteRefused(f"シンボリックリンクなので書き込みを拒みました: {path}")\n',
  "",
  [TEST, "-k", "write_atomically_refuses"]),

 # R-1: fmt 側の事前ガードだけを残して下位を消すのは上で見た。逆に事前ガードを消しても
 #      守られること（二重化）は、事前ガードを消す変異で S12 のテストだけが落ちて
 #      R-1 のテストは緑のままであることで示す。
 ("R-1-upfront", CLI,
  "        if path.is_symlink():\n",
  "        if False:\n",
  [TEST, "-k", "does_not_follow_symlinks"]),

 # R-2: docstring が「_collect が弾く」と嘘をついていた件を、テストで固定してある。
 ("R-2-collect", CLI,
  "        if path.is_dir():\n            found.extend(sorted(path.rglob(\"*.jin\")))\n",
  "        if path.is_dir():\n            found.extend(\n"
  "                sorted(p for p in path.rglob(\"*.jin\") if not p.is_symlink())\n            )\n",
  [TEST, "-k", "collect_does_not_filter_symlinks"]),

 # R-2: R-2 の欠陥そのもの（実装に無いガードを名指しする安全宣言）を書き戻す。
 ("R-2-lie", CLI,
  "    guard: _write_in_place -> os.O_NOFOLLOW\n    guard: _write_atomically -> os.replace\n",
  "    guard: _collect -> is_symlink\n",
  [TEST, "-k", "guard_claims"]),

 # R-2: 名指し先の関数が消えた / 改名されたことも捕まえる。
 ("R-2-ghost", CLI,
  "    guard: fmt -> path.is_symlink\n",
  "    guard: fmt_renamed -> path.is_symlink\n",
  [TEST, "-k", "guard_claims"]),

 # R-2: 主張の走査そのものが壊れて 0 件になる（検査が空虚になる）ことを捕まえる。
 ("R-2-scanner", TEST,
  'GUARD_CLAIM = re.compile(r"guard:\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*->\\s*(\\S+)")',
  'GUARD_CLAIM = re.compile(r"guard-none:\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*->\\s*(\\S+)")',
  [TEST, "-k", "guard_claims"]),

 # R-2: docstring を落とさない実装だと、主張の文言そのものを見て常に真になる。
 ("R-2-selfmatch", TEST,
  "                body = body[1:]\n",
  "                pass\n",
  [TEST, "-k", "looks_at_code_not_at_the_claim"]),

 # ---- 修正ラウンド 4 ----
 # T-1: mkstemp 側の except を PermissionError に戻す（欠陥の再現）。
 ("T-1-mkstemp", CLI,
  "    except OSError as exc:\n        raise _classify_write_failure(exc, path) from exc\n    try:",
  "    except PermissionError as exc:\n        raise AtomicWriteUnavailable(str(exc)) from exc\n    try:",
  [TEST, "-k", "mkstemp_fails or truncating_write"]),

 # T-1: replace 側の except を PermissionError に戻す。
 ("T-1-replace", CLI,
  "    except OSError as exc:\n        Path(temporary).unlink(missing_ok=True)\n"
  "        raise _classify_write_failure(exc, path) from exc",
  "    except PermissionError as exc:\n        Path(temporary).unlink(missing_ok=True)\n"
  "        raise AtomicWriteUnavailable(str(exc)) from exc",
  [TEST, "-k", "disappears_before_the_replace"]),

 # T-1: 容量不足でも退避可能として扱う（退避が被害を広げる形に戻す）。
 ("T-1-fallback", CLI,
  "    if isinstance(exc, PermissionError):\n",
  "    if True:\n",
  [TEST, "-k", "truncating_write"]),

 # T-1: 退避路の書き込み中の失敗を素通しに戻す。
 ("T-1-inplace", CLI,
  "    try:\n        with os.fdopen(descriptor, \"w\", encoding=\"utf-8\", newline=\"\") as handle:\n"
  "            handle.write(text)\n    except OSError as exc:",
  "    if True:\n        with os.fdopen(descriptor, \"w\", encoding=\"utf-8\", newline=\"\") as handle:\n"
  "            handle.write(text)\n    if False:",
  [TEST, "-k", "write_itself_fails"]),

 # T-1 / S2: BaseException を握り潰す（KeyboardInterrupt が伝播しなくなる）。
 ("T-1-swallow-bare", CLI,
  "        Path(temporary).unlink(missing_ok=True)\n        raise\n\n\ndef _write_canonical",
  "        Path(temporary).unlink(missing_ok=True)\n        return\n\n\ndef _write_canonical",
  [TEST, "-k", "keyboard_interrupt_still_propagates"]),

 # 点 3: Path.is_symlink を os.path.islink に書き換える（monkeypatch が効かなくなる）。
 ("P3-islink", CLI,
  "        if Path(path).is_symlink():\n",
  "        if os.path.islink(path):\n",
  [TEST, "-k", "guard_claims"]),

 # U-1 / E-B: 照合を素の部分文字列一致に戻す（欠陥の再現）。
 ("U-1-substring", TEST,
  "    wanted = ast.parse(token, mode=\"eval\").body\n",
  "    if token in code:\n        return True\n    wanted = ast.parse(token, mode=\"eval\").body\n",
  [TEST, "-k", "bare_name or absent_from_the_function"]),

 # U-1 / E-B: 裸の名前を拒む縛りを外す。
 ("U-1-barename", TEST,
  "    if isinstance(wanted, ast.Name):\n",
  "    if False:\n",
  [TEST, "-k", "bare_name"]),

 # U-1 / E-B: 「外側の属性参照の土台は数えない」縛りを外す。
 ("U-1-base", TEST,
  "    return any(ast.dump(node) == target and id(node) not in bases for node in ast.walk(body))",
  "    return any(ast.dump(node) == target for node in ast.walk(body))",
  [TEST, "-k", "partial_attribute_name"]),

 # ---- 修正ラウンド 5 ----
 # V-1: 文言を「書き込めません」だけに戻す（欠陥の再現）。
 ("V-1-message", CLI,
  '        raise ContentLostOnWrite(\n'
  '            f"原子的でない書き込みの途中で失敗したため、ファイルの内容が失われています。"\n'
  '            f"バックアップから復元してください（{_describe_write_failure(exc)}）"\n'
  '        ) from exc',
  '        raise WriteRefused(f"{_describe_write_failure(exc)}") from exc',
  [TEST, "-k", "content_was_lost"]),

 # V-1: 要約行の出し分けを戻す（書き込み失敗にも「診断を先に直してください」が付く）。
 ("V-1-summary", CLI,
  "                damaged.append(path)\n",
  "                failed.append(path)\n",
  [TEST, "-k", "content_was_lost"]),

 # V-1: 無傷の経路にも「失われた」と言ってしまう形（2 つの文言が混ざる）。
 ("V-1-intact", CLI,
  '                    f"{_safe(str(path))}: 書き込めません"\n'
  '                    f"（ファイルの内容は元のままです: {_safe(str(exc))}）",\n',
  '                    f"{_safe(str(path))}: 内容が失われました（{_safe(str(exc))}）",\n',
  [TEST, "-k", "content_is_intact"]),

 # V-1: メッセージにパスを戻して二重出力にする。
 ("V-1-doublepath", CLI,
  "    _ = path  # 文言にパスは入れない。表示側（fmt）が付けるので二重になる（V-1）。\n"
  "    detail = _describe_write_failure(exc)\n"
  "    if isinstance(exc, PermissionError):\n"
  "        return AtomicWriteUnavailable(detail)\n"
  "    return WriteRefused(detail)",
  "    detail = _describe_write_failure(exc)\n"
  "    if isinstance(exc, PermissionError):\n"
  '        return AtomicWriteUnavailable(f"{path}: {detail}")\n'
  '    return WriteRefused(f"{path}: {detail}")',
  [TEST, "-k", "content_is_intact"]),

 # V-1: 診断由来の失敗まで書き込み扱いにして要約行を消す（出し分けの反対側）。
 ("V-1-diagnostic", CLI,
  '        typer.echo(f"整形できませんでした（診断を先に直してください）: {len(failed)} 件", err=True)\n',
  "        pass\n",
  [TEST, "-k", "diagnostic_failure_still"]),
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
        verdict = "!!! 対象テストが無い !!!"
    else:
        verdict = "赤 (期待どおり)" if proc.returncode != 0 else "!!! 緑のまま !!!"
    results.append((name, verdict, tail[-1] if tail else ""))

width = max(len(r[0]) for r in results)
for name, verdict, tail in results:
    print(f"{name:<{width}}  {verdict:<20} {tail}")
