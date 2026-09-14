"""`sigils[].kind = agent`（v2.1・model.md §3.2 / §3.5・runtime.md §11・設計書 §11 #55）の意味検査。

- `cast target=<sigil 名> args=[prompt: str] into=<num>`（要求 id）
- 自陣の `message` の手順は `(name: str, id: num, text: str)` の前方部分（JIN221）
- 式の中では呼べない（summon と同じ JIN202）
- `file` の形は schema で落とす（相対パス・`/` 区切り・`..` 無し・`.jin`）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jin_core.check import check_file, check_text
from jin_core.v2.model import JinFileV2, SigilAgent

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT = REPO_ROOT / "tests" / "fixtures" / "v2-programs" / "agent.jin"


def load() -> dict:
    return json.loads(AGENT.read_text(encoding="utf-8"))


def codes_of(doc: dict) -> list[str]:
    return [d.code for d in check_text(json.dumps(doc), "agent.jin").diagnostics]


def test_the_agent_fixture_checks_clean_and_the_sigil_is_typed() -> None:
    result = check_file(AGENT)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.model, JinFileV2)
    sigil = result.model.circles[0].sigils[0]
    assert isinstance(sigil, SigilAgent)
    assert sigil.kind == "agent"
    assert sigil.file == "agents/oracle.jin"


@pytest.mark.parametrize(
    "file",
    ["../oracle.jin", "/oracle.jin", "oracle.txt", "a/../oracle.jin", "sub\\oracle.jin", ""],
)
def test_the_file_form_is_rejected_by_the_schema(file: str) -> None:
    doc = load()
    doc["circles"][0]["sigils"][0]["file"] = file
    assert codes_of(doc) == ["JIN002"]


def test_the_cast_returns_a_num_and_takes_one_str() -> None:
    doc = load()
    steps = doc["circles"][0]["rites"][0]["steps"]
    steps[0]["into"] = "answer"  # str に num は入らない
    assert codes_of(doc) == ["JIN202"]
    doc = load()
    doc["circles"][0]["rites"][0]["steps"][0]["args"] = ["1"]
    assert codes_of(doc) == ["JIN202"]
    doc = load()
    doc["circles"][0]["rites"][0]["steps"][0]["args"] = []
    assert codes_of(doc) == ["JIN202"]


def test_the_agent_cannot_be_called_inside_an_expression() -> None:
    doc = load()
    doc["circles"][0]["rites"][0]["steps"][0] = {
        "do": "set",
        "target": "pending",
        "expr": 'oracle("hi")',
    }
    assert codes_of(doc) == ["JIN202"]


def test_the_agent_has_no_members() -> None:
    doc = load()
    doc["circles"][0]["rites"][0]["steps"][0]["target"] = "oracle.ask"
    assert codes_of(doc) == ["JIN202"]


def test_the_message_handler_must_take_name_id_text_in_that_order() -> None:
    doc = load()
    doc["circles"][0]["rites"][1]["params"][1]["type"] = "str"
    doc["circles"][0]["rites"][1]["steps"] = []  # 本体の型エラー（JIN202）を混ぜない
    assert codes_of(doc) == ["JIN221"]
    doc = load()
    doc["circles"][0]["rites"][1]["params"].append({"name": "extra", "type": "num"})
    assert codes_of(doc) == ["JIN221"]
    # 前方部分は許す（name だけ）。
    doc = load()
    doc["circles"][0]["rites"][1]["params"] = [{"name": "name", "type": "str"}]
    doc["circles"][0]["rites"][1]["steps"] = []
    assert codes_of(doc) == []


def test_emit_to_an_agent_circle_must_match_the_reply_shape() -> None:
    doc = load()
    doc["circles"].append(
        {
            "name": "Other",
            "core": "go",
            "rites": [
                {
                    "name": "go",
                    "steps": [
                        {"do": "emit", "circle": "Npc", "message": "poke", "args": ['"x"', '"y"']}
                    ],
                }
            ],
        }
    )
    doc["root"] = "Pair"
    doc["circles"].insert(
        0, {"name": "Pair", "flow": {"kind": "parallel", "steps": ["Npc", "Other"]}}
    )
    assert codes_of(doc) == ["JIN202"]


def test_agents_do_not_join_the_reference_cycle_graph() -> None:
    doc = load()
    result = check_text(json.dumps(doc), "agent.jin")
    assert "JIN012" not in [d.code for d in result.diagnostics]
