"""`apps/player`（Jin v2 Phase 4）の契約を Python 側から固定する。

TS 側の検査（`pnpm lint` / `pnpm build` / `pnpm test` / `pnpm e2e`）が本体である。
ここが見るのは **「その検査が所定の位置にあり、CI で走る」** ことと、Python 側との
突き合わせ（サンドボックスの手順・命令数の上限の Lua・`.jinrec` の reducer・同梱）である。

正典は `docs/spec/v2/runtime.md` §8 / §9 / §10 と設計書 §11 #32〜#34。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER = REPO_ROOT / "apps" / "player"
SRC = PLAYER / "src"
EDITOR = REPO_ROOT / "apps" / "editor"


def package_json(app: Path = PLAYER) -> dict:
    return json.loads((app / "package.json").read_text(encoding="utf-8"))


def sources() -> list[Path]:
    return sorted(SRC.rglob("*.ts"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 足場（apps/editor と同じ規律）


def test_the_player_exists_with_the_expected_scripts() -> None:
    scripts = package_json()["scripts"]
    for name in ("dev", "typecheck", "build", "lint", "test", "e2e"):
        assert name in scripts, f"pnpm {name} が無い"
    assert scripts["build"].startswith("tsc --noEmit"), "`pnpm build` が tsc を含まない"


def test_the_package_manager_is_pinned() -> None:
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+", package_json()["packageManager"])
    assert (PLAYER / "pnpm-lock.yaml").is_file(), "pnpm-lock.yaml がコミットされていない"


def test_every_dependency_is_pinned_to_an_exact_version() -> None:
    manifest = package_json()
    loose = [
        f"{name}: {spec}"
        for section in ("dependencies", "devDependencies")
        for name, spec in manifest.get(section, {}).items()
        if not re.fullmatch(r"\d+\.\d+\.\d+", spec)
    ]
    assert loose == []


def test_the_only_runtime_dependency_is_wasmoon_at_the_probed_version() -> None:
    """version-matrix.md: Wasmoon は `1.16.0`（probe §A の実測版）。"""
    assert package_json()["dependencies"] == {"wasmoon": "1.16.0"}


def test_the_toolchain_matches_the_editor() -> None:
    """2 つの TS アプリでツールチェーンの版を揃える（片方だけ黙って動かない）。"""
    mine = package_json()["devDependencies"]
    theirs = package_json(EDITOR)["devDependencies"]
    shared = set(mine) & set(theirs)
    assert {"vite", "vitest", "typescript", "eslint", "@playwright/test"} <= shared
    assert {k: mine[k] for k in shared} == {k: theirs[k] for k in shared}


def test_the_player_ignores_its_build_products() -> None:
    ignored = read(PLAYER / ".gitignore").split()
    assert {"node_modules/", "dist/", "test-results/", "playwright-report/"} <= set(ignored)
    root_ignored = read(REPO_ROOT / ".gitignore")
    assert "packages/jin-wasm/src/jin_wasm/player/" in root_ignored, "同梱先を gitignore する"


# ---------------------------------------------------------------- ホスト境界（runtime.md §8 / §10）


def test_the_player_calls_only_boot_and_tick() -> None:
    """ホストが呼ぶ Lua の関数は `boot` / `tick` の 2 つだけ（runtime.md §1）。"""
    from jin_wasm.jil import HOST_ENTRY_POINTS

    called = {
        m.group(1)
        for path in sources()
        for m in re.finditer(r'\.call\(\s*"([A-Za-z_]+)"', read(path))
    }
    assert called == set(HOST_ENTRY_POINTS), called


def test_the_player_does_not_use_the_wasmoon_c_hook() -> None:
    """`Thread.setTimeout` / `functionTimeout`（C の hook）はコルーチンの中で PANIC する（probe §A.10）。"""
    for path in sources():
        text = read(path)
        assert ".setTimeout(" not in text, f"{path}: Lua スレッドに setTimeout を掛けない"
        assert "functionTimeout" not in text, path


def test_the_player_removes_globals_with_undefined_not_null() -> None:
    """`global.set(name, null)` は Wasmoon 1.16.0 で TypeError になり消えない（probe §A.8）。"""
    host = read(SRC / "host.ts")
    assert re.search(r"\.set\([^)]*,\s*undefined\)", host)
    assert not re.search(r"\.set\([^)]*,\s*null\)", host)


def test_the_player_always_passes_the_wasm_uri_to_the_factory() -> None:
    """引数無しの `new LuaFactory()` は unpkg へ fetch しに行く（probe §A.10・NFR-TEST-001）。"""
    for path in sources():
        code_only = re.sub(r"//.*|/\*.*?\*/", "", read(path), flags=re.DOTALL)
        for m in re.finditer(r"new LuaFactory\(([^)]*)\)", code_only):
            assert m.group(1).strip() != "", f"{path}: new LuaFactory() に wasm の URL を渡す"
    code = "".join(re.sub(r"//.*|/\*.*?\*/", "", read(p), flags=re.DOTALL) for p in sources())
    assert "unpkg" not in code, "unpkg への経路をコードに置かない（コメントで触れるのはよい）"


def test_the_sandbox_matches_the_lupa_host() -> None:
    """消すグローバル・命令数の上限・hook を置く Lua は Python 側と同じ（パリティの根拠）。"""
    from jin_wasm.jil import HOST_HOOK_GLOBALS
    from jin_wasm.runtime import _SETUP, INSTRUCTION_BUDGET, SANDBOX_REMOVED

    host = read(SRC / "host.ts")
    removed = re.search(r"SANDBOX_REMOVED[^=]*=\s*\[(.*?)\];", host, re.DOTALL)
    assert removed is not None
    assert re.findall(r'"([a-z]+)"', removed.group(1)) == list(SANDBOX_REMOVED)
    hooks = re.search(r"HOST_HOOK_GLOBALS[^=]*=\s*\[(.*?)\];", host, re.DOTALL)
    assert hooks is not None
    assert re.findall(r'"([A-Z_]+)"', hooks.group(1)) == list(HOST_HOOK_GLOBALS)
    budget = re.search(r"INSTRUCTION_BUDGET = ([0-9_]+);", host)
    assert budget is not None and int(budget.group(1).replace("_", "")) == INSTRUCTION_BUDGET
    setup = re.search(r"HOOK_SETUP = `(.*?)`;", host, re.DOTALL)
    assert setup is not None
    assert setup.group(1).strip() == _SETUP.strip(), (
        "JIN_ARM / JIN_HOOK を置く Lua が Python 側とずれた"
    )


def test_the_player_reads_only_abilities_json_from_the_repository() -> None:
    """runtime.md §10: Python を import しない。読む生成物は `schemas/abilities.json` だけ。"""
    imports = {
        m.group(1)
        for path in sources()
        for m in re.finditer(r'from\s+"([^"]+)"', read(path))
        if m.group(1).startswith(".")
    }
    outside = {i for i in imports if i.startswith("../..")}
    assert outside == {"../../../schemas/abilities.json"}, outside
    assert "jin.schema.json" not in "".join(read(p) for p in sources())
    assert "jin-v2.schema.json" not in "".join(read(p) for p in sources())


def test_key_names_and_op_names_are_not_spelled_out_in_the_player() -> None:
    """キー名と op 名はカタログから引く（`abilities.ts` 以外にリテラルを置かない）。"""
    catalog = json.loads((REPO_ROOT / "schemas" / "abilities.json").read_text(encoding="utf-8"))
    keys = catalog["keys"]
    for path in sources():
        text = read(path)
        for key in keys:
            assert f'"{key}"' not in text, f"{path}: キー名 {key} のリテラル"
    for path in sources():
        if path.name in ("abilities.ts",):
            continue
        text = re.sub(r"//.*|/\*.*?\*/", "", read(path), flags=re.DOTALL)
        for m in re.finditer(r'\bop\("([a-z]+)"\)', text):
            assert m.group(1) in {
                member["name"] for ns in catalog["namespaces"] for member in ns["members"]
            }
        assert not re.search(
            r'case\s+"(clear|ink|rect|circle|line|text|sprite|button|label)"', text
        ), path


def test_the_reducer_fixture_is_shared_by_both_sides() -> None:
    """`InputReducer` と `InputState.apply` は同じ fixture で検算する（`input.ts` / `test_runtime.py`）。"""
    fixture = REPO_ROOT / "tests" / "fixtures" / "jinrec"
    assert (fixture / "reducer.jinrec").is_file() and (fixture / "reducer.expected.json").is_file()
    assert "reducer.jinrec" in read(PLAYER / "test" / "input.test.ts")
    assert "reducer.jinrec" in read(
        REPO_ROOT / "packages" / "jin-wasm" / "tests" / "test_runtime.py"
    )


# ---------------------------------------------------------------- 同梱（runtime.md §9）


def test_the_single_bundle_markers_match_the_player_page() -> None:
    """`--single` が置き換える目印は `apps/player/public/index.html` に実在する。"""
    from jin_wasm.bundle import BUNDLE_MARKER, PLAYER_SCRIPT_TAG

    html = read(PLAYER / "public" / "index.html")
    assert html.count(BUNDLE_MARKER) == 1
    assert html.count(PLAYER_SCRIPT_TAG) == 1
    assert html.index(BUNDLE_MARKER) < html.index(PLAYER_SCRIPT_TAG), "束を先に置く"
    assert "JIN_BUNDLE" in read(SRC / "main.ts")


def test_sync_player_lists_the_same_files_as_the_bundle() -> None:
    from jin_wasm.bundle import PLAYER_FILES

    script = read(REPO_ROOT / "scripts" / "sync_player.py")
    listed = re.search(r"PLAYER_FILES = \((.*?)\)", script)
    assert listed is not None
    assert tuple(re.findall(r'"([^"]+)"', listed.group(1))) == PLAYER_FILES
    harness = read(PLAYER / "e2e" / "harness.ts")
    found = re.search(r"PLAYER_FILES = \[(.*?)\]", harness, re.DOTALL)
    assert found is not None
    assert re.findall(r'"([a-z.]+)"', found.group(1)) == list(PLAYER_FILES)


@pytest.mark.skipif(
    os.environ.get("JIN_REQUIRE_PLAYER") != "1",
    reason="JIN_REQUIRE_PLAYER=1 のとき（CI の player ジョブ）だけ同梱を要求する",
)
def test_the_player_is_synced_when_required() -> None:
    """CI の player ジョブは `pnpm build` → `sync_player.py` の後にこれを走らせ、「無い側」の分岐を偶然通さない。"""
    import subprocess
    import sys

    from jin_wasm.bundle import PLAYER_DIR, PLAYER_FILES, player_available

    assert player_available(), f"{PLAYER_DIR} に {PLAYER_FILES} が無い"
    check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "sync_player.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr
    for name in PLAYER_FILES:
        assert (PLAYER_DIR / name).read_bytes() == (PLAYER / "dist" / name).read_bytes()


# ---------------------------------------------------------------- CI


def test_ci_runs_the_player_gates() -> None:
    ci = read(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    assert "\n  player:\n" in ci, "CI に player ジョブが無い"
    job = ci.split("\n  player:\n", 1)[1]
    for needle in (
        "pnpm install --frozen-lockfile",
        "pnpm lint",
        "pnpm build",
        "pnpm test",
        "pnpm e2e",
        "scripts/sync_player.py",
        "JIN_REQUIRE_PLAYER",
        "--single",
    ):
        assert needle in job, f"player ジョブに {needle} が無い"


def test_the_embedded_player_waits_for_the_parent_instead_of_fetching() -> None:
    """runtime.md §10（Phase 5）: iframe の中では `game.lua` を fetch せず、親の `jin.load` を待つ。"""
    main = read(SRC / "main.ts")
    assert "const EMBEDDED = window.parent !== window;" in main
    assert "if (EMBEDDED) return null;" in main
    # `jin.load` / `jin.trace` / `jin.control` の 3 語（Phase 5）で親と話す。Phase 6 で 7 語になり、
    # 集合の等号は `test_editor_contract.py::test_the_parent_and_the_player_speak_the_same_vocabulary` が見る。
    for word in ('"jin.load"', '"jin.trace"', '"jin.control"'):
        assert word in main, word
    # 親以外からの message は無視する。
    assert "ev.source !== window.parent" in main
    # `api.load` は fetch しない（wasm の場所はページから決まる）。v2.1 で `keep`（状態を保つ）が付いた。
    load = main[main.index("load: (jil, manifest, keep = false) =>") :]
    load = load[: load.index("lastResume:")]
    assert "fetch(" not in load and "loadSource(" not in load


def test_the_jinrec_reader_mirrors_the_python_one() -> None:
    """設計書 §11 #39（Phase 6）: `src/jinrec.ts` は `jin_wasm.jinrec.read_jinrec` の写し。

    版と kind の語彙が同じで、壊れ fixture（`tests/fixtures/jinrec/broken/`）を**両側が同じ期待値ファイル**で
    検算していること。`jin.replay` はこの読み手を通す。
    """
    from jin_wasm.jinrec import EVENT_KINDS, JINREC_VERSION

    reader = read(SRC / "jinrec.ts")
    assert f"export const JINREC_VERSION = {JINREC_VERSION};" in reader
    assert 'export const EVENT_KINDS = ["key", "pointer"] as const;' in reader
    assert EVENT_KINDS == ("key", "pointer")
    broken = REPO_ROOT / "tests" / "fixtures" / "jinrec" / "broken"
    assert (broken / "broken.expected.json").is_file()
    assert len(list(broken.glob("*.jinrec"))) >= 10
    ts_test = read(PLAYER / "test" / "jinrec.test.ts")
    py_test = (REPO_ROOT / "packages" / "jin-wasm" / "tests" / "test_jinrec_bundle.py").read_text(
        encoding="utf-8"
    )
    assert "broken.expected.json" in ts_test and "broken.expected.json" in py_test
    main = read(SRC / "main.ts")
    assert "parseJinrec(text)" in main


def test_the_replay_feeds_the_same_reducer_and_ends_paused() -> None:
    """runtime.md §10（Phase 6）: 再生は録画の行を `InputReducer` に通し、止まったまま終わる。

    `show` は描くだけで `tick` を呼ばない（ホストが呼ぶ Lua の関数は `boot` / `tick` の 2 つのまま。
    `test_the_player_calls_only_boot_and_tick` が見る）。
    """
    player = read(SRC / "player.ts")
    replay = player[player.index("replay(recording: Recording): number {") :]
    replay = replay[: replay.index("show(ops")]
    assert "this.reboot(recording.seed ?? this.o.manifest.stage.seed);" in replay
    assert "eventsByTick(recording.events, ticks)" in replay
    assert "this.advance(perTick[t] ?? [], false);" in replay
    assert "this.running = false;" in replay
    assert "collector.drain()" not in replay
    show = player[player.index("show(ops") :]
    show = show[: show.index("private queueFrame")]
    assert "renderer.draw(ops)" in show and "host.tick" not in show
    # e2e が再生と `jin run --input` の全行一致を見る。
    spec = read(PLAYER / "e2e" / "replay.spec.ts")
    assert "expect(browserRows).toEqual(headlessRows);" in spec


def test_the_player_keeps_state_across_a_reload_through_the_snapshot() -> None:
    """runtime.md §1.3 / §10（v2.1・設計書 §11 #42〜#44）: 状態を保った差し替え。

    - `jin.load` の `keep` → `PlayerApi.load(jil, manifest, keep)` → `Player.resumeFrom(previous)` が直近の tick 結果の
      `snapshot` を `manifest.resume` に付けて `boot` する（ホストが呼ぶ Lua の関数は `boot` / `tick` のまま）
    - reducer と押下状態（`InputCollector.adopt`）を引き継ぐ。録画は続けない
    - root が照合できず `resume.mode == "fresh"` ならその tick を捨てて `reboot`（行は流さない）
    - 世代（`generation`）は boot し直すたびに増え、続けたときは変わらない。`jin.status` に載る
    - Wasmoon は JS の `null` を Lua に積めない（probe §A.11）ので、`boot` は `withoutNulls` を通す
    """
    main = read(SRC / "main.ts")
    assert "data.keep === true" in main
    assert "current.resumeFrom(previous)" in main
    assert "collector.adopt(previousCollector)" in main
    assert "generation: player?.generation ?? 0," in main
    player = read(SRC / "player.ts")
    resume = player[player.index("resumeFrom(previous: Player): boolean {") :]
    resume = resume[: resume.index("start(): void {")]
    assert "this.o.host.boot(this.seed, { ...this.o.manifest, resume: snapshot });" in resume
    assert "this.reducer = previous.reducer;" in resume
    assert "this.recorder = null;" in resume
    assert "this.generation = previous.generation;" in resume
    assert "this.tick = snapshot.tick + 1;" in resume
    advance = player[player.index("private advance(") :]
    assert 'if (result.resume.mode === "fresh") {' in advance
    assert "this.reboot();" in advance
    assert "if (result.snapshot !== undefined) this.lastSnapshot = result.snapshot;" in advance
    reboot = player[
        player.index("reboot(seed = this.seed): void {") : player.index(
            "resumeFrom(previous: Player): boolean {"
        )
    ]
    assert "this.generation = nextGeneration;" in reboot
    host = read(SRC / "host.ts")
    assert 'this.lua.global.call("boot", Math.trunc(seed), withoutNulls(manifest));' in host
    types = read(SRC / "types.ts")
    assert "readonly snapshot?: Snapshot;" in types and "readonly resume?: ResumeNote;" in types
    assert "readonly resume?: Snapshot;" in types  # Manifest
    # e2e が Wasmoon 経路（proxy の userdata・空の state・16 進の PCG32）で続くことを見る。
    spec = read(PLAYER / "e2e" / "reload.spec.ts")
    assert "window.__jinPlayer?.load(j, m, true)" in spec
    assert 'kept: ["Game", "Play", "Result"]' in spec
