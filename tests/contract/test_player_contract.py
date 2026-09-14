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
    assert 'export const EVENT_KINDS = ["key", "pointer", "text"] as const;' in reader
    assert EVENT_KINDS == ("key", "pointer", "text")  # text は v2.1（abilities.md §3）
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
    # v2.1: ヘッダの seed と記憶の写し（スクラッチ）で boot し直す（abilities.md §8）。
    assert "recording.seed ?? this.o.manifest.stage.seed," in replay
    assert "new Map(Object.entries(recording.storage ?? {}))," in replay
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
    assert "resume: snapshot," in resume and "storage: this.storageCopy()," in resume
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


def test_the_player_owns_the_storage_copy_and_never_persists_a_replay() -> None:
    """abilities.md §8 / runtime.md §10（v2.1・設計書 §11 #47）: 記憶の写しはプレイヤーが持つ。

    - すべての `boot`（最初から / 録画 / 差し替え / 再生）に `manifest.storage` を渡す
    - tick の戻り値の `storage` を写しへ反映し、`onStore` で永続化を頼む（`localStorage` の鍵は `jin.storage:<file>`）
    - 再生はヘッダの写しから始まるスクラッチに書き、永続化しない
    - 録画のヘッダには録画の boot に渡した写し。読み手は Python と同じ文言で検査する
    """
    player = read(SRC / "player.ts")
    assert "readonly store: Map<string, string>;" in player
    assert player.count("storage: this.storageCopy(),") == 3  # restart / resumeFrom / Recorder
    assert "new Map(Object.entries(recording.storage ?? {}))," in player
    assert "if (this.scratch === null) this.o.onStore?.(result.storage, this.store);" in player
    main = read(SRC / "main.ts")
    assert "return `jin.storage:${file}`;" in main
    assert "onStore: (_writes, store) => saveStore(source.manifest.file, store)," in main
    assert 'data.action === "forget"' in main
    recorder = read(SRC / "recorder.ts")
    assert "? { storage }" in recorder
    reader = read(SRC / "jinrec.ts")
    for fragment in ("ヘッダの storage はオブジェクトです", "ヘッダの storage の値は文字列です"):
        assert fragment in reader, fragment
    broken = REPO_ROOT / "tests" / "fixtures" / "jinrec" / "broken"
    assert (broken / "storage-not-object.jinrec").is_file()
    assert (broken / "storage-value-not-str.jinrec").is_file()
    # e2e: localStorage に残り読み直しで続く → 録画のヘッダの写しで jin run --input と全行一致 → 再生は上書きしない
    spec = read(PLAYER / "e2e" / "storage.spec.ts")
    assert "expect(browserRows).toEqual(headlessRows);" in spec
    assert 'window.localStorage.getItem("jin.storage:storage.jin")' in spec


# ---------------------------------------------------------------- 書体（abilities.md §2・v2.1・設計書 §11 #49）

FONT_DIR = PLAYER / "fonts" / "k6x8"
FONT_BDF = FONT_DIR / "k6x8_gothic.bdf"
GLYPHS_TS = SRC / "glyphs.ts"


def _glyph_table() -> dict[int, bytes]:
    """`glyphs.ts` の 2 本の base64 を読む（コードポイントは 2 バイト big-endian、字形は 6 バイト）。"""
    import base64

    text = read(GLYPHS_TS)
    blobs = {}
    for name in ("CODEPOINTS", "BITMAPS"):
        found = re.search(rf'export const {name} =\s*"([A-Za-z0-9+/=]*)";', text)
        assert found is not None, f"glyphs.ts に {name} が無い"
        blobs[name] = base64.b64decode(found.group(1))
    codepoints = [
        int.from_bytes(blobs["CODEPOINTS"][i : i + 2], "big")
        for i in range(0, len(blobs["CODEPOINTS"]), 2)
    ]
    assert codepoints == sorted(set(codepoints)), "コードポイントが昇順・重複なしでない"
    assert len(blobs["BITMAPS"]) == 6 * len(codepoints)
    return {cp: blobs["BITMAPS"][6 * i : 6 * i + 6] for i, cp in enumerate(codepoints)}


def _bdf_cells() -> dict[int, bytes]:
    """BDF を生成スクリプトとは独立に読み、6×8 の枠（列ごと・bit0 が最上段）に置く。"""
    cells: dict[int, bytes] = {}
    ascent = 0
    codepoint = width = height = x_off = y_off = 0
    lines = iter(FONT_BDF.read_text(encoding="ascii").splitlines())
    for line in lines:
        head, _, rest = line.partition(" ")
        if head == "FONT_ASCENT":
            ascent = int(rest)
        elif head == "ENCODING":
            codepoint = int(rest)
        elif head == "BBX":
            width, height, x_off, y_off = map(int, rest.split())
        elif head == "BITMAP":
            columns = [0] * 6
            span = (width + 7) // 8 * 8
            for row in range(height):
                bits = int(next(lines), 16)
                for col in range(width):
                    if bits >> (span - 1 - col) & 1:
                        columns[x_off + col] |= 1 << (ascent - (y_off + height) + row)
            cells[codepoint] = bytes(columns)
    return cells


def _sjis_decoded(ku: int, ten: int) -> str | None:
    """JIS X 0208 の区点を Shift_JIS に写して cp932 で読む（euc_jp と対応先が割れる区点がある）。"""
    lead = (ku + 257) // 2 if ku <= 62 else (ku + 385) // 2
    trail = (ten + 63 + (ten >= 64)) if ku % 2 else ten + 158
    try:
        return bytes([lead, trail]).decode("cp932")
    except UnicodeDecodeError:
        return None


def test_the_glyph_data_is_generated_from_the_bundled_bdf() -> None:
    """`glyphs.ts` は `scripts/generate_glyphs.py` の生成物（手で編集しない）。CI の diff と 2 重の網。"""
    import subprocess
    import sys

    check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_glyphs.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "scripts/generate_glyphs.py" in read(GLYPHS_TS)
    ci = read(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    assert (
        "uv run python scripts/generate_glyphs.py --stdout | diff -u apps/player/src/glyphs.ts -"
        in ci
    )


def test_the_glyphs_are_every_non_ascii_glyph_of_k6x8_gothic() -> None:
    """ASCII は `font.ts` の 5×7 のまま。それ以外は k6x8 ゴシックの字形を**全部**そのまま持つ。"""
    cells = _bdf_cells()
    assert len(cells) == 7096
    assert _glyph_table() == {cp: cell for cp, cell in cells.items() if cp > 0x7E}


def test_the_glyphs_cover_jis_x_0208_in_both_unicode_mappings() -> None:
    """JIS X 0208 の全区点を、euc_jp（JIS 流）と cp932（Windows 流）の両方の対応先で持つ。"""
    table = _glyph_table()
    missing = []
    for ku in range(1, 95):
        for ten in range(1, 95):
            try:
                euc = bytes([0xA0 + ku, 0xA0 + ten]).decode("euc_jp")
            except UnicodeDecodeError:
                continue
            for ch in {euc, _sjis_decoded(ku, ten) or euc}:
                if ord(ch) not in table:
                    missing.append((ku, ten, f"U+{ord(ch):04X}"))
    assert missing == []


def test_the_font_source_keeps_its_license_and_digest() -> None:
    """k6x8 は自由なライセンス（改変の有無・商用を問わず利用・複製・再配布できる）。出典と原本の digest を残す。"""
    import hashlib

    license_text = (FONT_DIR / "k6x8.txt").read_text(encoding="utf-8")
    assert "Unlimited permission is granted to use, copy, and distribute them" in license_text
    digest = hashlib.sha256(FONT_BDF.read_bytes()).hexdigest()
    assert digest in read(FONT_DIR / "README.md")
    header = read(GLYPHS_TS).split("*/", 1)[0]
    for needle in ("Copyright (C) 2000-2023 Num Kadoma", digest, "Unlimited permission is granted"):
        assert needle in header, needle
