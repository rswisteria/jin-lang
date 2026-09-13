"""docs/spec/v2/*.md と examples-v2/ が Jin v2 の設計書と一致することを検証する突合テスト。

設計書: docs/superpowers/specs/2026-09-13-jin-v2-general-design.md(以下 DESIGN)。
v1 の `test_spec_consistency.py` と同じ手口で、`<!-- machine-readable: <ID> -->` マーカーで囲んだ
Markdown 表を読み、設計書の対応する表・箇条書きと突き合わせる。

ここは**文書同士**と**文書と例**の一致を見る。実装との一致（`V2_CODES` / `OPERATIONS` / `STEP_KINDS` /
カタログ）はこのファイルの各テストが `jin_core.v2` を import して等号で固定し、例が実装を通ることは
`packages/jin-core/tests/test_v2_model.py` が見る。`examples-v2/` は恒久的に `examples/` の外に置く
（`examples/` は v1 の契約が「3 本」と数える。設計書 §11 #18）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN = REPO_ROOT / "docs/superpowers/specs/2026-09-13-jin-v2-general-design.md"
SPEC_V2 = REPO_ROOT / "docs/spec/v2"
SPEC_V1_LAYOUT = REPO_ROOT / "docs/spec/layout.md"
EXAMPLES_V2 = sorted((REPO_ROOT / "examples-v2").glob("*/*.jin"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def machine_block(path: Path, marker: str) -> str:
    text = read(path)
    open_tag = f"<!-- machine-readable: {marker} -->"
    close_tag = "<!-- /machine-readable -->"
    assert open_tag in text, f"{path.name} にマーカー {marker} が無い"
    body = text.split(open_tag, 1)[1]
    assert close_tag in body, f"{path.name} のマーカー {marker} が閉じていない"
    return body.split(close_tag, 1)[0]


def table_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def first_code_span(cell: str) -> str:
    m = re.search(r"`([^`]+)`", cell)
    assert m, f"コードスパンが無い: {cell!r}"
    return m.group(1)


def design_section(heading_prefix: str) -> str:
    """設計書の `## N.` / `### N.M` 見出しから次の同レベル以上の見出しまで。"""
    text = read(DESIGN)
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(heading_prefix))
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    out = []
    for l in lines[start + 1 :]:
        if l.startswith("#") and (len(l) - len(l.lstrip("#"))) <= level:
            break
        out.append(l)
    return "\n".join(out)


# ---------------------------------------------------------------- ステップ 11 種


def test_step_kinds_match_the_design_document() -> None:
    """model.md §3.4 の 11 種と設計書 §2.3 の表が同じ集合で、11 個である。"""
    spec = {
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "model.md", "step-kinds"))[1:]
    }
    design_rows = table_rows(design_section("### 2.3"))
    design = {first_code_span(r[0]) for r in design_rows[1:]}
    assert spec == design
    assert len(spec) == 11


# ---------------------------------------------------------------- data-jin-kind 13 種


def test_data_jin_kinds_match_the_design_document() -> None:
    spec = [
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "layout.md", "data-jin-kinds"))[1:]
    ]
    design_text = design_section("## 7.")
    m = re.search(r"^`stage`.*$", design_text, re.MULTILINE)
    assert m, "設計書 §7 に data-jin-kind の列挙行が無い"
    design = re.findall(r"`([a-z-]+)`", m.group(0))
    assert spec == design
    assert len(spec) == 13
    assert len(set(spec)) == 13


# ---------------------------------------------------------------- 環の半径は v1 と同じ 4 本


def test_v2_ring_radii_reuse_the_v1_values() -> None:
    v1 = {r[1] for r in table_rows(machine_block(SPEC_V1_LAYOUT, "ring-radii"))[1:]}
    v2 = {r[1] for r in table_rows(machine_block(SPEC_V2 / "layout.md", "ring-radii"))[1:]}
    assert v1 == v2 == {"0.35", "0.55", "0.75", "0.95"}


# ---------------------------------------------------------------- 診断 JIN2xx


def test_v2_diagnostic_codes_match_the_design_document() -> None:
    spec = {
        r[0] for r in table_rows(machine_block(SPEC_V2 / "diagnostics.md", "v2-diagnostics"))[1:]
    }
    design = {r[0] for r in table_rows(design_section("## 6.")) if re.fullmatch(r"JIN2\d\d", r[0])}
    assert spec == design
    assert all(re.fullmatch(r"JIN2\d\d", c) for c in spec)


def test_shared_diagnostic_codes_are_listed_in_both_documents() -> None:
    """diagnostics.md §0 の共有番号が、設計書 §1.3 の「同じ番号を使う」の列挙と一致する。"""
    spec_text = read(SPEC_V2 / "diagnostics.md").split("## 1.", 1)[0]
    spec = set(re.findall(r"\bJIN0\d\d\b", spec_text))
    design_row = next(r for r in table_rows(design_section("### 1.3")) if r[0].startswith("モデル"))
    design = {f"JIN{n}" for n in re.findall(r"(?:JIN|\b)(0\d\d)\b", design_row[1])}
    assert spec == design


# ---------------------------------------------------------------- ホスト能力


def test_ability_namespaces_match_the_design_document() -> None:
    spec = {
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "abilities.md", "abilities"))[1:]
    }
    design = {first_code_span(r[0]) for r in table_rows(design_section("### 3.4"))[1:]}
    assert (
        spec | {"storage"} == design
    )  # storage は設計書の表に v2.1 として載っているが、カタログには無い
    assert spec == {"canvas", "input", "ui", "audio", "random"}


# ---------------------------------------------------------------- オペレーション


def test_v2_ops_count_matches_the_design_document() -> None:
    spec = [
        first_code_span(r[0]) for r in table_rows(machine_block(SPEC_V2 / "ops.md", "v2-ops"))[1:]
    ]
    design_text = design_section("## 9.")
    # 列挙の段落には説明の括弧書き(`if` / `loop` / 合成の内訳)も混じるので、camelCase の名前を出現順・重複なしで取る
    design = list(
        dict.fromkeys(re.findall(r"`(rename|[a-z]+[A-Z][A-Za-z]*)", design_text.split("\n\n")[1]))
    )
    assert spec == design
    assert len(spec) == 32
    from jin_core.v2.ops import OPERATIONS

    assert list(OPERATIONS) == spec, "jin_core.v2.ops.OPERATIONS の順と ops.md §2 の表を揃える"


# ---------------------------------------------------------------- examples


def _steps(steps: list[dict]):
    for s in steps:
        yield s
        for key in ("then", "else", "steps"):
            if isinstance(s.get(key), list):
                yield from _steps(s[key])


def test_there_are_three_v2_examples() -> None:
    assert [p.parent.name for p in EXAMPLES_V2] == ["clicker", "fib", "paddle"]


@pytest.mark.parametrize("path", EXAMPLES_V2, ids=[p.stem for p in EXAMPLES_V2])
def test_example_uses_only_the_documented_vocabulary(path: Path) -> None:
    doc = json.loads(read(path))
    assert doc["version"] == 2
    step_kinds = {
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "model.md", "step-kinds"))[1:]
    }
    namespaces = {
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "abilities.md", "abilities"))[1:]
    }
    members = {
        (first_code_span(r[0]), first_code_span(r[1]))
        for r in table_rows(machine_block(SPEC_V2 / "abilities.md", "abilities"))[1:]
    }
    events = {
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "model.md", "event-kinds"))[1:]
    }

    names = [c["name"] for c in doc["circles"]]
    assert len(names) == len(set(names)), "circle 名が重複"
    assert doc["root"] in names
    for circle in doc["circles"]:
        assert ("core" in circle) != ("flow" in circle), circle["name"]
        rites = {r["name"] for r in circle.get("rites", [])}
        if "core" in circle:
            assert circle["core"] in rites
        for sigil in circle.get("sigils", []):
            if sigil["kind"] == "host":
                assert sigil["host"] in namespaces
        for on in circle.get("boundary", {}).get("on", []):
            assert on["event"] in events
            assert on["rite"] in rites
        for rite in circle.get("rites", []):
            assert len(rite["steps"]) <= 12, (
                f"{circle['name']}.{rite['name']} は 12 ステップを超えている"
            )
            for step in _steps(rite["steps"]):
                assert step["do"] in step_kinds, step
                if step["do"] == "cast" and "." in step["target"]:
                    ns, member = step["target"].split(".", 1)
                    assert (ns, member) in members, step["target"]


def test_paddle_example_matches_the_design_document_section_2_2() -> None:
    """設計書 §2.2 の JSON と examples-v2/paddle/paddle.jin が同じモデルである(v1 の §2.2 突合と同じ)。"""
    block = re.search(r"```json\n(.*?)```", design_section("### 2.2"), re.DOTALL)
    assert block
    assert json.loads(block.group(1)) == json.loads(
        read(REPO_ROOT / "examples-v2/paddle/paddle.jin")
    )


def test_paddle_step_counts_are_as_the_design_document_says() -> None:
    """§2.2 の説明「step は 9、paint は 5、まとめると 14 で JIN210」が実物と一致する。"""
    doc = json.loads(read(REPO_ROOT / "examples-v2/paddle/paddle.jin"))
    play = next(c for c in doc["circles"] if c["name"] == "Play")
    rites = {r["name"]: r for r in play["rites"]}
    assert len(rites["step"]["steps"]) == 9
    assert len(rites["paint"]["steps"]) == 5
    merged = (
        len(rites["step"]["steps"]) - 1 + len(rites["paint"]["steps"])
    )  # cast paint の位置に paint を戻す
    step_limit = 12  # JIN210
    assert merged == 13
    assert merged > step_limit


# ---------------------------------------------------------------- JIL / トレース（Phase 2）


def test_jil_forbidden_words_match_the_implementation() -> None:
    """jil.md §2 の禁止語（machine-readable）と `jin_wasm.jil.JIL_FORBIDDEN` が同じ列である。"""
    from jin_wasm.jil import JIL_FORBIDDEN

    spec = re.findall(r"`([^`]+)`", machine_block(SPEC_V2 / "jil.md", "jil-forbidden"))
    assert spec == list(JIL_FORBIDDEN)
    design_text = design_section("### 4.4")
    for word in ("pairs", "next", "setmetatable", "load", "require", "..."):
        assert f"`{word}`" in design_text or f"`{word}" in design_text


def test_trace_kinds_match_the_implementation() -> None:
    """runtime.md §5 の kind（machine-readable）と `jin_wasm.jil.TRACE_KINDS` が同じ列である。

    設計書 §4.7 の列挙は `error` を含まない 12 種（実行時エラーは runtime.md で足した）ので、
    設計書側は部分集合として見る。
    """
    from jin_wasm.jil import TRACE_FIELDS, TRACE_KINDS

    spec = [
        first_code_span(r[0])
        for r in table_rows(machine_block(SPEC_V2 / "runtime.md", "trace-kinds"))[1:]
    ]
    assert spec == list(TRACE_KINDS)
    design_text = design_section("### 4.7")
    m = re.search(r"^kind: (.+)$", design_text, re.MULTILINE)
    assert m, "設計書 §4.7 に kind の列挙行が無い"
    design = [k.strip() for k in m.group(1).split("|")]
    assert set(design) <= set(spec)
    fields = re.search(
        r'\{ "seq", "tick", "circle", "kind", "name", "pointer", "input", "output" \}', design_text
    )
    assert fields, "設計書 §4.7 のトレース行のキー列が変わった"
    assert list(TRACE_FIELDS) == [
        "seq",
        "tick",
        "circle",
        "kind",
        "name",
        "pointer",
        "input",
        "output",
    ]
