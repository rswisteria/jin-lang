"""`apps/editor`（Phase 5）の契約を Python 側から固定する。

TS 側の検査（`pnpm lint` / `pnpm build` / `pnpm test` / `pnpm e2e`）が本体である。
ここが見るのは **「その検査が所定の位置にあり、CI で走る」** ことと、
Python 側からしか言えないこと（`jin editor` の入口・正準形の往復）である。

要件書 §7 / design.yaml `implementation_phases.items[5].verification.machine` 7 件に対応する。
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
