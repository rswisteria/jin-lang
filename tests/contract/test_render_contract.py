"""パッケージ横断契約: トレースの pointer 空間と描画の `data-jin` 空間が一致すること。

要件書 §10 #11 / `docs/spec/model.md` §6: pointer は「ファイル内の位置・描画要素（`data-jin`）・
診断・トレースイベント」を結ぶ**唯一の鍵**である。Phase 2（`jin_adk.trace`）が付ける pointer と
Phase 3（`jin_render`）が付ける `data-jin` は別のパッケージで独立に作られるので、
**両方を実際に動かして突き合わせる**のはここにしか置けない。

`jin_adk` を import してよいのは `tests/contract/` だけである（`jin-render` のパッケージテストは
`jin_core` と標準ライブラリしか見ない・ADR-003 / design.yaml rule 4）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_core.model import JinFile
from jin_core.pointer import pointer_exists
from jin_render import DATA_JIN_KINDS, render

from tests.conftest import env_with_stubs

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
COMMITTED_TRACE = REPO_ROOT / "tests" / "fixtures" / "traces" / "pipeline-fake.jsonl"
JIN = Path(sys.executable).parent / "jin"


def _model(path: Path) -> JinFile:
    result = check_file(path)
    assert result.model is not None, path
    return result.model


def _elements(svg: str) -> list[dict[str, str]]:
    namespace = "{http://www.w3.org/2000/svg}"
    root = ET.fromstring(svg)
    found: list[dict[str, str]] = []

    def walk(node: ET.Element, inside_defs: bool) -> None:
        for child in node:
            in_defs = inside_defs or child.tag == f"{namespace}defs"
            if not in_defs:
                found.append(dict(child.attrib))
            walk(child, in_defs)

    walk(root, False)
    return found


def _keys(svg: str) -> set[str]:
    """`data-jin` と `data-jin-ref` の和集合（overlay が引ける鍵の全体）。"""
    keys: set[str] = set()
    for attributes in _elements(svg):
        for name in ("data-jin", "data-jin-ref"):
            value = attributes.get(name)
            if value is not None:
                keys.add(value)
    return keys


def _resolves(keys: set[str], pointer: str) -> bool:
    """pointer を末尾から削りながら、鍵に当たるかを見る（layout.md §7 の強調規則と同じ）。"""
    tokens = pointer.lstrip("/").split("/")
    for length in range(len(tokens), 0, -1):
        if "/" + "/".join(tokens[:length]) in keys:
            return True
    return False


@pytest.fixture(scope="module")
def live_trace(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    """`jin run --model fake` を**実際に回して**得たトレース（ネットワーク・API キー不要）。

    コミット済みの fixture が古びていないことも同時に確かめる（下の突合テスト）。
    """
    assert JIN.exists(), f"jin コマンドが見つからない: {JIN}"
    target = tmp_path_factory.mktemp("trace") / "live.jsonl"
    result = subprocess.run(
        [
            str(JIN),
            "run",
            str(EXAMPLES / "pipeline" / "pipeline.jin"),
            "go",
            "--model",
            "fake",
            "--trace",
            str(target),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env_with_stubs(),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in target.read_text(encoding="utf-8").split("\n") if line]


def test_the_live_run_produces_rows(live_trace: list[dict]) -> None:
    assert len(live_trace) == 11


def test_the_committed_fixture_matches_a_live_run(live_trace: list[dict]) -> None:
    """`tests/fixtures/traces/pipeline-fake.jsonl` が実行結果と同じ形であること。

    `ts` は実行のたびに変わるので比べない。行数・`seq` / `kind` / `pointer` を突き合わせる。
    """
    committed = [
        json.loads(line) for line in COMMITTED_TRACE.read_text(encoding="utf-8").split("\n") if line
    ]
    fields = ("seq", "agent", "kind", "name", "pointer")
    assert [{k: row[k] for k in fields} for row in committed] == [
        {k: row[k] for k in fields} for row in live_trace
    ]


def test_every_live_pointer_resolves_at_the_root_focus(live_trace: list[dict]) -> None:
    """申し送り §4: focus=root（Pipeline）で全 pointer が何かの要素に解決すること。

    「focus=各 circle の和集合」では referent 規則の有無を検出できない（root 焦点でしか
    下位 circle の `model` 行が参照側の要素に落ちない）。
    """
    model = _model(EXAMPLES / "pipeline" / "pipeline.jin")
    keys = _keys(render(model))
    for row in live_trace:
        pointer = row["pointer"]
        if pointer is None:
            continue
        assert _resolves(keys, pointer), f"seq={row['seq']} {pointer} が解決しない"


@pytest.mark.parametrize("focus", ["Pipeline", "Refine", "Drafter"])
def test_at_least_one_live_pointer_resolves_for_each_focus(
    live_trace: list[dict], focus: str
) -> None:
    """焦点を変えても、少なくとも 1 つの行が解決すること（描画が空になっていない側の確認）。"""
    model = _model(EXAMPLES / "pipeline" / "pipeline.jin")
    keys = _keys(render(model, focus=focus))
    resolved = [row for row in live_trace if row["pointer"] and _resolves(keys, row["pointer"])]
    assert resolved, focus


def test_every_live_pointer_exists_in_the_model(live_trace: list[dict]) -> None:
    """トレースの pointer 自体がモデルに解決できること（Phase 2 の契約の再確認）。"""
    model = _model(EXAMPLES / "pipeline" / "pipeline.jin")
    document = model.model_dump(mode="json", by_alias=True)
    for row in live_trace:
        if row["pointer"] is not None:
            assert pointer_exists(document, row["pointer"]), row


def test_the_cli_and_the_library_produce_the_same_svg() -> None:
    """要件書 §4 最終項: CLI の `jin render` と `jin_render.render` は同じ出力を返す。

    Phase 4 の `jin/renderSvg` も同じ関数を呼ぶ（入口を 2 本にしない）。
    """
    path = EXAMPLES / "researcher" / "researcher.jin"
    result = subprocess.run(
        [str(JIN), "render", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.decode("utf-8") == render(_model(path))


@pytest.mark.parametrize("name", ["researcher/researcher.jin", "pipeline/pipeline.jin"])
def test_every_rendered_pointer_is_in_the_model_pointer_space(name: str) -> None:
    """描画側 → モデル。`data-jin` と `data-jin-ref` がモデルに解決できること。"""
    model = _model(EXAMPLES / name)
    document = model.model_dump(mode="json", by_alias=True)
    for circle in model.circles:
        svg = render(model, focus=circle.name)
        for attributes in _elements(svg):
            assert attributes["data-jin-kind"] in DATA_JIN_KINDS
            assert pointer_exists(document, attributes["data-jin"]), attributes
            ref = attributes.get("data-jin-ref")
            if ref is not None:
                assert pointer_exists(document, ref), attributes


# --------------------------------------------------------------------------------------
# `jin run --trace` が書いた行を `jin render --trace` が読めること（F-C-P3-001 / F-S-P3-003）
# --------------------------------------------------------------------------------------
#: モデル出力に U+2028 を混ぜる台本。`jin run --model fake` には応答を渡す手段が無いので、
#: `jin_cli.main.FakeLlm` を差し替えて `app()` を呼ぶ（`test_cli_contract._scripted_run` と同じ手）。
_SCRIPTED_RUN = """
import sys
import jin_cli.main
from jin_adk.fake_llm import FakeLlm
jin_cli.main.FakeLlm = lambda: FakeLlm(responses=["a\u2028b\u2029c\u0085d"])
jin_cli.main.app(["run", sys.argv[1], "go", "--model", "fake", "--trace", sys.argv[2]])
"""


def _jin_with_separator_in_core(tmp_path: Path) -> Path:
    """`core` に U+2028 を混ぜた pipeline のコピー。

    `Ident` の検証（`jin_core.model._reject_bad_chars`）は C0 / C1 / DEL / 孤立サロゲートしか
    拒まないので U+2028 は通り、`jin check` も exit 0 になる。
    """
    model = json.loads((EXAMPLES / "pipeline" / "pipeline.jin").read_text(encoding="utf-8"))
    for circle in model["circles"]:
        if circle.get("core"):
            circle["core"] = circle["core"] + "\u2028x"
    target = tmp_path / "u2028.jin"
    target.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


@pytest.mark.parametrize("path", ["core", "output"])
def test_a_trace_written_by_jin_run_is_readable_by_jin_render(tmp_path: Path, path: str) -> None:
    """行区切り文字を含むトレースでも 2 つのコマンドが繋がること。

    `jin_adk.trace` は `json.dumps(..., ensure_ascii=False)` で書くので、U+2028 / U+2029 /
    U+0085 は**生のまま** JSONL に載る。読む側が `splitlines()` で割ると 1 行が 2〜4 行になり、
    正当なトレースが「JSON として読めません」で拒まれていた。パッケージ単体テストでは
    「writer が書いたもの」と「reader が読むもの」が同じ文字列であることを示せないので、
    ここで 2 プロセスを繋いで実測する。

    経路は 2 つ:

    - `core`: `.jin` の `core` に置く。トレースの `model` 行の `name` はこの `core` そのもの
      なので、**普通の `jin run` で**生の U+2028 が JSONL に載る
    - `output`: モデル出力に置く。`FakeLlm` の台本で 3 種の区切り文字を 1 度に混ぜられる

    R1 では `output` だけを試し、記録に「`core` 経由では `name` に載る経路が無い」と書いて
    いたが**これは誤りだった**（F-V-P3-103 / F-W-P3-105）。両方を回す。
    """
    trace = tmp_path / "live.jsonl"
    if path == "core":
        target = _jin_with_separator_in_core(tmp_path)
        assert (
            subprocess.run(
                [str(JIN), "check", str(target)],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        ), "core に U+2028 を入れた .jin が jin check を通らない（経路が塞がっている）"
        written = subprocess.run(
            [str(JIN), "run", str(target), "go", "--model", "fake", "--trace", str(trace)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env_with_stubs(),
            check=False,
        )
    else:
        target = EXAMPLES / "pipeline" / "pipeline.jin"
        written = subprocess.run(
            [sys.executable, "-P", "-c", _SCRIPTED_RUN, str(target), str(trace)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env_with_stubs(),
            check=False,
        )
    assert written.returncode == 0, written.stdout + written.stderr

    raw = trace.read_text(encoding="utf-8")
    assert "\u2028" in raw, f"{path}: U+2028 が生で載らない（テストが空虚になっている）"
    assert len(raw.splitlines()) > len(raw.split("\n")) - 1, (
        f"{path}: splitlines() と \\n 分割が同じ数（テストが空虚になっている）"
    )

    rendered = subprocess.run(
        [str(JIN), "render", str(target), "--trace", str(trace)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    assert rendered.stdout.startswith("<svg ")


# --------------------------------------------------------------------------------------
# 標準出力はロケールに依らず UTF-8（F-S-P3-010）
# --------------------------------------------------------------------------------------
def test_stdout_is_utf8_even_when_the_locale_cannot_encode_the_rune(tmp_path: Path) -> None:
    """`PYTHONIOENCODING=ascii` でも落ちず、`-o` の出力とバイト一致すること。

    researcher の rune は日本語なので、`sys.stdout.write` だと `UnicodeEncodeError` の
    トレースバックで exit 1 になる（Windows の cp932 コンソールでも同じ）。CliRunner の
    中では stdout が常に UTF-8 なので、この差は**別プロセスでしか測れない**。
    """
    target = EXAMPLES / "researcher" / "researcher.jin"
    written = tmp_path / "out.svg"
    assert (
        subprocess.run(
            [str(JIN), "render", str(target), "-o", str(written)],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )

    result = subprocess.run(
        [str(JIN), "render", str(target)],
        cwd=REPO_ROOT,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"Traceback" not in result.stderr
    assert result.stdout == written.read_bytes()
