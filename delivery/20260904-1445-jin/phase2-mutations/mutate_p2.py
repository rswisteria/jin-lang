"""Phase 2（jin-adk）の主要な防御を 1 つずつ壊し、対応テストが赤くなることを実測する。

**隔離コピー上で変異する**（修正ラウンド 1・wiring review F-W-P2-002）: `packages/` `tests/` `examples/`
`pyproject.toml` を一時ディレクトリへ複製し、`PYTHONPATH` にコピー側の `src` を並べて pytest を走らせる。
実ツリーは 1 バイトも書き換えない（起動時に `jin_adk.__file__` がコピー側を指すことを印字して確かめる）。

判定（security review F-S-P2-011）: 「赤」は **`returncode == 1` かつ summary に `failed`** があるとき。
`-k` が 0 件を選ぶ exit 5 / ファイル欠落 exit 4 / collection error は赤に数えない。
`SKIP (pattern not found)` も caught に数えず、1 件でもあれば exit 1。

実行: `uv run python delivery/20260904-1445-jin/phase2-mutations/mutate_p2.py`
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
COPY_ITEMS = ["packages", "tests", "examples", "pyproject.toml"]

CODEGEN = "packages/jin-adk/src/jin_adk/codegen.py"
TEMPLATE = "packages/jin-adk/src/jin_adk/templates/agent.py.j2"
BUILD = "packages/jin-adk/src/jin_adk/build.py"
RUNTIME = "packages/jin-adk/src/jin_adk/runtime.py"
TRACE = "packages/jin-adk/src/jin_adk/trace.py"
CLI = "packages/jin-cli/src/jin_cli/main.py"
T_CODEGEN = "packages/jin-adk/tests/test_codegen.py"
T_BUILD = "packages/jin-adk/tests/test_build.py"
T_RUNTIME = "packages/jin-adk/tests/test_runtime.py"
T_TRACE = "packages/jin-adk/tests/test_trace.py"
T_CLI = "packages/jin-cli/tests/test_build_run.py"
T_GUARD = "tests/contract/test_guard_claims.py"
T_CLI_CONTRACT = "tests/contract/test_cli_contract.py"

#: (名前, 対象ファイル, before, after, pytest 引数)
MUTATIONS: list[tuple[str, str, str, str, list[str]]] = [
    # --- security (1): エスケープ ------------------------------------------------------
    (
        "ESC-no-escape",
        CODEGEN,
        "    return json.dumps(text, ensure_ascii=False).translate(_EXTRA_ESCAPES)\n",
        "    return '\"' + text + '\"'\n",
        [T_CODEGEN, "-k", "py_literal_roundtrips or cannot_inject"],
    ),
    (
        "ESC-repr",
        CODEGEN,
        "    return json.dumps(text, ensure_ascii=False).translate(_EXTRA_ESCAPES)\n",
        "    return repr(text)\n",
        [T_CODEGEN, "-k", "py_literal_roundtrips"],
    ),
    # R1 F-S-P2-005: 孤立サロゲートを素通しすると生成物が UTF-8 で書けない
    (
        "ESC-surrogate-passthrough",
        CODEGEN,
        '_EXTRA_ESCAPES.update({code: f"\\\\u{code:04x}" for code in range(0xD800, 0xE000)})\n',
        "",
        [T_CODEGEN, "-k", "py_literal_roundtrips or source_name_cannot_inject"],
    ),
    # R1 F-S-P2-001: ファイル名をヘッダに生で置く
    (
        "ESC-header-raw-source-name",
        CODEGEN,
        '    source = f"# source: {py_literal(source_name)}\\n" if source_name else ""\n',
        '    source = f"# source: {source_name}\\n" if source_name else ""\n',
        [T_CODEGEN, "-k", "source_name_cannot_inject or cannot_inject_statements"],
    ),
    # --- NFR-FAIL-001 --------------------------------------------------------------------
    (
        "FAIL-skip-validate",
        CODEGEN,
        "    _validate(model)\n    by_name = {c.name: c for c in model.circles}\n",
        "    by_name = {c.name: c for c in model.circles}\n",
        [T_CODEGEN, "-k", "build_error_fixture or keyword_circle_name or reserved_generated_name"],
    ),
    (
        "FAIL-no-keyword-check",
        CODEGEN,
        '    if keyword.iskeyword(name) or name in ("True", "False", "None"):\n',
        "    if False:\n",
        [T_CODEGEN, "-k", "keyword"],
    ),
    (
        "FAIL-two-outs",
        CODEGEN,
        "        if circle.core is not None and len(outs) > 1:\n",
        "        if False:\n",
        [T_CODEGEN, "-k", "two_out_states"],
    ),
    (
        "FAIL-rune-conflict",
        CODEGEN,
        '        if name.startswith("artifact.") or _adk_is_valid_state_name(name):\n',
        "        if False:\n",
        [T_CODEGEN, "-k", "adk_template_conflicts or rune_adk"],
    ),
    (
        "FAIL-ref-format",
        CODEGEN,
        "        reason = check_ref_format(ref)\n        if reason is not None:\n",
        "        reason = None\n        if reason is not None:\n",
        [T_CODEGEN, "-k", "malformed_ref or ref_malformed"],
    ),
    # R1 F-S-P2-002: NFKC
    (
        "FAIL-no-nfkc",
        CODEGEN,
        "    if normalized != name:\n",
        "    if False:\n",
        [T_CODEGEN, "-k", "nfkc"],
    ),
    # R1 F-C-P2-001: builtin 名を taken に入れない → ref が builtin を上書き
    (
        "FAIL-builtin-not-taken",
        CODEGEN,
        "    taken = set(var_of.values()) | set(RESERVED_NAMES) | _builtin_names(model)\n",
        "    taken = set(var_of.values()) | set(RESERVED_NAMES)\n",
        [T_CODEGEN, "-k", "aliased_not_shadowed"],
    ),
    # R1 F-C-P2-003: circle 名 vs builtin 名
    (
        "FAIL-builtin-circle-collision",
        CODEGEN,
        "        if circle.name in builtins:\n",
        "        if False:\n",
        [T_CODEGEN, "-k", "builtin_name_collision or named_like_a_builtin"],
    ),
    # R1 F-C-P2-002: ADK ツール名の重複
    (
        "FAIL-adk-tool-dup",
        CODEGEN,
        "        if adk_name in seen:\n",
        "        if False:\n",
        [
            T_CODEGEN,
            "-k",
            "same_callable_name_in_one_circle or adk_tool_name_duplicate or same_adk_name",
        ],
    ),
    # R1 F-C-P2-016: root に親
    (
        "FAIL-root-parent",
        CODEGEN,
        "        _check_root_is_not_a_child(model, circle, base)\n",
        "        pass\n",
        [T_CODEGEN, "-k", "root_with_a_parent or root_has_parent"],
    ),
    # R1 F-C-P2-010: 同種 guard の 2 つ目を捨てる
    (
        "GEN-guards-first-only",
        CODEGEN,
        '        value = names[0] if len(names) == 1 else "[" + ", ".join(names) + "]"\n',
        "        value = names[0]\n",
        [T_RUNTIME, "-k", "two_guards_of_the_same_kind"],
    ),
    # R1 F-C-P2-015: delegate の順序
    (
        "GEN-delegate-reversed",
        CODEGEN,
        "        lines.append(f\"    sub_agents=[{', '.join(var_of[name] for name in circle.delegate)}],\")\n",
        "        lines.append(f\"    sub_agents=[{', '.join(var_of[name] for name in reversed(circle.delegate))}],\")\n",
        [T_RUNTIME, "-k", "description_and_delegate_order"],
    ),
    # --- ADR-008 / 生成物の形 -------------------------------------------------------------
    (
        "ADR8-header",
        CODEGEN,
        'jin を更新したら `jin build` で再生成すること（ADR-008）。\\n"\n',
        'jin を更新しても何もしなくてよい。\\n"\n',
        [T_CODEGEN, "-k", "header_states"],
    ),
    (
        "ADR9-header",
        CODEGEN,
        '単体実行してもトレースに Jin の pointer は付かない（ADR-009）。\\n"\n',
        '単体実行しても大丈夫。\\n"\n',
        [T_CODEGEN, "-k", "header_states"],
    ),
    # --- テンプレート（flow.exit の比較） ----------------------------------------------------
    (
        "TMPL-equals-not-stripped",
        TEMPLATE,
        "            return text == expected.strip()\n",
        "            return text == expected\n",
        [T_RUNTIME, "-k", "state_matches_semantics"],
    ),
    (
        "TMPL-bool-as-number",
        TEMPLATE,
        "        return isinstance(value, (int, float)) and not isinstance(value, bool) and value == expected\n",
        "        return isinstance(value, (int, float)) and value == expected\n",
        [T_RUNTIME, "-k", "state_matches_semantics"],
    ),
    # --- build の書き込み安全 -----------------------------------------------------------
    (
        "BUILD-overwrite-file",
        BUILD,
        "    create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW\n",
        "    create = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW\n",
        [T_BUILD, "-k", "only_env_example_exists"],
    ),
    # R2 F-S-P2-104: 差し替えを「全部書けたあと」から「ファイルごとに書けた直後」に前倒しすると、
    # 2 つ目の os.write が ENOSPC のとき 1 つ目の既存ファイルが変わってしまう
    (
        "BUILD-replace-early",
        BUILD,
        "                    os.close(fd)\n                    open_fds.remove(fd)\n",
        "                    os.close(fd)\n                    open_fds.remove(fd)\n"
        "                    _move_into_place(dir_fd, opened_name, name)\n",
        [T_BUILD, "-k", "force_write_failure_keeps"],
    ),
    # R3 F-S-P2-301: tmp の fchmod 失敗時の片付け（close + unlink）を消す → 残骸が残る
    (
        "BUILD-fchmod-leftover",
        BUILD,
        "        os.close(fd)\n        with contextlib.suppress(OSError):\n            os.unlink(tmp, dir_fd=dir_fd)\n",
        "        pass\n",
        [T_BUILD, "-k", "fchmod_failure_on_the_temporary_file"],
    ),
    # R2 F-S-P2-104: 既存ファイルを直接開いて ftruncate する旧方式に戻す（一時ファイルを使わない）
    (
        "BUILD-truncate-in-place",
        BUILD,
        '    tmp = f".{name}{TMP_SUFFIX}"\n    try:\n        fd = os.open(tmp, create, 0o644, dir_fd=dir_fd)\n',
        "    tmp = name\n    try:\n        fd = os.open(tmp, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=dir_fd)\n"
        "        os.ftruncate(fd, 0)\n",
        [T_BUILD, "-k", "force_write_failure_keeps"],
    ),
    # 二層防御: ディレクトリ単位の事前判定だけを消しても、ファイル単位の O_EXCL が拒む（緑のまま）。
    (
        "BUILD-overwrite-dir-only",
        BUILD,
        '        if not force:\n            raise WriteRefused(\n                f"{root_name}/ が既にあります。',
        '        if False:\n            raise WriteRefused(\n                f"{root_name}/ が既にあります。',
        [T_BUILD, "-k", "refuses_to_overwrite or partial_failure"],
    ),
    (
        "BUILD-overwrite-both",
        BUILD,
        '        if not force:\n            raise WriteRefused(\n                f"{root_name}/ が既にあります。',
        '        if False:\n            raise WriteRefused(\n                f"{root_name}/ が既にあります。',
        [T_BUILD, "-k", "refuses_to_overwrite or partial_failure"],
    ),
    (
        "BUILD-leftover-dir",
        BUILD,
        "                if created:\n                    os.close(pkg_fd)\n",
        "                if False:\n                    os.close(pkg_fd)\n",
        [T_BUILD, "-k", "leaves_nothing_behind"],
    ),
    # R2: --force で既存がリンクでも拒まない（os.replace がリンク自体を置き換えてしまう）
    (
        "BUILD-follow-symlink",
        BUILD,
        '    if stat.S_ISLNK(info.st_mode):\n        raise WriteRefused(f"{shown} がシンボリックリンクなので',
        '    if False:\n        raise WriteRefused(f"{shown} がシンボリックリンクなので',
        [T_BUILD, "-k", "symlinked_file"],
    ),
    (
        "BUILD-no-root-check",
        BUILD,
        "    _check_root_name(project.root_name)\n    out = Path(out)\n",
        "    out = Path(out)\n",
        [T_BUILD, "-k", "root_name_is_validated"],
    ),
    # R1 F-S-P2-002（build 側）: root_name の NFKC
    (
        "BUILD-root-not-nfkc",
        BUILD,
        '        or unicodedata.normalize("NFKC", root_name) != root_name\n',
        "",
        [T_BUILD, "-k", "root_name_is_validated"],
    ),
    # 二層防御: 事前判定（S_ISLNK / S_ISDIR）だけを消しても O_NOFOLLOW が ELOOP で拒む（緑のまま）。
    (
        "BUILD-pkg-symlink-upfront-only",
        BUILD,
        "        if stat.S_ISLNK(info.st_mode):\n",
        "        if False:\n",
        [T_BUILD, "-k", "package_directory_is_a_symlink"],
    ),
    (
        "BUILD-pkg-symlink-both",
        BUILD,
        "        if not stat.S_ISDIR(info.st_mode):\n",
        "        if False:\n",
        [T_BUILD, "-k", "package_directory_is_a_symlink"],
    ),
    # R1 F-S-P2-005: encode を書き込み時に回す（open 後に落ちる）
    (
        "BUILD-encode-late",
        BUILD,
        '            encoded.append(text.encode("utf-8"))\n',
        '            encoded.append(text.encode("utf-8", "surrogatepass"))\n',
        [T_BUILD, "-k", "unencodable_content"],
    ),
    # R1 F-C-P2-020: WriteRefused 以外では片付けない
    (
        "BUILD-cleanup-only-on-refusal",
        BUILD,
        "            except BaseException:\n",
        "            except WriteRefused:\n",
        [T_BUILD, "-k", "write_failure_after_open"],
    ),
    # R1 F-S-P2-004: OSError を包まない
    (
        "BUILD-oserror-traceback",
        BUILD,
        '        raise WriteRefused(f"{out} を出力先ディレクトリにできません: {exc.strerror}") from exc\n',
        "        raise\n",
        [T_BUILD, "-k", "regular_file_is_refused"],
    ),
    # R1 F-S-P2-007: <out> 自体のリンクを辿る
    (
        "BUILD-follow-out-symlink",
        BUILD,
        "        return os.open(out, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)\n",
        "        return os.open(out, os.O_RDONLY | os.O_DIRECTORY)\n",
        [T_BUILD, "-k", "out_itself_is_not_followed"],
    ),
    (
        "BUILD-guard-lie",
        BUILD,
        "    guard: _open_for_write -> os.O_EXCL\n",
        "    guard: _open_for_write -> os.O_APPEND\n",
        [T_GUARD, "-k", "guard_claims_point_at_real_guards"],
    ),
    # --- runtime ---------------------------------------------------------------------------
    (
        "RUN-swallow-systemexit",
        RUNTIME,
        "    except BaseException as exc:\n        sys.modules.pop(name, None)\n",
        "    except Exception as exc:\n        sys.modules.pop(name, None)\n",
        [T_RUNTIME, "-k", "system_exit_in_generated_code_import"],
    ),
    # R2 F-S-P2-102（R1 の回帰）: 実行中の sys.exit(0) は asyncio がループの外へ再送出する。
    # 同期 run_model の包みを消す（raise で素通し）
    (
        "RUN-swallow-systemexit-in-run_model",
        RUNTIME,
        "    except SystemExit as exc:\n        raise RunError(\n",
        "    except SystemExit as exc:\n        raise\n        raise RunError(\n",
        [T_RUNTIME, "-k", "system_exit_in_a_tool_at_runtime"],
    ),
    # R2 F-S-P2-102: CancelledError を RunError にすると shutdown 中の未処理例外としてトレースバックが漏れる
    (
        "RUN-cancelled-to-runerror",
        RUNTIME,
        "            if task is not None and task.cancelling():\n",
        "            if False:\n",
        [T_RUNTIME, "-k", "system_exit_in_a_tool_at_runtime or cancelled_error_propagates"],
    ),
    # R3 F-S-P2-201: 応答の無い function_call の検知を消す → LlmAgent root のツール cancel が exit 0 に戻る
    (
        "RUN-ignore-unanswered-tool",
        RUNTIME,
        "    return [name for call_id, name in pending.items() if call_id not in long_running]\n",
        "    return []\n",
        [T_RUNTIME, T_CLI, "-k", "tool_cancelled_error"],
    ),
    # R3 F-S-P2-201: await の pause を除外しないと researcher の publish（long-running）が失敗になる
    (
        "RUN-await-pause-as-failure",
        RUNTIME,
        "    return [name for call_id, name in pending.items() if call_id not in long_running]\n",
        "    return [name for call_id, name in pending.items()]\n",
        [T_RUNTIME, T_CLI, "-k", "await_pause"],
    ),
    # R3 F-S-P2-202: ツール由来の CancelledError を RunError にせず素通り（sequence root でトレースバック）
    (
        "RUN-cancelled-passthrough",
        RUNTIME,
        "            if task is not None and task.cancelling():\n                # shutdown",
        "            if True:\n                # shutdown",
        [T_RUNTIME, "-k", "workflow_root_is_a_run_error_from_run_model_async"],
    ),
    # R2 DP-IMPL-JIN-P2-SYSPATH-01（再々判断）: import 窓の finally を消すと Runner 実行中も cwd が残る。
    # 未インストール名（anthropic）の契約テストが別プロセスで赤・同一プロセスの 2 件も赤
    (
        "RUN-cwd-stays-after-import",
        RUNTIME,
        "            with contextlib.suppress(ValueError):\n                sys.path.remove(entry)\n",
        "            pass\n",
        [
            T_CLI,
            T_RUNTIME,
            T_CLI_CONTRACT,
            "-k",
            "only_while_importing or present_only_during_the_import or uninstalled_optional_dependency",
        ],
    ),
    # R1 F-S-P2-003: 先頭に足すと窓の中で site-packages の名前を cwd で差し替えられる
    (
        "RUN-cwd-first",
        RUNTIME,
        "        sys.path.append(entry)\n",
        "        sys.path.insert(0, entry)\n",
        [T_CLI, T_RUNTIME, "-k", "only_while_importing or present_only_during_the_import"],
    ),
    (
        "RUN-no-agenttool-swap",
        RUNTIME,
        "            if isinstance(tool, AgentTool):\n                yield from _walk(tool.agent, seen)\n",
        "            pass\n",
        [T_RUNTIME, "-k", "agent_tool_targets"],
    ),
    (
        "RUN-no-seed",
        RUNTIME,
        "    return {state.name: None for circle in model.circles for state in circle.state}\n",
        "    return {}\n",
        [T_RUNTIME, "-k", "seeded or fake_llm_completes"],
    ),
    (
        "RUN-no-cleanup",
        RUNTIME,
        "        shutil.rmtree(directory, onexc=_report_cleanup_failure)\n",
        "        pass\n",
        [T_RUNTIME, "-k", "cleans_up or created_with_mkdtemp"],
    ),
    # R1 F-S-P2-011: mkdtemp を「素の mkdir」に変える本来の形（0700 の検査で落ちる）
    (
        "RUN-plain-mkdir",
        RUNTIME,
        '    directory = tempfile.mkdtemp(prefix="jin-run-")\n',
        '    directory = tempfile.mktemp(prefix="jin-run-")\n    Path(directory).mkdir()\n',
        [T_RUNTIME, "-k", "cleans_up or created_with_mkdtemp"],
    ),
    # R1 F-W-P2-008: 片付けの失敗を黙る
    (
        "RUN-cleanup-silent",
        RUNTIME,
        "        shutil.rmtree(directory, onexc=_report_cleanup_failure)\n",
        "        shutil.rmtree(directory, ignore_errors=True)\n",
        [T_RUNTIME, "-k", "cleanup_failure_is_reported"],
    ),
    # --- trace（ADR-009: 引けなければ null、黙って落とさない） ---------------------------
    (
        "TRACE-drop-unknown",
        TRACE,
        "        pointer, model_name = table.core_pointer(author)\n",
        "        pointer, model_name = table.core_pointer(author)\n        if pointer is None:\n            return []\n",
        [T_TRACE, "-k", "unknown_author"],
    ),
    (
        "TRACE-dup-first-wins",
        TRACE,
        "            elif key in self.tool_pointer:\n                self.tool_pointer[key] = None\n",
        "            elif key in self.tool_pointer:\n                pass\n",
        [T_TRACE, T_RUNTIME, "-k", "duplicate_tool_names or runtime_tool_name_collision"],
    ),
    (
        "TRACE-no-final",
        TRACE,
        '            if last.kind == "model":\n                last = last.with_kind("final")\n',
        "            pass\n",
        [T_TRACE, T_RUNTIME, "-k", "relabels or has_final"],
    ),
    (
        "TRACE-escalate-pointer",
        TRACE,
        "        return entry.exit, loop\n",
        "        return None, loop\n",
        [T_RUNTIME, "-k", "fake_llm_completes_and_every_pointer"],
    ),
    # R1 F-C-P2-004: transfer の function_call を tool 行にする
    # R2 F-C-P2-101: transfer の event で同居する他ツールの応答を捨てる（早期 return と同じ状態）
    (
        "TRACE-transfer-drops-siblings",
        TRACE,
        '    for response in responses:\n        name = response.name or ""\n        if name == TRANSFER_TOOL_NAME:\n',
        '    for response in responses if not transfer_target else []:\n        name = response.name or ""\n        if name == TRANSFER_TOOL_NAME:\n',
        [T_TRACE, "-k", "transfer_keeps_the_sibling"],
    ),
    (
        "TRACE-transfer-call-as-tool",
        TRACE,
        "        if name == TRANSFER_TOOL_NAME:\n            continue\n",
        "        pass\n",
        [
            T_TRACE,
            T_RUNTIME,
            "-k",
            "transfer_function_call_is_not_a_tool_row or delegate_transfer_end_to_end",
        ],
    ),
    # R1 F-C-P2-007 / F-C-P2-021: text / error を捨てる
    (
        "TRACE-drop-text-with-call",
        TRACE,
        "    if text or error or not (calls or responses or transfer_target):\n",
        "    if not (calls or responses or transfer_target):\n",
        [T_TRACE, "-k", "text_and_function_call or model_error_event"],
    ),
    (
        "TRACE-error-hidden",
        TRACE,
        "        if event.error_code or event.error_message\n",
        "        if False\n",
        [T_TRACE, "-k", "model_error_event"],
    ),
    # R1 F-C-P2-005: escalate が tool 行を消す（修正前の形）
    (
        "TRACE-escalate-swallows-tool",
        TRACE,
        "    if actions.escalate:\n        # F-C-P2-005",
        "    if actions.escalate:\n        rows = []\n        # F-C-P2-005",
        [T_TRACE, "-k", "non_checker_escalate"],
    ),
    # R1 F-C-P2-014: ts を Event.timestamp から取らない
    (
        "TRACE-ts-zero",
        TRACE,
        "    ts = float(event.timestamp)\n",
        "    ts = 0.0\n",
        [T_TRACE, "-k", "ts_is_taken"],
    ),
    # R1 F-C-P2-011: 添字対応を壊す
    (
        "TRACE-bind-first-index",
        TRACE,
        "                self.tool_pointer[key] = entry.tools[j]\n",
        "                self.tool_pointer[key] = entry.tools[0]\n",
        [T_RUNTIME, "-k", "declared_index_not_the_first"],
    ),
    # --- CLI -------------------------------------------------------------------------------
    # R2: CLI が cwd を runtime の import 窓へ渡さない（research.* が cwd から解決できない）
    (
        "CLI-no-cwd",
        CLI,
        "                extra_sys_path=[os.getcwd()],\n",
        "                extra_sys_path=[],\n",
        [T_CLI, "-k", "only_while_importing"],
    ),
    # R2 F-S-P2-102: CLI の except SystemExit を素通し（raise）にすると exit 0 に戻る
    # R3 F-S-P2-202: CLI の保険 except CancelledError を素通しにする
    (
        "CLI-cancelled-traceback",
        CLI,
        "    except asyncio.CancelledError as exc:\n        # 保険（F-S-P2-202）",
        "    except asyncio.CancelledError as exc:\n        raise\n        # 保険（F-S-P2-202）",
        [T_CLI, "-k", "stray_cancelled_error"],
    ),
    (
        "RUN-swallow-systemexit-at-runtime",
        CLI,
        "    except SystemExit as exc:\n        # ツール関数の sys.exit() は",
        "    except SystemExit as exc:\n        raise\n        # ツール関数の sys.exit() は",
        [T_CLI, "-k", "tool_sys_exit_at_runtime"],
    ),
    (
        "CLI-trace-follow-symlink",
        CLI,
        "    fd = os.open(trace, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)\n",
        "    fd = os.open(trace, os.O_WRONLY | os.O_CREAT, 0o600)\n",
        [T_CLI, "-k", "symlinked_trace"],
    ),
    (
        "CLI-accept-any-model",
        CLI,
        '    if model not in (None, "fake"):\n',
        "    if False:\n",
        [T_CLI, "-k", "rejects_other_model"],
    ),
    # R1 F-S-P2-001 / 016 / 005: ファイル名の入口検査
    (
        "CLI-filename-unchecked",
        CLI,
        "    if _has_unsafe_chars(file.name):\n",
        "    if False:\n",
        [T_CLI, "-k", "unsafe_file_names"],
    ),
    # R1 F-S-P2-005 / 014: _safe がサロゲートと U+2028 を素通す
    (
        "CLI-safe-narrow",
        CLI,
        "_UNSAFE_CODES = [*range(0x20), 0x7F, *range(0x80, 0xA0), 0x2028, 0x2029, *range(0xD800, 0xE000)]\n",
        "_UNSAFE_CODES = [*range(0x20), 0x7F, *range(0x80, 0xA0)]\n",
        [T_CLI, "-k", "unsafe_file_names"],
    ),
    # R1 F-S-P2-006: 開いた時点で切り詰める（修正前の O_TRUNC と同じ効果）
    (
        "CLI-trace-truncate-on-open",
        CLI,
        "        self._truncated = False\n",
        "        os.ftruncate(fd, 0)\n        self._truncated = True\n",
        [T_CLI, "-k", "failed_run_does_not_empty"],
    ),
    # R1 F-S-P2-008: 0644
    # R2 F-C-P2-103: fchmod が新規・既存の両方を 0600 にする。mode を緩めると両方赤
    (
        "CLI-trace-world-readable",
        CLI,
        "    os.fchmod(fd, 0o600)\n",
        "    os.fchmod(fd, 0o644)\n",
        [T_CLI, "-k", "owner_only"],
    ),
    # R2 F-C-P2-103: fchmod を消すと新規は O_CREAT の mode で 0600 のまま・既存 0644 は残る
    (
        "CLI-trace-keep-existing-mode",
        CLI,
        "    os.fchmod(fd, 0o600)\n",
        "",
        [T_CLI, "-k", "existing_trace_file_is_made_owner_only"],
    ),
]

#: 二層防御のため「片方だけ消しても緑」が正しいもの。
EXPECT_GREEN = {"BUILD-pkg-symlink-upfront-only", "BUILD-overwrite-dir-only"}


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
    # R2 F-W-P2-101: 変異した runtime が消し損ねる /tmp/jin-run-* をコピー内へ向ける（コピーごと消える）
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
    )


def _summary(result: subprocess.CompletedProcess[str]) -> str:
    lines = [
        l for l in result.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l
    ]
    return (
        lines[-1]
        if lines
        else result.stderr.strip().splitlines()[-1:]
        and result.stderr.strip().splitlines()[-1]
        or "(no summary)"
    )


def _is_red(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 1 and "failed" in _summary(result)


def _is_green(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0 and "passed" in _summary(result)


def main() -> int:
    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-"))
    try:
        _copy_tree(copy)
        where = (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import jin_adk, jin_cli; print(jin_adk.__file__); print(jin_cli.__file__)",
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
        if not all(line.startswith(str(copy)) for line in where):
            print("!! jin_adk / jin_cli が隔離コピーを指していない。中止")
            return 2
        baseline = _run_pytest(copy, ["packages/jin-adk/tests", T_CLI, T_GUARD])
        if not _is_green(baseline):
            print("BASELINE NOT GREEN")
            print(baseline.stdout[-2000:])
            return 2
        print(f"baseline: green ({_summary(baseline)})")
        caught = 0
        skipped = 0
        only = {n for n in os.environ.get("MUTATE_ONLY", "").split(",") if n}
        unknown = only - {m[0] for m in MUTATIONS}
        if unknown:
            # F-W-P2-203 / F-S-P2-205: typo が「全部 caught」に見えないよう、存在しない名前は失敗にする
            print(f"!! MUTATE_ONLY に存在しない変異名: {sorted(unknown)}")
            return 1
        mutations = [m for m in MUTATIONS if not only or m[0] in only]
        for name, rel, before, after, target in mutations:
            path = copy / rel
            original = path.read_text(encoding="utf-8")
            if before not in original:
                print(f"{name:32s} SKIP (pattern not found)")
                skipped += 1
                continue
            mutated = original.replace(before, after, 1)
            if name == "BUILD-overwrite-both":
                mutated = mutated.replace(
                    "    create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW\n",
                    "    create = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW\n",
                    1,
                )
            if name == "BUILD-pkg-symlink-both":
                mutated = mutated.replace(
                    "        if stat.S_ISLNK(info.st_mode):\n", "        if False:\n", 1
                )
                mutated = mutated.replace(
                    "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=out_fd",
                    "os.O_RDONLY | os.O_DIRECTORY, dir_fd=out_fd",
                    1,
                )
            path.write_text(mutated, encoding="utf-8")
            try:
                result = _run_pytest(copy, target)
            finally:
                path.write_text(original, encoding="utf-8")
            if name in EXPECT_GREEN:
                ok = _is_green(result)
                status = "GREEN (expected: 二層目が守る)" if ok else "RED (!! 二層目が効いていない)"
            else:
                ok = _is_red(result)
                status = (
                    "RED (expected)"
                    if ok
                    else (
                        "GREEN (!! not caught)"
                        if result.returncode == 0
                        else f"NOT RED (!! exit {result.returncode})"
                    )
                )
            caught += ok
            print(f"{name:32s} {status:34s} {_summary(result)}")
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
