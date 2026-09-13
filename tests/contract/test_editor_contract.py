"""`apps/editor`（Phase 5）の契約を Python 側から固定する。

TS 側の検査（`pnpm lint` / `pnpm build` / `pnpm test` / `pnpm e2e`）が本体である。
ここが見るのは **「その検査が所定の位置にあり、CI で走る」** ことと、
Python 側からしか言えないこと（`jin editor` の入口・正準形の往復）である。

要件書 §7 / design.yaml `implementation_phases.items[5]`（Phase 5・machine 7 件）と
`items[6]`（Phase 6・machine 4 件）に対応する。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EDITOR = REPO_ROOT / "apps" / "editor"
SRC = EDITOR / "src"


def package_json() -> dict:
    return json.loads((EDITOR / "package.json").read_text(encoding="utf-8"))


def test_the_editor_exists_with_the_expected_scripts() -> None:
    """machine 4「pnpm test / pnpm build が通る」の足場。"""
    scripts = package_json()["scripts"]
    for name in ("dev", "typecheck", "build", "lint", "test", "e2e"):
        assert name in scripts, f"pnpm {name} が無い"
    assert scripts["build"].startswith("tsc --noEmit"), (
        "`pnpm build` が tsc を含まない。DP-COMMON-19 の網羅性を落とすのは tsc であり、"
        "vitest は型を見ない"
    )


def test_the_package_manager_is_pinned() -> None:
    """版を推測で置かない（CLAUDE.md「具体値を推測で置かない」）。"""
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+", package_json()["packageManager"]), (
        "packageManager が固定されていない"
    )
    assert (EDITOR / "pnpm-lock.yaml").is_file(), "pnpm-lock.yaml がコミットされていない"


def test_every_dependency_is_pinned_to_an_exact_version() -> None:
    """依存は**完全一致**で固定する（`^` / `~` を使わない）。

    レンダラの出力や LSP の応答と突き合わせるテストがあるので、
    ツールチェーンが黙って動くと原因の切り分けができなくなる。
    """
    manifest = package_json()
    loose: list[str] = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in manifest.get(section, {}).items():
            if not re.fullmatch(r"\d+\.\d+\.\d+", spec):
                loose.append(f"{name}: {spec}")
    assert loose == [], loose


def test_the_editor_never_draws_the_magic_circle_itself() -> None:
    """machine（要件書 §0 / §4 最終項）: **レンダラは Python 1 本**。

    エディタが SVG の図形要素を組み立てていないことを見る。診断バッジ（`circle`）と
    その入れ物（`g` / `title`）だけは `createElementNS` で作るが、これは
    **レイアウトを再計算していない**（位置は描かれた要素の `getBBox()` から取る）。
    `<path>` / `<line>` / `<text>` を作り始めたら、それは陣を描いている。
    """
    forbidden = re.compile(
        r'createElementNS\([^,]+,\s*"(path|line|text|polygon|polyline|ellipse|rect)"'
    )
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {match.group(1)}"
        for path in sorted(SRC.rglob("*.ts*"))
        for match in forbidden.finditer(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders


def test_the_property_panel_has_no_hand_written_form_definition() -> None:
    """machine 6「フォームが JSON Schema から生成され、手書きの定義ファイルが無い」。

    強い証拠は TS 側の `test/schemaForm.test.ts`（schema にキーを足すと欄が増える）である。
    ここでは弱い網として、**欄の名前を並べたファイルが `src/form` に無い**ことを見る。
    """
    schema_readers = [
        path
        for path in sorted(SRC.rglob("*.ts*"))
        if "jin.schema.json" in path.read_text(encoding="utf-8")
    ]
    assert schema_readers, "schemas/jin.schema.json を読んでいるファイルが無い"

    # `schemas/jin.schema.json` のコピーが `apps/editor` に無いこと（ドリフト防止）。
    copies = [p for p in EDITOR.rglob("jin.schema.json") if "node_modules" not in p.parts]
    assert copies == [], copies


def test_the_five_view_states_match_the_decided_set() -> None:
    """machine 7「DP-COMMON-19 の表示状態集合」を Python 側からも等号で見る。

    **状態数を 3 に固定しない**ことがこの判断の要点なので、
    5 つの名前をここに書いて TS 側と突き合わせる（片方だけ変えたら赤）。
    """
    source = (SRC / "state" / "viewState.ts").read_text(encoding="utf-8")
    listed = re.search(r"VIEW_STATE_KINDS = \[(.*?)\]", source, re.DOTALL)
    assert listed is not None, "VIEW_STATE_KINDS が見つからない"
    names = re.findall(r'"([a-z]+)"', listed.group(1))
    assert names == ["disconnected", "loading", "ready", "stale", "unavailable"], names
    assert "assertNever" in source, "網羅性の番人が無い"


def test_the_exhaustiveness_tripwire_is_present() -> None:
    """分岐漏れが**コンパイルエラーになる**ことの証拠が置かれている（machine 7）。

    `@ts-expect-error` は「エラーが出ないと逆に tsc が落ちる」ので、
    網羅性検査を緩めた瞬間に `pnpm build` が赤くなる。
    """
    fixture = (EDITOR / "test" / "exhaustiveness.fixture.ts").read_text(encoding="utf-8")
    # **説明文ではなくディレクティブ**を数える。docstring にも同じ語が出るので、
    # 単なる `in` 判定だと行を消しても緑のままになる（変異ハーネスで実測して直した）。
    directives = [
        line for line in fixture.splitlines() if line.lstrip().startswith("// @ts-expect-error")
    ]
    assert len(directives) == 1, directives
    assert "assertNever" in fixture


def test_the_editor_does_not_add_a_twentieth_operation() -> None:
    """要件書 §6.3 の 19 件を超えるオペレーション名をエディタが送らない。"""
    from jin_core.ops import OPERATIONS

    known = set(OPERATIONS)
    source = (SRC / "form" / "dispatch.ts").read_text(encoding="utf-8")
    source += (SRC / "App.tsx").read_text(encoding="utf-8")
    used = set(re.findall(r'op: "([A-Za-z]+)"', source))
    assert used <= known, sorted(used - known)
    assert len(known) == 19, len(known)


def test_jin_editor_does_not_use_the_pygls_start_ws() -> None:
    """`jin editor` は `JinLanguageServer.serve_ws` を使う（pygls の `start_ws` ではない）。

    pygls 2.1.1 の `start_ws` は 1 本目の接続が閉じた直後に `shutdown()` を呼ぶので、
    **ページを再読み込みしただけでエディタが死ぬ**。挙動そのものは
    `packages/jin-lsp/tests/test_ws_roundtrip.py::test_the_server_survives_a_client_reconnect`
    が見張っている。ここは呼び先が戻っていないことの二層目である。
    """
    source = (REPO_ROOT / "packages/jin-cli/src/jin_cli/editor.py").read_text(encoding="utf-8")
    assert "server.serve_ws(" in source
    assert "server.start_ws(" not in source


JIN = Path(sys.executable).parent / "jin"


def test_jin_editor_is_defined_in_a_real_process() -> None:
    """`jin editor` が実装されている（要件書 §7.3）。**実バイナリで**確かめる。"""
    result = subprocess.run(
        [str(JIN), "editor", "--help"], capture_output=True, text=True, cwd=REPO_ROOT, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "エディタ" in result.stdout


def test_jin_editor_refuses_a_non_jin_file(tmp_path: Path) -> None:
    """`.jin` 以外は 1 行で断る（トレースバックを出さない・NFR-FAIL-001）。"""
    other = tmp_path / "a.txt"
    other.write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [str(JIN), "editor", str(other), "--no-browser"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert ".jin" in result.stderr


def test_jin_editor_reports_a_missing_build(tmp_path: Path) -> None:
    """ビルド済みエディタが無いときに 404 を配らず、何をすべきかを言って落ちる。"""
    target = tmp_path / "a.jin"
    target.write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [str(JIN), "editor", str(target), "--no-browser", "--dist", str(tmp_path / "none")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "index.html" in result.stderr or "pnpm build" in result.stderr


# ======================================================================================
# Phase 6: デバッグモード（要件書 §7.2 / design.yaml items[6]）
# ======================================================================================
TRACE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "traces" / "pipeline-fake.jsonl"


def test_the_debug_mode_does_not_add_a_new_lsp_request() -> None:
    """トレースは**ブラウザが読む**（HANDOFF `DP-IMPL-JIN-P6-TRACE-SOURCE-01`）。

    要件書 §6.3 の独自リクエスト 4 種（+ ADR-011 の `jin/open` / `jin/save`）への
    **追加は仕様変更**であり、人間の承認が要る。`<input type="file">` なら
    読めるのはユーザーが選んだ 1 本だけで、`jin lsp --ws` の口も広がらない
    （`docs/spec/ops.md` §5.1）。
    """
    protocol = (SRC / "rpc" / "protocol.ts").read_text(encoding="utf-8")
    listed = re.search(r"JIN_METHOD = \{(.*?)\} as const", protocol, re.DOTALL)
    assert listed is not None, "JIN_METHOD が見つからない"
    methods = set(re.findall(r'"(jin/[A-Za-z]+)"', listed.group(1)))
    assert methods == {
        "jin/model",
        "jin/renderSvg",
        "jin/ops",
        "jin/applyOps",
        "jin/open",
        "jin/save",
    }, sorted(methods)

    # ソースのどこにも 6 種以外の `jin/…` を書いていないこと。
    used: set[str] = set()
    for path in sorted(SRC.rglob("*.ts*")):
        used |= set(re.findall(r'"(jin/[A-Za-z]+)"', path.read_text(encoding="utf-8")))
    assert used <= methods, sorted(used - methods)

    # ブラウザ側で JSONL を読む口が実在すること（読み込みをサーバへ回していない）。
    parse = (SRC / "trace" / "parse.ts").read_text(encoding="utf-8")
    assert "parseTrace" in parse
    assert 'type="file"' in (SRC / "debug" / "DebugPanel.tsx").read_text(encoding="utf-8")


def test_the_editor_does_not_compute_the_overlay_itself() -> None:
    """machine 2 の前提: オーバーレイを描くのは `jin_render` 1 本（要件書 §0 / §4 最終項）。

    `data-jin-fired` / `data-jin-seq` はサーバが返した SVG に**既に入っている**。
    エディタがこれを自分で付け始めたら、同じ `upto` で同じ SVG になる保証が
    レンダラの決定性（DP-JIN-SVG-DETERMINISM-01）から外れる。
    """
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {name}"
        for path in sorted(SRC.rglob("*.ts*"))
        for name in ("data-jin-fired", "data-jin-seq")
        if name in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


def test_the_pointer_filter_agrees_with_the_overlay_rule() -> None:
    """machine 3: フィルタの一致規則が overlay の規則 1 と**同じ**であること。

    強い証拠は TS 側の `test/trace.test.ts` だが、その期待値が正しいことは
    TS だけでは言えない。ここで `jin_render.overlay.is_ancestor_or_same` に
    **実トレース**を通した結果を計算し、TS が書いている期待値と突き合わせる。
    レンダラ側の規則を変えれば、こちらの計算が動いて TS の期待値とずれ、赤くなる。
    """
    from jin_render.overlay import is_ancestor_or_same

    rows = [
        json.loads(line)
        for line in TRACE_FIXTURE.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    assert len(rows) == 11, len(rows)

    source = (EDITOR / "test" / "trace.test.ts").read_text(encoding="utf-8")
    checked = 0
    for pointer in ("/circles/2/core", "/circles/4/core", "/circles/4", "/circles/1/flow/exit"):
        expected = [
            row["seq"]
            for row in rows
            if row["pointer"] is not None and is_ancestor_or_same(pointer, row["pointer"])
        ]
        found = re.search(
            re.escape(f'eventsFiredAt(rows, "{pointer}")')
            + r"[\s\S]{0,90}?toEqual\(\[([0-9, ]*)\]\)",
            source,
        )
        assert found is not None, f"TS 側に {pointer} の期待値が無い"
        written = [int(value) for value in found.group(1).split(",") if value.strip()]
        assert written == expected, (pointer, written, expected)
        checked += 1
    assert checked == 4

    # **前方一致にしない**ことの検査が TS 側に置かれていること（変異の主対象）。
    assert '"/circles/20/core"' in source, "段一致（`/` 区切り）の反例が無い"


def test_the_e2e_uses_the_committed_trace_fixture() -> None:
    """デバッグモードの e2e が**実際に `jin run` が書いた**トレースを読むこと。

    作り物の JSONL を使うと「レンダラが読める形」から静かにずれる。この fixture が
    実行結果と一致することは `tests/contract/test_render_contract.py` が見張っている。
    """
    spec = (EDITOR / "e2e" / "debug.spec.ts").read_text(encoding="utf-8")
    # **説明文ではなく代入**を見る。単なる `in` 判定だと、docstring に同じパスが
    # 書いてあるせいで値を差し替えても緑のままになる（変異ハーネスで実測して直した）。
    assert re.search(
        r'const TRACE = join\(\s*REPO_ROOT,\s*"tests/fixtures/traces/pipeline-fake\.jsonl",?\s*\)',
        spec,
    ), "e2e が実トレース fixture を読んでいない"
    assert re.search(r'readFileSync\(join\(REPO_ROOT, "examples/pipeline/pipeline\.jin"\)', spec), (
        "e2e が examples/pipeline を台本にしていない"
    )
    assert TRACE_FIXTURE.is_file()


def test_the_detail_panel_shows_the_four_fields() -> None:
    """machine 4: 詳細パネルが `input` / `output` / `name` / `kind` を出す。

    **本体は Playwright**（`e2e/debug.spec.ts` の machine 4）である。ここは
    「4 つの欄が消えていない」ことだけを見る弱い網で、変異ハーネス（e2e を回さない）から
    欄の削除に気づけるようにするために置いている。
    """
    panel = (SRC / "debug" / "DebugPanel.tsx").read_text(encoding="utf-8")
    spec = (EDITOR / "e2e" / "debug.spec.ts").read_text(encoding="utf-8")
    for field in ("kind", "name", "input", "output"):
        assert f'data-testid="jin-detail-{field}"' in panel, field
        assert f'"jin-detail-{field}"' in spec, field
    # **そのまま**出す（要約・切り詰めをしない）。
    assert "JSON.stringify(value, null, 2)" in panel


def test_the_trace_is_not_folded_into_the_view_state() -> None:
    """DP-COMMON-19 の 5 状態を**増やさない**。

    トレースの有無は「LSP との関係」と直交する（構文エラー中でもトレースは読めるし、
    正常表示でもトレースが無いことはある）。`ViewState` に畳むと状態が 10 通りになる。
    """
    source = (SRC / "state" / "viewState.ts").read_text(encoding="utf-8")
    for word in ("Replay", "trace", "upto"):
        assert word not in source, f"{word} が ViewState に入り込んでいる"


# --------------------------------------------------------------------------------------
# e2e が `jin editor` のプロセスを取り残さないこと（Issue #32）
# --------------------------------------------------------------------------------------
def e2e_harness() -> str:
    return (EDITOR / "e2e" / "editor.ts").read_text(encoding="utf-8")


def brace_block(source: str, opener: str) -> str:
    """`opener` の正規表現に続く `{ ... }` の中身を、括弧の対応で切り出す。

    行頭の字下げで切ると formatter の設定（タブ / 空白）に依存して静かに空振りする。
    """
    match = re.search(opener, source)
    assert match is not None, f"{opener} が見つからない"
    begin = source.index("{", match.end() - 1)
    depth = 0
    for index in range(begin, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[begin + 1 : index]
    raise AssertionError(f"{opener} の閉じ括弧が見つからない")


def test_the_e2e_harness_does_not_signal_the_editor_with_sigint() -> None:
    """SIGINT は `uv` の**孫**（Python の `jin editor`）へ伝わらない（Issue #32・実測）。

    `spawn` の直接の子は `uv` である。SIGINT を送ると `uv` 自身も終わらず、
    `uv run` と Python の 2 プロセスがポートを掴んだまま残る。2026-09-08 の実測では
    前日の `pnpm e2e` が 90 個を取り残していた。SIGTERM は `uv` が孫へ中継する。

    見るのは**文字列リテラルとしての SIGINT** と、`kill()` にシグナル名を渡していないこと。
    散文の「SIGINT ではない」という説明で緑にならないよう、素の `in` では数えない。
    """
    source = e2e_harness()
    assert '"SIGINT"' not in source and "'SIGINT'" not in source, (
        "e2e のハーネスが SIGINT を送っている。uv の孫まで届かないので取り残す（Issue #32）"
    )
    assert re.search(r"\.kill\(\s*['\"]", source) is None, (
        "kill() にシグナル名を渡している。既定（SIGTERM）以外は uv が孫へ中継しない"
    )


def test_the_e2e_harness_kills_the_child_when_the_url_cannot_be_read() -> None:
    """URL を読めずに reject する経路でも子を落とすこと（Issue #32 の 2 つ目の経路）。

    `startEditor` が例外を投げると呼び出し元は `RunningEditor` を受け取れないので、
    **`stop()` を呼ぶ手段そのものが無い**。この経路（60 秒のタイムアウト / 子の早期 exit）で
    殺し忘れると確実に取り残す。`afterEach` の検査では届かないのでここで固定する。

    `catch` の**中**に `child.kill(` があることを見る。ファイル全体で
    `"child.kill(" in source` を数えると `stop()` 側の 1 本で緑になってしまう。
    """
    body = brace_block(e2e_harness(), r"\}\s*catch\s*\([^)]*\)\s*")
    assert "child.kill(" in body, (
        "URL を読めなかった経路で子を落としていない（呼び出し元は stop() を呼べない）"
    )


def test_both_e2e_specs_assert_the_editor_actually_stopped() -> None:
    """取り残しを**テストの赤**にすること。

    `stop()` の戻り値を捨てると、時間内に終わらなかった回が静かに素通りする。
    ポートが閉じたことは `stop()` の外（`afterEach`）で見る決まりで、
    `stop()` の中へ移すと「`await` を落とす」変更が赤くならない。
    """
    for name in ("smoke.spec.ts", "debug.spec.ts"):
        spec = (EDITOR / "e2e" / name).read_text(encoding="utf-8")
        stopped = re.search(r"expect\(\s*stopped\s*\)\.toBe\(true\)", spec)
        assert stopped is not None, f"{name} が stop() の戻り値を見ていない"
        port = spec.find("await expectServerGone(editor.url)")
        assert port != -1, f"{name} がポートの解放を見ていない"
        assert port < stopped.start(), (
            f"{name} はポートの解放を先に見ること。"
            "戻り値を先に見ると、uv だけが終わって孫が残る形（Linux で SIGTERM が"
            "中継されない場合）に到達しない"
        )


# ======================================================================================
# Jin v2（Phase 5・設計書 §8）
# ======================================================================================
def test_the_v2_editor_uses_only_the_thirty_two_v2_operations() -> None:
    """`src/v2/` が送るオペレーション名は `jin_core.v2.ops.OPERATIONS`（32 件）に閉じる。

    v1 の 19 件（`form/dispatch.ts` / `App.tsx`）とは**別集合**で、v2 の op を v1 のファイルに
    書けば上の `test_the_editor_does_not_add_a_twentieth_operation` が落ち、v1 の op を
    ここに書けばこちらが落ちる（`setDescription` / `moveTool` は v2 に無い）。
    """
    from jin_core.v2.ops import OPERATIONS

    known = set(OPERATIONS)
    assert len(known) == 32, len(known)
    used: set[str] = set()
    for path in sorted((SRC / "v2").rglob("*.ts*")):
        used |= set(re.findall(r'op: "([A-Za-z]+)"', path.read_text(encoding="utf-8")))
    assert used <= known, sorted(used - known)
    # 実際に使っていること（走査対象が消えて空で緑になっていない）。
    assert {"addStep", "setStep", "moveStep", "wrapSteps", "extractRite", "rename"} <= used


def test_the_v2_hit_test_lists_the_thirteen_kinds_of_the_renderer() -> None:
    """`JIN_KINDS_V2` は `jin_render.DATA_JIN_KINDS_V2` と等号（v1 の 9 種は変えない）。"""
    from jin_render import DATA_JIN_KINDS, DATA_JIN_KINDS_V2

    source = (SRC / "svg" / "hitTest.ts").read_text(encoding="utf-8")
    v1 = re.search(r"JIN_KINDS = \[(.*?)\] as const", source, re.DOTALL)
    v2 = re.search(r"JIN_KINDS_V2 = \[(.*?)\] as const", source, re.DOTALL)
    assert v1 is not None and v2 is not None
    assert re.findall(r'"([a-z-]+)"', v1.group(1)) == list(DATA_JIN_KINDS)
    assert re.findall(r'"([a-z-]+)"', v2.group(1)) == list(DATA_JIN_KINDS_V2)


def test_the_v2_form_reads_the_v2_schema_without_a_copy() -> None:
    """v2 のフォームも schema から生成する。`jin-v2.schema.json` の写しを `apps/editor` に置かない。"""
    readers = [
        path
        for path in sorted(SRC.rglob("*.ts*"))
        if "jin-v2.schema.json" in path.read_text(encoding="utf-8")
    ]
    assert readers, "schemas/jin-v2.schema.json を読んでいるファイルが無い"
    copies = [
        p
        for name in ("jin-v2.schema.json", "abilities.json")
        for p in EDITOR.rglob(name)
        if "node_modules" not in p.parts
    ]
    assert copies == [], copies
    # 式エディタを出す判定は schema の印だけ（欄の名前を書き写さない）。
    form = (SRC / "form" / "schemaForm.ts").read_text(encoding="utf-8")
    assert '"x-jin-expr"' in form
    panel = (SRC / "v2" / "PropertyPanelV2.tsx").read_text(encoding="utf-8")
    assert "field.expr" in panel


def test_the_run_panel_does_not_use_the_run_endpoint() -> None:
    """設計書 §8: v2 の実行パネルは同一オリジンの iframe `/play/` で、`POST /run` を使わない。"""
    panel = (SRC / "run" / "RunPanel.tsx").read_text(encoding="utf-8")
    assert '"/run"' not in panel and "'/run'" not in panel and "`/run`" not in panel
    assert "runAgent" not in panel and "X-Jin-Token" not in panel
    assert "src={PLAYER_PATH}" in panel and 'PLAYER_PATH = "./play/"' in panel
    # プレイヤーの `jin.load` / `jin.trace` / `jin.control` と同じ語で話す。
    for word in ('"jin.load"', '"jin.trace"', '"jin.control"'):
        assert word in panel, word
    # 受け取りは iframe の contentWindow からのものだけ。
    assert "event.source !== frame.current?.contentWindow" in panel
    # `jin editor` 側の前置きと同じ文字列。
    editor_py = (REPO_ROOT / "packages" / "jin-cli" / "src" / "jin_cli" / "editor.py").read_text(
        encoding="utf-8"
    )
    assert 'PLAY_PREFIX = "/play/"' in editor_py


def test_the_expression_editor_does_not_reimplement_the_expression_grammar() -> None:
    """設計書 §8: 式エディタは `jin_core.v2.expr` を再実装しない。候補は LSP の completion。"""
    editor = (SRC / "v2" / "ExprEditor.tsx").read_text(encoding="utf-8")
    assert "textDocument/completion" in (SRC / "rpc" / "jin.ts").read_text(encoding="utf-8")
    # 演算子や予約語の表を持たない（トークンは識別子と `.` だけ）。
    for word in ("and", "or", "not", "++"):
        assert f'"{word}"' not in editor, word
    assert "parse" not in editor.lower().replace("parsefloat", "")


# --------------------------------------------------------------------------------------
# Jin v2 Phase 6（設計書 §8 / §11 #39〜#41・runtime.md §5 / §10）
# --------------------------------------------------------------------------------------
PLAYER_VOCABULARY = {
    # 親 → プレイヤー
    "jin.load",
    "jin.control",
    "jin.replay",
    "jin.frame",
    # プレイヤー → 親
    "jin.trace",
    "jin.status",
    "jin.recording",
}


def test_the_parent_and_the_player_speak_the_same_vocabulary() -> None:
    """runtime.md §10: 親（`RunPanel.tsx`）とプレイヤー（`main.ts`）の `"jin.xxx"` は**同じ集合**（等号）。

    片方だけに語を足すと黙って届かない message になる。語彙はこの 2 ファイルの外に書かない
    （`App` は `PlayerControl` / `PlayerStatus` の型を通してだけ関わる）。
    """
    words = re.compile(r'"(jin\.[a-z]+)"')
    panel = (SRC / "run" / "RunPanel.tsx").read_text(encoding="utf-8")
    main = (REPO_ROOT / "apps" / "player" / "src" / "main.ts").read_text(encoding="utf-8")
    assert set(words.findall(panel)) == PLAYER_VOCABULARY, sorted(set(words.findall(panel)))
    assert set(words.findall(main)) == PLAYER_VOCABULARY, sorted(set(words.findall(main)))
    leaked = [
        f"{path.relative_to(REPO_ROOT)}: {word}"
        for path in sorted(SRC.rglob("*.ts*"))
        if path.name != "RunPanel.tsx"
        for word in words.findall(path.read_text(encoding="utf-8"))
    ]
    assert leaked == [], leaked


def test_the_editor_does_not_read_the_recording_itself() -> None:
    """設計書 §11 #39: `.jinrec` の読み手はプレイヤー（`apps/player/src/jinrec.ts`）。

    エディタは 1 行目に `"jinrec"` があるかだけを見て、生のテキストを `jin.replay` で渡す。
    読み手をここにも置くと `read_jinrec` の写しが 3 つ目になる（`apps/player` の TS は import できない）。
    """
    panel = (SRC / "run" / "RunPanel.tsx").read_text(encoding="utf-8")
    assert "looksLikeJinrec" in panel
    assert '"jin.replay", text' in panel
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {word}"
        for path in sorted(SRC.rglob("*.ts*"))
        for word in ("parseJinrec", "eventsByTick", 'from "../jinrec"', "JINREC_VERSION")
        if word in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


def test_the_state_values_are_accumulated_only_from_the_trace_rows_named_by_the_runtime_spec() -> (
    None
):
    """runtime.md §5: 「エディタのスクラバは `set` 行を積算して記憶環の値を出し、`frame` 行で画面を出す」。

    積算は `debug/values.ts` の 1 か所で、見る `kind` は `enter` / `exit` / `set` / `assert` / `frame` だけ。
    ラベルは SVG の外の HTML 層（`SvgCanvas` の `jin-labels`）に置く（`<text>` を作らない契約は
    `test_the_editor_never_draws_the_magic_circle_itself` が見る）。
    """
    values = (SRC / "debug" / "values.ts").read_text(encoding="utf-8")
    # `kind === "enter"` と `stringOf(event, "kind") !== "assert"` の両方の形を拾う。
    kinds = set(re.findall(r'\bkind\W{0,3}(?:!==|===) "([a-z]+)"', values))
    assert kinds == {"enter", "exit", "set", "assert", "frame"}, sorted(kinds)
    canvas = (SRC / "svg" / "SvgCanvas.tsx").read_text(encoding="utf-8")
    assert 'className="jin-labels"' in canvas and "getBoundingClientRect" in canvas
    # 積算をレンダラに頼まない（`jin/renderSvg` の引数は trace + upto + focus のまま）。
    app = (SRC / "App.tsx").read_text(encoding="utf-8")
    assert "stateValuesAt(replay.events, replay.upto)" in app
    assert "values:" not in (SRC / "rpc" / "jin.ts").read_text(encoding="utf-8")


def test_the_replay_rows_are_never_trimmed() -> None:
    """設計書 §11 #41: 録画の再生の行は落とさない（落とすと `enter` 行が消えて値が黙って狂う）。"""
    app = (SRC / "App.tsx").read_text(encoding="utf-8")
    assert "export const MAX_LIVE_ROWS = 4000;" in app
    assert "export const MAX_REPLAY_ROWS = 60000;" in app
    replay_branch = app[app.index('if (source.kind === "replay")') :]
    replay_branch = replay_branch[: replay_branch.index("const trimmed")]
    assert "slice(" not in replay_branch
    assert "MAX_REPLAY_ROWS" in replay_branch and "return;" in replay_branch


def test_the_v2_e2e_uses_the_committed_recording_fixture() -> None:
    """§12 行 6 の完了条件は実ブラウザで見る。録画はコミット済みの fixture で、プレイヤーの e2e と同じもの。"""
    spec = (EDITOR / "e2e" / "v2.spec.ts").read_text(encoding="utf-8")
    replay_spec = (REPO_ROOT / "apps" / "player" / "e2e" / "replay.spec.ts").read_text(
        encoding="utf-8"
    )
    fixture = "tests/fixtures/jinrec/paddle-120.jinrec"
    assert (REPO_ROOT / fixture).is_file()
    assert fixture in spec
    assert '"paddle-120.jinrec"' in replay_spec
    for phrase in (
        ".jinrec を読んでスクラブするとオーバーレイと記憶環の値が動く",
        "偽になった assert はバッジと一覧に出て",
        "録画して書き出した .jinrec は jin run --input で同じ行数になり",
    ):
        assert phrase in spec, phrase
