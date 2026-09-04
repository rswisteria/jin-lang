"""正準形 writer（ADR-005 / DP-JIN-CANONICAL-01）のテスト。

要件書 §2.3 の 5 規則 + $schema/version 先頭固定 + 既定値の省略を 1 箇所（jin_core.canonical）で担保する。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.canonical import dumps, encode_string
from jin_core.model import JinFile
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]


def build(**circle_extra) -> JinFile:
    doc = {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "A",
        "circles": [{"name": "A", "core": "m", **circle_extra}],
    }
    return JinFile.model_validate(doc)


def test_two_space_indent_and_trailing_newline() -> None:
    text = dumps(build())
    assert text.endswith("}\n")
    assert not text.endswith("}\n\n")
    assert '\n  "version": 1,\n' in text


def test_schema_and_version_come_first() -> None:
    lines = dumps(build()).splitlines()
    assert lines[0] == "{"
    assert lines[1].startswith('  "$schema":')
    assert lines[2].startswith('  "version":')
    assert lines[3].startswith('  "root":')


def test_key_order_follows_field_definition_order() -> None:
    model = build(
        description="d",
        instruction={"rune": "r"},
        state=[{"name": "s", "type": "str"}],
    )
    text = dumps(model)
    order = [
        text.index('"name"'),
        text.index('"core"'),
        text.index('"description"'),
        text.index('"instruction"'),
        text.index('"state"'),
    ]
    assert order == sorted(order)


def test_default_values_are_omitted() -> None:
    text = dumps(build(state=[{"name": "s", "type": "str", "out": False}]))
    assert '"out"' not in text
    assert '"tools"' not in text
    assert '"delegate"' not in text
    assert '"boundary"' not in text


def test_non_default_optional_is_emitted() -> None:
    text = dumps(build(state=[{"name": "s", "type": "str", "out": True}]))
    assert '"out": true' in text


def test_non_ascii_is_not_escaped() -> None:
    text = dumps(build(description="調査と要約"))
    assert "調査と要約" in text
    assert "\\u" not in text


def test_control_characters_are_escaped() -> None:
    """writer の最小エスケープ（規則 5）。

    `\x01` / `\x1f` は S13 の追加で段 2（`jin_core.model`）が JIN002 として弾くため、
    モデル経由では writer に届かない。エスケープは **writer 単体の責務**なので
    `encode_string` を直接呼んで確かめる（アサーションは 1 つも緩めていない）。
    """
    literal = encode_string('a\nb\tc\x01d\x1fe"f\\g')
    assert "\\n" in literal and "\\t" in literal
    assert "\\u0001" in literal and "\\u001f" in literal
    assert '\\"' in literal and "\\\\" in literal
    assert not any(ord(ch) < 0x20 for ch in literal)

    # モデル経由（改行・タブは自由記述で許される）でも生の制御文字を出さない。
    text = dumps(build(instruction={"rune": 'a\nb\tc"d\\e'}))
    body = text.split('"rune": ', 1)[1].split("\n", 1)[0]
    assert not any(ord(ch) < 0x20 for ch in body)


@pytest.mark.parametrize("bad", ["a\x01b", "a\x1fb", "a\x7fb", "a\x9fb"])
def test_control_characters_are_rejected_by_the_model(bad: str) -> None:
    """S13: 制御文字（C0 / DEL / C1）は段 2 で落とす。

    改行・タブだけを自由記述に許し、それ以外は端末表示の偽装（S6）に使えるので拒む。
    """
    with pytest.raises(ValidationError):
        build(instruction={"rune": bad})


def test_lone_surrogate_is_rejected_by_the_writer() -> None:
    """D-1: 孤立サロゲートは UTF-8 に符号化できない。writer が明示的に拒む。"""
    with pytest.raises(ValueError, match="孤立サロゲート"):
        encode_string("a\ud800b")


def test_lone_surrogate_is_rejected_by_the_model() -> None:
    """D-1: 段 2 でも落とす（`jin fmt` が書き出しでクラッシュしないため）。"""
    with pytest.raises(ValidationError):
        build(description="a\ud800b")


def test_surrogate_pair_survives_roundtrip() -> None:
    """BMP 外の文字（異体字・絵文字）をエスケープせずそのまま出す。"""
    model = build(description="\U00020bb7野家 \U0001f409")
    text = dumps(model)
    assert "\U00020bb7野家 \U0001f409" in text
    assert json.loads(text)["circles"][0]["description"] == "\U00020bb7野家 \U0001f409"


def test_del_and_latin1_are_not_escaped() -> None:
    """U+007F（DEL）と U+0080 以上は writer のエスケープ対象外（docs/spec/model.md §7 規則 5）。

    U+007F と C1（U+0080〜U+009F）は S13 の追加で段 2 が弾くようになったので、
    **writer の規則**は `encode_string` を直接呼んで確かめる。
    U+00A0 以上（例: é）はモデルでも許されるのでモデル経由でも確かめる。
    """
    literal = encode_string("a\x7fb\xe9c\x9fd")
    assert "\x7f" in literal and "\xe9" in literal and "\x9f" in literal
    assert "\\u007f" not in literal.lower()

    text = dumps(build(description="a\xe9b"))
    assert "\xe9" in text
    assert "\\u" not in text


def test_output_is_valid_json_and_semantics_preserved() -> None:
    model = build(
        description="調査",
        instruction={"rune": "{x}"},
        tools=[{"name": "t", "kind": "summon", "circle": "A"}],
        state=[{"name": "x", "type": "str", "out": True}],
        boundary={"guards": [{"on": "before_model", "ref": "m:f"}], "await": []},
    )
    text = dumps(model)
    assert JinFile.model_validate(json.loads(text)) == model


def test_idempotent() -> None:
    model = build(description="調査")
    once = dumps(model)
    twice = dumps(JinFile.model_validate(json.loads(once)))
    assert once == twice


def test_empty_containers_are_emitted_when_explicitly_present() -> None:
    """boundary は既定 None。明示された空 boundary は空オブジェクトとして残る（冪等）。"""
    model = build(boundary={})
    text = dumps(model)
    assert '"boundary": {}' in text
    assert dumps(JinFile.model_validate(json.loads(text))) == text


def test_numbers_are_written_without_reformatting() -> None:
    doc = {
        "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
        "version": 1,
        "root": "A",
        "circles": [
            {
                "name": "A",
                "flow": {
                    "kind": "loop",
                    "steps": [],
                    "max": 3,
                    "exit": {"key": "k", "equals": 1.5},
                },
            }
        ],
    }
    text = dumps(JinFile.model_validate(doc))
    assert '"max": 3' in text
    assert '"equals": 1.5' in text


@pytest.mark.parametrize(
    "path",
    sorted((REPO_ROOT / "examples").glob("*/*.jin")),
    ids=lambda p: p.name,
)
def test_examples_are_already_canonical(path: Path) -> None:
    """Phase 0 で手書きした examples が Phase 1 の正準形と**バイト一致**すること。
    これが Phase 0 と Phase 1 の閉じ。"""
    raw = path.read_text(encoding="utf-8")
    model = JinFile.model_validate(json.loads(raw))
    assert dumps(model) == raw
