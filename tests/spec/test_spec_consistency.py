"""docs/spec/*.md と examples/ が上位要件書と一致することを検証する突合テスト。

design.yaml implementation_phases.items[0].note が要求する Phase 0 の成果物。
これが無いと Phase 0 の完了条件が人間の目視だけになり、auto mode で検証不能になる。

上位要件書は jin-requirements.md（= docs/superpowers/specs/2026-09-04-jin-overview.md）。
docs/spec/*.md 側は `<!-- machine-readable: <ID> -->` マーカーで囲んだ Markdown 表を読む。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "jin-requirements.md"
SPEC_COPY = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-09-04-jin-overview.md"
SPEC_DIR = REPO_ROOT / "docs" / "spec"
EXAMPLES = REPO_ROOT / "examples"


# --------------------------------------------------------------------------------------
# 汎用パーサ
# --------------------------------------------------------------------------------------
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, start_heading: str, stop_pattern: str) -> str:
    """start_heading の行から stop_pattern にマッチする行の直前までを返す。"""
    lines = text.splitlines()
    out: list[str] = []
    started = False
    for line in lines:
        if not started:
            if line.startswith(start_heading):
                started = True
            continue
        if re.match(stop_pattern, line):
            break
        out.append(line)
    assert started, f"見出しが見つからない: {start_heading!r}"
    return "\n".join(out)


def table_rows(block: str) -> list[list[str]]:
    """Markdown 表の本体行（ヘッダと区切り行を除く）をセル配列で返す。"""
    rows: list[list[str]] = []
    seen_header = False
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue
        if all(set(c) <= {"-", ":"} and c for c in cells):
            continue
        rows.append(cells)
    return rows


def machine_block(path: Path, marker: str) -> str:
    """docs/spec/*.md の <!-- machine-readable: marker --> ブロックを返す。"""
    text = read(path)
    open_tag = f"<!-- machine-readable: {marker} -->"
    close_tag = "<!-- /machine-readable -->"
    assert open_tag in text, f"{path.name} にマーカー {marker} が無い"
    body = text.split(open_tag, 1)[1]
    assert close_tag in body, f"{path.name} のマーカー {marker} が閉じていない"
    return body.split(close_tag, 1)[0]


def first_code_span(cell: str) -> str:
    """セル中の最初の `...` を返す。無ければセルをそのまま返す。"""
    match = re.search(r"`([^`]+)`", cell)
    return match.group(1) if match else cell


# --------------------------------------------------------------------------------------
# 上位要件書から集合を取り出す
# --------------------------------------------------------------------------------------
def req_diagnostic_codes() -> list[str]:
    block = section(read(REQUIREMENTS), "### 2.4 静的意味制約", r"^各コードに fixture")
    return [row[0] for row in table_rows(block)]


def req_vocabulary_keys() -> list[str]:
    block = section(read(REQUIREMENTS), "### 2.1 語彙と ADK 対応", r"^circle は 2 種類")
    return [first_code_span(row[0]) for row in table_rows(block)]


def req_ops() -> list[str]:
    text = read(REQUIREMENTS)
    line = next(ln for ln in text.splitlines() if ln.startswith("オペレーション(v1):"))
    head = line.split("。各オペレーションは", 1)[0]
    return re.findall(r"`([A-Za-z]+)`", head)


def req_ring_radii() -> dict[str, str]:
    text = read(REQUIREMENTS)
    line = next(ln for ln in text.splitlines() if "環の半径は固定" in ln)
    return dict(re.findall(r"(instruction|tools|state|boundary) (\d\.\d+)", line))


def req_data_jin_kinds() -> list[str]:
    text = read(REQUIREMENTS)
    match = re.search(r'data-jin-kind="([^"]+)"', text)
    assert match, "要件書に data-jin-kind の値集合が無い"
    return match.group(1).split("|")


def req_example_json() -> list[dict]:
    """§2.2 に掲載された 2 つの ```json ブロックを返す。"""
    block = section(read(REQUIREMENTS), "### 2.2 ファイル形式", r"^形式上の決定事項")
    blocks = re.findall(r"```json\n(.*?)```", block, re.DOTALL)
    return [json.loads(b) for b in blocks]


# --------------------------------------------------------------------------------------
# 0. 要件書の 2 つの写しが同一
# --------------------------------------------------------------------------------------
def test_requirements_copies_are_identical() -> None:
    assert SPEC_COPY.exists(), "docs/superpowers/specs/2026-09-04-jin-overview.md が無い"
    assert read(REQUIREMENTS) == read(SPEC_COPY), (
        "jin-requirements.md と docs/superpowers/specs/2026-09-04-jin-overview.md が食い違っている。"
        "どちらが正典か分からなくなるので同一に保つこと"
    )


# --------------------------------------------------------------------------------------
# 1. diagnostics.md ↔ 要件書 §2.4（machine 条件 1）
# --------------------------------------------------------------------------------------
def test_diagnostics_canonical_matches_requirements() -> None:
    expected = req_diagnostic_codes()
    assert len(expected) == 14, f"要件書 §2.4 の行数が 14 でない: {len(expected)}"
    block = machine_block(SPEC_DIR / "diagnostics.md", "diagnostics-canonical")
    actual = [row[0] for row in table_rows(block)]
    assert actual == expected, (
        "diagnostics.md の正典コード表が要件書 §2.4 と一致しない\n"
        f"  diagnostics.md: {actual}\n  要件書 §2.4    : {expected}"
    )


def test_diagnostics_canonical_severity_matches_requirements() -> None:
    block = section(read(REQUIREMENTS), "### 2.4 静的意味制約", r"^各コードに fixture")
    expected = {row[0]: row[1] for row in table_rows(block)}
    actual_block = machine_block(SPEC_DIR / "diagnostics.md", "diagnostics-canonical")
    actual = {row[0]: row[1] for row in table_rows(actual_block)}
    assert actual == expected


def test_implementation_code_table_matches_requirements() -> None:
    """コード側の正典表が要件書 §2.4 と一致すること（重大度まで）。

    ADR-012 の承認で JIN012 / JIN013 が §2.4 に入り、承認待ちの別表は消えた。
    仕様側とコード側が同じ表を持つことをここで固定する。3 件目を勝手に採番すれば
    要件書 §2.4 との差として落ちる（旧 test_diagnostics_proposed_codes_are_exactly_two の役目）。
    """
    from jin_core.diagnostics import CANONICAL_CODES

    block = section(read(REQUIREMENTS), "### 2.4 静的意味制約", r"^各コードに fixture")
    expected = {row[0]: row[1] for row in table_rows(block)}
    assert dict(CANONICAL_CODES) == expected, (
        "jin_core.diagnostics.CANONICAL_CODES が要件書 §2.4 と一致しない\n"
        f"  CANONICAL_CODES: {dict(CANONICAL_CODES)}\n  要件書 §2.4     : {expected}"
    )


def test_diagnostics_md_has_no_separate_proposed_table() -> None:
    """承認済みコードを別表に残さない（表は §2 の 1 つだけ）。"""
    text = spec_text("diagnostics.md")
    assert "machine-readable: diagnostics-proposed" not in text
    assert "人間承認待ち" not in text


def test_diagnostic_stage_table_covers_all_codes() -> None:
    block = machine_block(SPEC_DIR / "diagnostics.md", "diagnostic-stages")
    listed: set[str] = set()
    for row in table_rows(block):
        listed |= set(re.findall(r"JIN\d{3}", row[2]))
    canonical = set(req_diagnostic_codes())
    assert listed == canonical, listed ^ canonical


def test_precedence_table_resolves_jin011_overlap() -> None:
    """要件書 §2.4 の JIN011 は steps / await / {key} を含むが、それぞれ専用コードがある。
    diagnostics.md がその優先順位を明記していること。"""
    block = machine_block(SPEC_DIR / "diagnostics.md", "diagnostic-precedence")
    rows = table_rows(block)
    wins = {row[1] for row in rows}
    assert {"JIN031", "JIN060", "JIN070", "JIN050", "JIN011"} <= wins


def test_position_base_is_declared() -> None:
    """lsp-api-probe.md §3 が要求する「基点を決めて根拠を残す」への対応が明文化されていること。"""
    block = machine_block(SPEC_DIR / "diagnostics.md", "position-base")
    decisions = {row[0]: row[1] for row in table_rows(block)}
    assert len(decisions) == 4
    assert all("1 始まり" in v or "排他" in v or "コードポイント" in v for v in decisions.values())


# --------------------------------------------------------------------------------------
# 2. ops.md ↔ 要件書 §6.3（machine 条件 2）
# --------------------------------------------------------------------------------------
def test_ops_match_requirements() -> None:
    expected = req_ops()
    assert len(expected) == 19, f"要件書 §6.3 のオペレーションが 19 件でない: {len(expected)}"
    block = machine_block(SPEC_DIR / "ops.md", "ops-list")
    actual = [first_code_span(row[0]) for row in table_rows(block)]
    assert actual == expected, f"\n  ops.md : {actual}\n  要件書 : {expected}"


# --------------------------------------------------------------------------------------
# 3. layout.md ↔ 要件書 §2.5（machine 条件 3 / 4）
# --------------------------------------------------------------------------------------
def test_ring_radii_match_requirements() -> None:
    expected = req_ring_radii()
    assert expected == {
        "instruction": "0.35",
        "tools": "0.55",
        "state": "0.75",
        "boundary": "0.95",
    }
    block = machine_block(SPEC_DIR / "layout.md", "ring-radii")
    actual = {row[0]: row[1] for row in table_rows(block)}
    assert actual == expected


def test_data_jin_kinds_match_requirements() -> None:
    expected = req_data_jin_kinds()
    assert len(expected) == 9, f"要件書 §2.5 の data-jin-kind が 9 種でない: {len(expected)}"
    block = machine_block(SPEC_DIR / "layout.md", "data-jin-kinds")
    actual = [first_code_span(row[0]) for row in table_rows(block)]
    assert actual == expected


# --------------------------------------------------------------------------------------
# 4. adk-mapping.md ↔ 要件書 §2.1（machine 条件 5）
# --------------------------------------------------------------------------------------
def test_adk_vocabulary_matches_requirements() -> None:
    expected = req_vocabulary_keys()
    block = machine_block(SPEC_DIR / "adk-mapping.md", "adk-vocabulary")
    actual = [first_code_span(row[0]) for row in table_rows(block)]
    assert actual == expected, f"\n  adk-mapping.md: {actual}\n  要件書 §2.1   : {expected}"


def test_adk_vocabulary_row_count_is_twelve_not_eleven() -> None:
    """design.yaml の machine 条件は「11 行」と書いているが、要件書 §2.1 と
    requirements.json FR-MODEL-002.vocabulary[] はいずれも 12 行である。
    上流 2 系統が一致しているほうを正とし、design.yaml 側の件数を転記誤りとして扱う。
    この事実をテストで固定し、後から「11 が正しかった」と静かに書き換えられないようにする。"""
    assert len(req_vocabulary_keys()) == 12


# --------------------------------------------------------------------------------------
# 5. examples ↔ 要件書 §2.2（machine 条件 6）
# --------------------------------------------------------------------------------------
EXAMPLE_FILES = [
    EXAMPLES / "researcher" / "researcher.jin",
    EXAMPLES / "pipeline" / "pipeline.jin",
]


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_is_valid_json(path: Path) -> None:
    json.loads(read(path))


def test_examples_match_requirements_section_2_2() -> None:
    """この時点（Phase 0）では Pydantic 検証が存在しないため素の JSON 比較で突合する。"""
    expected = req_example_json()
    assert len(expected) == 2
    actual = [json.loads(read(p)) for p in EXAMPLE_FILES]
    assert actual == expected


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_ends_with_single_newline(path: Path) -> None:
    raw = path.read_bytes()
    assert raw.endswith(b"}\n") and not raw.endswith(b"}\n\n")


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_is_not_ascii_escaped(path: Path) -> None:
    """正準形の規則 5（非 ASCII はエスケープしない）を examples でも守る。"""
    assert "\\u" not in read(path)


# --------------------------------------------------------------------------------------
# 6. spec 文書の存在（FR-DOC-001）
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name", ["model.md", "adk-mapping.md", "layout.md", "diagnostics.md", "ops.md"]
)
def test_spec_document_exists(name: str) -> None:
    assert (SPEC_DIR / name).exists()


# ======================================================================================
# 修正ラウンド 1: 仕様書側の誤り（S-1 〜 S-6）を検出できるようにする
# ======================================================================================
def spec_text(name: str) -> str:
    return read(SPEC_DIR / name)


# ---- S-1: 逆オペレーションの復元条件が仕様に書かれている ---------------------------------
def test_ops_declare_the_restore_contract() -> None:
    """S-1: §1 の「クライアントが逆 op 列を保持して undo する」を成立させる条件を明記する。

    修正前の §2 は `toggleAwait`（配列順が戻らない）と `setGuard`（boundary を消す責務が無い）の
    **復元不能を仕様として追認**していた。
    """
    text = spec_text("ops.md")
    assert "バイト一致" in text, "§1 に「逆適用でバイト一致」の契約が無い"


def test_ops_restore_conditions_table_covers_both_operations() -> None:
    """S-1: 復元条件は表（機械可読）で持つ。実装の引数名と対応づける。"""
    rows = table_rows(machine_block(SPEC_DIR / "ops.md", "ops-restore-conditions"))
    pairs = {(first_code_span(row[0]), first_code_span(row[2])) for row in rows}
    # 「どのオペレーションが / 何を運んで復元するか」を 3 つ組で固定する。
    # 集合どうしの比較にすると、片方の行を消しても別の行が肩代わりして通ってしまう。
    assert ("toggleAwait", "index") in pairs, pairs
    assert ("toggleAwait", "pruneBoundary") in pairs, pairs
    assert ("setGuard", "pruneBoundary") in pairs, pairs


def test_ops_restore_arguments_exist_in_the_implementation() -> None:
    """S-1: 仕様が挙げた引数名が実装に実在すること（仕様だけ直して終わりにしない）。"""
    from jin_core import ops as ops_module

    source = Path(ops_module.__file__).read_text(encoding="utf-8")
    rows = table_rows(machine_block(SPEC_DIR / "ops.md", "ops-restore-conditions"))
    for row in rows:
        argument = first_code_span(row[2])
        assert f'"{argument}"' in source, f"ops.py に {argument!r} が無い"


def test_ops_list_mentions_the_restore_conditions() -> None:
    """S-1: §2 の逆オペレーション欄が §2.1 を指していること。"""
    rows = table_rows(machine_block(SPEC_DIR / "ops.md", "ops-list"))
    inverse = {first_code_span(row[0]): row[3] for row in rows}
    assert "§2.1" in inverse["toggleAwait"], inverse["toggleAwait"]
    assert "§2.1" in inverse["setGuard"], inverse["setGuard"]


# ---- S-2: 優先順位表に flow.exit.key がある ---------------------------------------------
def test_precedence_table_covers_flow_exit_key() -> None:
    """S-2: `rename` が `flow.exit.key` を参照として追随させている以上、未解決時のコードも決める。"""
    rows = table_rows(machine_block(SPEC_DIR / "diagnostics.md", "diagnostic-precedence"))
    situations = {row[0]: row[1] for row in rows}
    matched = [code for situation, code in situations.items() if "exit.key" in situation]
    assert matched == ["JIN011"], situations


def test_every_reference_in_rename_cascade_has_a_diagnostic_rule() -> None:
    """S-2 の一般化: rename が追随させる参照は、すべて優先順位表に現れること。

    「追随させるが未解決を報告しない」参照があると、システム内で
    「参照かどうか」の扱いが一貫しない。
    """
    cascade = table_rows(machine_block(SPEC_DIR / "ops.md", "rename-cascade"))
    precedence = table_rows(machine_block(SPEC_DIR / "diagnostics.md", "diagnostic-precedence"))
    situations = " / ".join(row[0] for row in precedence)
    references = re.findall(r"`([A-Za-z_.\[\]{}]+)`", " ".join(row[1] for row in cascade))
    interesting = {r for r in references if "." in r or "[]" in r}
    missing = [
        reference
        for reference in sorted(interesting)
        if reference.rstrip("[]").split(".")[-1] not in situations
    ]
    assert missing == [], f"優先順位表に規則が無い参照: {missing}"


# ---- S-3: max / exit をどの段で落とすかが書かれている ------------------------------------
def test_model_says_where_loop_only_keys_are_rejected() -> None:
    """S-3: 「loop のみ」と書くだけでは、どこで落ちるかが決まらない。"""
    text = spec_text("model.md")
    block = section(text, "### 3.4 Flow", r"^### 3\.5")
    assert "JIN002" in block, "§3.4 に max / exit を落とす診断コードが無い"
    assert "段 2" in block, "§3.4 に max / exit を落とす段が書かれていない"


def test_loop_only_rule_is_enforced_by_the_model() -> None:
    """S-3: 仕様が「段 2 で落とす」と言うなら、実際に段 2 で落ちること。"""
    from jin_core.check import check_text

    document = json.dumps(
        {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "A",
            "circles": [
                {"name": "A", "flow": {"kind": "sequence", "steps": ["B"], "max": 2}},
                {"name": "B", "core": "m"},
            ],
        }
    )
    assert [d.code for d in check_text(document, "t.jin").diagnostics] == ["JIN002"]


# ---- S-4: pointer の一意性が重複キーで崩れない -------------------------------------------
def test_model_states_that_a_pointer_denotes_one_value() -> None:
    """S-4: 重複キーを許すと「pointer は唯一の鍵」が成り立たない。"""
    block = section(spec_text("model.md"), "## 6. JSON Pointer", r"^## 7\.")
    assert "重複キー" in block, "§6 に重複キーの扱いが無い"
    assert "JIN001" in block, "§6 に重複キーを落とすコードが無い"


def test_duplicate_keys_are_actually_rejected() -> None:
    """S-4: 仕様の主張どおりに実装が落とすこと。"""
    from jin_core.check import check_text

    result = check_text('{"a": 1, "a": 2}', "t.jin")
    assert [d.code for d in result.diagnostics] == ["JIN001"]


# ---- S-5: ADK 側のエスケープを実測なしに断定しない ----------------------------------------
def test_rune_escape_claim_is_marked_unverified_without_probe_evidence() -> None:
    """S-5: `adk-api-probe.md` にエスケープの実測が無い間は「未確認」と明記すること（T-002）。

    実測が入ったらこのテストが赤くなるので、そのとき §3.1 を実測に置き換える。
    """
    probe = REPO_ROOT / "delivery" / "20260904-1445-jin" / "adk-api-probe.md"
    has_evidence = probe.is_file() and re.search(r"\{\{.*\}\}|エスケープ", read(probe)) is not None
    block = section(spec_text("model.md"), "### 3.1 Instruction", r"^### 3\.2")
    if has_evidence:
        pytest.fail(
            "adk-api-probe.md にエスケープの実測が入った。model.md §3.1 を実測へ置き換えること"
        )
    assert "未確認" in block, "§3.1 に「未確認」の明記が無い（証拠なく断定しない・T-002）"


def test_rune_escape_rule_matches_the_implementation() -> None:
    """S-5 の Jin 側: 仕様が挙げた `"{a}}"` の読みが実装と一致すること。"""
    from jin_core.semantic import rune_keys

    block = section(spec_text("model.md"), "### 3.1 Instruction", r"^### 3\.2")
    assert '"{a}}"' in block
    assert rune_keys("{a}}") == ["a"]


# ---- S-6: 星形多角形の根拠の説明 ----------------------------------------------------------
def test_star_polygon_example_explains_n6_correctly() -> None:
    """S-6: 結論 k=1 は正しいが、「2 と 3 は gcd≠1」は誤り（3 は探索範囲外）。"""
    text = spec_text("layout.md")
    assert "2 と 3 は gcd≠1" not in text, "誤った根拠が残っている"
    assert "探索範囲に入らない" in text


@pytest.mark.parametrize(
    ("n", "expected"), [(5, 2), (6, 1), (7, 3), (8, 3), (9, 4), (10, 3), (12, 5)]
)
def test_star_polygon_step_matches_the_declared_formula(n: int, expected: int) -> None:
    """S-6: 例の値そのものを式から計算して突き合わせる（説明文だけの確認にしない）。"""
    from math import gcd

    computed = max(j for j in range(1, n) if 2 * j < n and gcd(n, j) == 1)
    assert computed == expected


def test_star_polygon_examples_in_the_spec_are_all_correct() -> None:
    """仕様に書かれた例の並びを読み取って検算する。"""
    from math import gcd

    text = spec_text("layout.md")
    line = next(ln for ln in text.splitlines() if ln.startswith("例: n=5"))
    for n_text, k_text in re.findall(r"n=(\d+) → k=(\d+)", line):
        n, k = int(n_text), int(k_text)
        assert k == max(j for j in range(1, n) if 2 * j < n and gcd(n, j) == 1), f"n={n}"


# ---- ADR-014: machine-readable: upstream-rule に消費者を与える ---------------------------
def test_upstream_rule_table_declares_the_loop_scope() -> None:
    """ADR-014（DP-JIN-JIN050-LOOP-SCOPE-01）は現仕様の維持を決めた。

    その代わり、この表に**テストという消費者**を与えて内容を固定する
    （修正前はこのマーカーを読むテストが 0 件だった）。
    """
    rows = table_rows(machine_block(SPEC_DIR / "model.md", "upstream-rule"))
    scopes = {row[0]: row[1] for row in rows}
    assert len(scopes) >= 4

    loop = next(k for k in scopes if "loop" in k)
    assert "すべて" in loop, loop
    assert scopes[loop] == "含める", scopes[loop]

    sequence = next(k for k in scopes if "sequence" in k)
    assert "前" in sequence, sequence
    assert scopes[sequence] == "含める", scopes[sequence]

    parallel = next(k for k in scopes if "parallel" in k)
    assert scopes[parallel] == "含めない", scopes[parallel]


def test_upstream_rule_matches_the_implementation() -> None:
    """ADR-014: 表の内容が `jin_core.semantic` の可視範囲と一致すること。"""
    from jin_core.check import check_text

    def document(kind: str) -> str:
        return json.dumps(
            {
                "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
                "version": 1,
                "root": "P",
                "circles": [
                    {
                        "name": "P",
                        "flow": {
                            "kind": kind,
                            "steps": ["X", "Y"],
                            **({"max": 2} if kind == "loop" else {}),
                        },
                    },
                    {"name": "X", "core": "m", "instruction": {"rune": "{later}"}},
                    {
                        "name": "Y",
                        "core": "m",
                        "state": [{"name": "later", "type": "str", "out": True}],
                    },
                ],
            }
        )

    # loop: すべての兄弟枝が見えるので、後ろの兄弟が作る state を読んでよい。
    assert [d.code for d in check_text(document("loop"), "t.jin").diagnostics] == []
    # sequence: 先行する兄弟枝のみ。後ろは見えない。
    assert [d.code for d in check_text(document("sequence"), "t.jin").diagnostics] == ["JIN050"]
    # parallel: 兄弟は見えない。
    assert [d.code for d in check_text(document("parallel"), "t.jin").diagnostics] == ["JIN050"]


# ---- CONV C-1 / S14: 成果物の記述が実装と一致する ----------------------------------------
DELIVERY = REPO_ROOT / "delivery" / "20260904-1445-jin"


def test_version_matrix_points_at_the_real_grammar_location() -> None:
    """CONV C-1: `version-matrix.md` が実在しないファイルを「自作した」と記録していた。

    この文書は後続ラウンドの実装者が最初に読む依存情報の正本なので、所在の誤記は
    Phase 4 で存在しないパスを探すことにつながる。
    """
    text = (DELIVERY / "version-matrix.md").read_text(encoding="utf-8")
    assert "jin_json.lark" not in text, "実在しない .lark ファイルの記述が残っている"
    assert "JIN_JSON_GRAMMAR" in text
    assert not list((REPO_ROOT / "packages").rglob("*.lark")), ".lark ファイルは作っていないはず"

    from jin_core import parser

    assert hasattr(parser, "JIN_JSON_GRAMMAR")


def test_decision_conformance_does_not_claim_jin_core_imports() -> None:
    """S14: DP-COMMON-07「jin_core は状態を持たない純関数」の記述が実態と乖離していた。

    実態（import 実装が jin_cli にしか無い）と対照表の記述が同時に真であることを見る。
    """
    text = (DELIVERY / "decision-conformance.md").read_text(encoding="utf-8")
    assert "DP-COMMON-07" in text
    assert "jin_cli.resolver.ImportResolver" in text, "S14 の訂正が入っていない"

    core = REPO_ROOT / "packages" / "jin-core" / "src" / "jin_core"
    for path in sorted(core.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("import importlib", "from importlib")), (
                f"{path}: {line}"
            )


# ======================================================================================
# 修正ラウンド 2: 実装に足した制約を正典にも書く（correctness review N-2 / N-3）
# ======================================================================================
def test_string_constraints_table_matches_the_implementation() -> None:
    """N-2: S13 で `model.py` に入れた制約が `model.md` に書かれていなかった。

    表の値と実装の定数を突き合わせる（import して比べるのでドリフトしようがない）。
    """
    from jin_core.model import MAX_IDENT_LENGTH, MAX_TEXT_LENGTH, MAX_URL_LENGTH

    rows = table_rows(machine_block(SPEC_DIR / "model.md", "string-constraints"))
    limits = {row[0]: int(row[2]) for row in rows}
    assert limits == {
        "識別子": MAX_IDENT_LENGTH,
        "自由記述": MAX_TEXT_LENGTH,
        "URL": MAX_URL_LENGTH,
    }, limits


def test_string_constraints_table_lists_every_string_field() -> None:
    """N-2: 表に載っていないフィールドがあると「どの制約が効くか」が読み取れない。

    `jin_core.model` の全モデルの文字列フィールドを走査し、表のどこかに現れることを見る。
    """
    import jin_core.model as model_module
    from pydantic import BaseModel

    rows = table_rows(machine_block(SPEC_DIR / "model.md", "string-constraints"))
    listed = " ".join(row[1] for row in rows)
    missing: list[str] = []
    for name in dir(model_module):
        cls = getattr(model_module, name)
        if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
            continue
        for field_name, info in cls.model_fields.items():
            alias = info.alias or field_name
            if alias in {"kind", "on", "version"}:
                continue  # Literal（値集合が固定）なので長さ制約の対象外
            if "str" not in str(info.annotation):
                continue
            if alias not in listed:
                missing.append(f"{cls.__name__}.{alias}")
    assert missing == [], f"model.md §3.6 の表に無い文字列フィールド: {sorted(set(missing))}"


def test_control_character_rule_is_stated_in_the_spec() -> None:
    """N-2: 制御文字と孤立サロゲートの扱いが正典に書かれていること。"""
    block = section(spec_text("model.md"), "### 3.6 文字列の制約", r"^### 3\.7")
    assert "孤立サロゲート" in block
    assert "JIN002" in block
    assert "段 2" in block


def test_canonical_section_reconciles_the_writer_with_the_accepted_range() -> None:
    """N-2: §7 が「モデルが受け付けない文字の書き出し規則」を正典として書いたままだった。

    writer の規則は残す（`dumps` を直接呼ぶ経路のため）が、
    受理範囲との関係を明記して矛盾を解く。
    """
    block = section(spec_text("model.md"), "## 7. 正準形", r"^## 8\.")
    assert "受理範囲との関係" in block
    assert "§3.6" in block
    assert "孤立サロゲート" in block


def test_diagnostics_notes_what_jin002_covers() -> None:
    """N-2: diagnostics.md 側にも段 2 の守備範囲を書く。"""
    text = spec_text("diagnostics.md")
    assert "§3.6" in text
    assert "文字列の制約" in text


# ---- N-3: 公開スキーマが表現しない制約 ---------------------------------------------------
def test_schema_gaps_table_exists_and_names_the_detector() -> None:
    """N-3: 公開スキーマが実際の受け入れ条件より緩いことを明記する。

    要件書 §0 成功条件 3 は「Claude Code が JSON Schema と診断の出力だけで直しきれる」ことを
    求めており、緩いまま黙っていると LLM がスキーマ的に妥当な `.jin` を書いて `jin check` で落ちる。
    """
    rows = table_rows(machine_block(SPEC_DIR / "model.md", "schema-gaps"))
    assert len(rows) >= 5
    for row in rows:
        assert re.search(r"JIN\d{3}", row[1]), row
        assert row[2] in {"段 1", "段 2", "段 3"}, row


def test_generated_schema_really_lacks_the_conditional_constraints() -> None:
    """N-3: 「表現できない」という主張が現物と一致すること。

    ここが赤くなったら、スキーマが表現できるようになったということなので
    §3.7 の表を見直す（捏造した `pattern` を足していないことの確認でもある）。
    """
    from jin_core.schema_export import build_schema

    schema = build_schema()
    flow = schema["$defs"]["Flow"]
    assert "if" not in flow and "allOf" not in flow, flow
    # 識別子・自由記述・URL は `AfterValidator` で検査しているので、Pydantic は正規表現を
    # 出力できない。ここでは**その 3 種の文字列型**に限って pattern の不在を見る。
    # スキーマ全体から pattern を禁じると、将来 `StringConstraints(pattern=...)` を正当に
    # 使ったときに「捏造の疑い」という誤った文言で落ちる。
    for name, definition in schema.get("$defs", {}).items():
        for field, spec in definition.get("properties", {}).items():
            if "maxLength" in spec:
                assert "pattern" not in spec, (
                    f"$defs.{name}.{field} に pattern が現れた。"
                    "検査が正規表現で表現できるようになったなら model.md §3.7 の表を更新すること"
                )
    text = json.dumps(schema, ensure_ascii=False)
    assert '"maxLength"' in text, "maxLength は出るはず（S13）"


def test_schema_gaps_are_consistent_with_the_diagnostic_tables() -> None:
    """N-3: §3.7 が挙げるコードが、実在する診断コードであること。"""
    from jin_core.diagnostics import CANONICAL_CODES

    rows = table_rows(machine_block(SPEC_DIR / "model.md", "schema-gaps"))
    for row in rows:
        for code in re.findall(r"JIN\d{3}", row[1]):
            assert code in CANONICAL_CODES, f"{code} は診断コード表に無い"
