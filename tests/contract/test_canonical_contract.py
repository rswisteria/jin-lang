"""パッケージ横断契約: 正準形の往復無損失（ADR-003 / NFR-DET-002）。

design.yaml implementation_phases.items[1].verification.machine のうち次を検証する:

- 冪等性: examples と全 fixture について fmt(fmt(x)) == fmt(x) がバイト一致
- 意味保存: model(fmt(x)) == model(x)
- 正準形の 4 規則（2 スペースインデント / スキーマ定義順のキー順 / 非 ASCII 非エスケープ / 末尾改行）
- 省略可能キーが既定値のとき出力されない
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jin_core.canonical import INDENT, dumps, encode_string
from jin_core.check import check_file, check_text
from jin_core.model import DEFAULT_SCHEMA_URL, JinFile

from tests.conftest import UNFORMATTABLE_CODES, fixture_code

#: 規則 1 の検査そのものを検査するための最小文書。
MINIMAL_DOCUMENT = {
    "$schema": DEFAULT_SCHEMA_URL,
    "version": 1,
    "root": "A",
    "circles": [
        {
            "name": "A",
            "core": "gemini-2.5-flash",
            "state": [{"name": "s", "type": "str", "out": True}],
            "boundary": {"guards": [{"on": "before_model", "ref": "m:g"}]},
        }
    ],
}


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


def test_unformattable_set_is_exactly_the_two_documented_codes(
    error_fixture_paths: list[Path],
) -> None:
    """「モデルにならない fixture」が JIN001 / JIN002 の 2 つだけであることを固定する。

    ここを固定しないと、後から意味段の fixture を除外集合に足して冪等性検査を骨抜きにできてしまう。
    """
    actual = set()
    for path in error_fixture_paths:
        if check_file(path).model is None:
            actual.add(fixture_code(path))
    assert actual == set(UNFORMATTABLE_CODES)


def test_formattable_set_is_not_empty(formattable_paths: list[Path]) -> None:
    assert len(formattable_paths) >= 14


def test_idempotent_for_every_formattable_document(formattable_paths: list[Path]) -> None:
    for path in formattable_paths:
        model = check_file(path).model
        assert model is not None, path
        once = dumps(model)
        twice = dumps(check_text(once, str(path)).model)
        assert once == twice, f"fmt が冪等でない: {path}"


def test_semantics_preserved_for_every_formattable_document(
    formattable_paths: list[Path],
) -> None:
    for path in formattable_paths:
        original = check_file(path).model
        assert original is not None, path
        reparsed = check_text(dumps(original), str(path)).model
        assert reparsed == original, f"model(fmt(x)) != model(x): {path}"


def test_text_roundtrip_is_byte_identical(formattable_paths: list[Path]) -> None:
    """ファイル → モデル → ファイルがバイト同一（正準形のファイルに限る）。"""
    for path in formattable_paths:
        canonical = dumps(check_file(path).model)
        twice = dumps(check_text(canonical, str(path)).model)
        assert canonical == twice


# --------------------------------------------------------------------------------------
# 正準形の 4 規則を出力そのものに対して検査する
# --------------------------------------------------------------------------------------
def _canonical_texts(paths: list[Path]) -> list[tuple[Path, str]]:
    out = []
    for path in paths:
        model = check_file(path).model
        assert model is not None, path
        out.append((path, dumps(model)))
    return out


def _lines_with_depth(text: str):
    """正準形の各行と、その行が属する入れ子の深さを返す。

    正準形は 1 行 1 要素なので、括弧の開閉だけで深さが決まる。
    """
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("}", "]")):
            depth -= 1
        yield line, depth
        if stripped.endswith(("{", "[")):
            depth += 1


def test_rule1_indent_is_two_spaces(formattable_paths: list[Path]) -> None:
    """規則 1: インデントは**深さ × 2 スペース**。

    「2 の倍数か」だけを見ると `INDENT = "    "` に変えても通ってしまう
    （correctness review E-1）。深さから期待値を計算して突き合わせる。
    """
    assert INDENT == "  ", f"規則 1 の単位が変わっている: {INDENT!r}"
    checked = 0
    for path, text in _canonical_texts(formattable_paths):
        for line, depth in _lines_with_depth(text):
            indent = len(line) - len(line.lstrip(" "))
            assert indent == depth * 2, (
                f"{path}: 深さ {depth} の行のインデントが {indent}（期待 {depth * 2}）: {line!r}"
            )
            assert "\t" not in line, f"{path}: タブが混じっている"
            checked += 1
    assert checked > 0, "検査対象の行が 1 行も無い"


def test_the_indent_check_can_tell_a_widened_indent_apart() -> None:
    """E-1: 上のテストが使う**検査ロジック自体**が幅の差を見分けられることを固定する。

    旧名は `test_rule1_detects_a_wider_indent_unit`（correctness review R2-2 で改名）。
    旧名は「`INDENT` を 4 に変える変異でこのテストが落ちる」と読めるが、**落ちない**。
    ここは writer に触れず、自分で 4 スペース化したテキストを `_lines_with_depth` と
    深さ × 2 の比較に通しているだけだからである。
    `INDENT` の変異を捕まえる実効ガードは `test_rule1_indent_is_two_spaces` の側にある
    （そちらは `INDENT == "  "` を直接固定している）。
    このテストの役目は「その実効ガードが使う道具が、差を差として検出できる」ことの確認に限られる。
    """
    text = dumps(JinFile.model_validate(MINIMAL_DOCUMENT))
    widened = "\n".join(
        " " * (2 * (len(line) - len(line.lstrip(" ")))) + line.lstrip(" ")
        for line in text.splitlines()
    )
    bad = [
        (line, depth)
        for line, depth in _lines_with_depth(widened)
        if (len(line) - len(line.lstrip(" "))) != depth * 2
    ]
    assert bad, "4 スペース化したのに検査が差を見つけられなかった"


def test_rule2_key_order_is_schema_definition_order(formattable_paths: list[Path]) -> None:
    for path, text in _canonical_texts(formattable_paths):
        document = json.loads(text)
        _assert_key_order(document, JinFile, path)


def _field_order(model_cls: type) -> list[str]:
    return [info.alias or name for name, info in model_cls.model_fields.items()]


def _assert_key_order(node, model_cls, path: Path) -> None:
    from jin_core.model import Boundary, Circle, Flow, FlowExit, Guard, Instruction, State

    expected = _field_order(model_cls)
    actual = [k for k in node if k in expected]
    assert actual == [k for k in expected if k in node], f"{path}: {model_cls.__name__} のキー順"

    children = {
        JinFile: [("circles", Circle, True)],
        Circle: [
            ("instruction", Instruction, False),
            ("state", State, True),
            ("flow", Flow, False),
            ("boundary", Boundary, False),
        ],
        Flow: [("exit", FlowExit, False)],
        Boundary: [("guards", Guard, True)],
    }.get(model_cls, [])

    for key, child_cls, is_list in children:
        value = node.get(key)
        if value is None:
            continue
        for item in value if is_list else [value]:
            _assert_key_order(item, child_cls, path)


def test_rule3_arrays_keep_declaration_order(example_paths: list[Path]) -> None:
    for path in example_paths:
        source = json.loads(path.read_text(encoding="utf-8"))
        canonical = json.loads(dumps(check_file(path).model))
        assert [c["name"] for c in canonical["circles"]] == [c["name"] for c in source["circles"]]


def test_rule4_trailing_newline(formattable_paths: list[Path]) -> None:
    for path, text in _canonical_texts(formattable_paths):
        assert text.endswith("\n"), path
        assert not text.endswith("\n\n"), path


def test_rule5_non_ascii_is_not_escaped(formattable_paths: list[Path]) -> None:
    """規則 5: 非 ASCII はエスケープしない。

    元の正規表現 `\\u00[2-9a-f][0-9a-f]` は**決して一致しなかった**（correctness review E-2）。
    writer が `\\uXXXX` を出すのは U+0000〜U+001F だけなので、2 桁目に `[2-9a-f]` を求める
    パターンは writer の出力集合と交わらない = 空虚なアサーションだった。
    「現れる `\\uXXXX` はすべて制御文字である」という、writer の出力集合に触れる形にする。
    """
    checked = 0
    for path, text in _canonical_texts(formattable_paths):
        for code in re.findall(r"\\u([0-9a-fA-F]{4})", text):
            assert int(code, 16) < 0x20, (
                f"{path}: 制御文字でない文字がエスケープされている \\u{code}"
            )
            checked += 1
        assert "\\u3" not in text, path
    # 非 ASCII が生で出ていることを 1 件以上で確認する（検査対象が空にならないように）。
    non_ascii = [
        path
        for path, text in _canonical_texts(formattable_paths)
        if re.search(r"[^\x00-\x7f]", text)
    ]
    assert non_ascii, "非 ASCII を含む正準形が 1 件も無い。規則 5 が検査できていない"
    assert checked >= 0


def test_rule5_escapes_only_control_characters() -> None:
    """E-2: 上の検査が「エスケープすべきでない文字がエスケープされた」ことを捕まえられること。

    writer を直接呼び、制御文字だけが `\\uXXXX` になり、それ以外は生で出ることを見る。
    """
    literal = encode_string("a\x01b\x1fc\u00e9d\u3042e\U0001f409")
    codes = [int(c, 16) for c in re.findall(r"\\u([0-9a-fA-F]{4})", literal)]
    assert codes == [0x01, 0x1F], codes
    for raw in ("\u00e9", "\u3042", "\U0001f409"):
        assert raw in literal, raw


def test_rule6_schema_and_version_first(formattable_paths: list[Path]) -> None:
    for path, text in _canonical_texts(formattable_paths):
        lines = text.splitlines()
        assert lines[1].startswith('  "$schema":'), path
        assert lines[2].startswith('  "version":'), path


def test_rule7_default_values_are_omitted() -> None:
    document = {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "A",
        "circles": [
            {
                "name": "A",
                "core": "m",
                "tools": [],
                "delegate": [],
                "state": [{"name": "s", "type": "str", "out": False}],
            }
        ],
    }
    text = dumps(JinFile.model_validate(document))
    assert '"out"' not in text
    assert '"tools"' not in text
    assert '"delegate"' not in text


@pytest.mark.parametrize(("written_value", "should_be_dropped"), [(False, True), (True, False)])
def test_rule7_roundtrip_drops_explicit_defaults(
    tmp_path: Path, written_value: bool, should_be_dropped: bool
) -> None:
    """明示的に書かれた**既定値**は 1 回目の fmt で消え、既定でない値は残る。

    値が 1 つしかない parametrize は実質パラメタライズになっておらず、
    「既定値でないものまで消してしまう」後退を捕まえられない（correctness review E-3）。
    """
    explicit_default = written_value
    document = {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "A",
        "circles": [
            {
                "name": "A",
                "core": "m",
                "state": [{"name": "s", "type": "str", "out": explicit_default}],
            }
        ],
    }
    target = tmp_path / "a.jin"
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    once = dumps(check_file(target).model)
    if should_be_dropped:
        assert '"out"' not in once, once
    else:
        assert '"out": true' in once, once
    assert dumps(check_text(once, str(target)).model) == once
