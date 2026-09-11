"""`docs/document-review-agent.md` のコマンドが実際に通ることを固定する。

ガイドは「動くサンプル付き」を約束している。サンプル（`docs/samples/docreview/`）は `examples/` の
3 本（要件書 §2.2 と machine 条件で本数が固定されている）とは別枠なので、ここで独立に
check / fmt / build / fake 実行 / ルール / 判定取り出しを走らせる。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from tests.conftest import child_env

REPO_ROOT = Path(__file__).resolve().parents[2]
JIN = Path(sys.executable).parent / "jin"  # test_cli_contract と同じ引き方
GUIDE = REPO_ROOT / "docs" / "document-review-agent.md"
SAMPLE = REPO_ROOT / "docs" / "samples" / "docreview"
JIN_FILE = SAMPLE / "docreview.jin"
VERDICT = SAMPLE / "verdict.py"

#: ガイド §1-3 の構成。fake 実行のトレースにこの順で `agent` が現れる（parallel の 6 本は順不同）。
PROFILER = "Profiler"
CHECKERS = frozenset({"FiveW1H", "Volume", "Terminology", "Typos", "Grammar", "Consistency"})
VERIFIER = "Verifier"
JUDGE = "Judge"

#: 動くサンプルの `judge` 応答行が出る pointer（`Judge` は `circles[10]`、その `tools[0]`）。
JUDGE_TOOL_POINTER = "/circles/10/tools/0"


def _jin(*args: str) -> subprocess.CompletedProcess[str]:
    assert JIN.exists(), f"jin コマンドが見つからない: {JIN}"
    env = child_env({"PYTHONPATH": str(SAMPLE)})
    return subprocess.run(
        [str(JIN), *args], cwd=REPO_ROOT, capture_output=True, text=True, env=env, check=False
    )


def _python(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    env = child_env({"PYTHONPATH": str(SAMPLE)})
    return subprocess.run(
        [sys.executable, "-P", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False
    )


def test_every_sample_path_named_in_the_guide_exists() -> None:
    """ガイドが名指しするファイルが消えたら気づく。"""
    text = GUIDE.read_text(encoding="utf-8")
    paths = set(re.findall(r"docs/samples/docreview/[\w./-]+", text))
    assert paths, "ガイドがサンプルのパスを 1 つも参照していない"
    missing = sorted(p for p in paths if not (REPO_ROOT / p).exists())
    assert not missing, f"ガイドが参照するファイルが無い: {missing}"


def test_check_and_fmt_pass_on_the_sample() -> None:
    """ガイド §2-1 / §2-2。"""
    check = _jin("check", str(JIN_FILE))
    assert check.returncode == 0, check.stdout + check.stderr
    fmt = _jin("fmt", "--check", str(JIN_FILE))
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr


def test_build_passes_on_the_sample(tmp_path: Path) -> None:
    """ガイド §2-4。rune の波括弧など `jin check` では出ない BuildError が無いこと。"""
    result = _jin("build", str(JIN_FILE), "--out", str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "DocReview" / "agent.py").exists()


def test_fake_run_visits_the_circles_in_the_documented_order(tmp_path: Path) -> None:
    """ガイド §2-5。Profiler → 6 チェッカー → Verifier → Judge の順に model 行が出る。"""
    trace = tmp_path / "trace.jsonl"
    result = _jin("run", str(JIN_FILE), "テスト本文", "--model", "fake", "--trace", str(trace))
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line]
    agents = [row["agent"] for row in rows]
    assert agents[0] == PROFILER
    assert set(agents[1:7]) == CHECKERS
    assert agents[7:] == [VERIFIER, JUDGE]
    assert all(row["pointer"] is not None for row in rows)
    # fake モデルはツールを呼ばないので判定行は無く、verdict.py は「無い」を exit 2 で返す（§2-7）
    verdict = _python(str(VERDICT), str(trace))
    assert verdict.returncode == 2, verdict.stdout + verdict.stderr


_RULES_PROBE = """
import json
from review.rules import judge
axes = ("w5h1", "volume", "terminology", "typo", "grammar", "consistency")
ok = {"findings": [], "dropped": [], "scores": {a: 90 for a in axes}}
ng = {"findings": [{"severity": "Critical"}], "dropped": [], "scores": {a: 90 for a in axes}}
for payload in (json.dumps(ok), json.dumps(ng), "not json"):
    print(json.loads(judge(payload))["verdict"])
"""


def test_the_rules_module_judges_ok_ng_and_broken_input() -> None:
    """ガイド §1-4 / §2-6。Critical 1 件で NG、壊れた入力も NG（fail-closed）。"""
    result = _python("-c", _RULES_PROBE, cwd=SAMPLE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == ["OK", "NG", "NG"]


_SCRIPTED_RUN = """
import json
import sys
from collections.abc import AsyncGenerator

import jin_cli.main
from google.adk.models import LlmRequest, LlmResponse
from google.genai import types
from jin_adk.fake_llm import FakeLlm

FINDINGS = {
    "findings": [{"id": "typo-1", "axis": "typo", "severity": "Minor", "location": "Slcak",
                  "problem": "誤記", "fix": "Slack", "evidence": "Slcak"}],
    "dropped": [],
    "scores": {"w5h1": 80, "volume": 75, "terminology": 70, "typo": 85, "grammar": 90,
               "consistency": 85},
}


class ScriptedLlm(FakeLlm):
    # FakeLlm はツール台本を全陣に配るので、`judge` が宣言された要求（= Judge 陣）で、
    # まだ応答が無いときだけ function_call を返す
    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        has_judge = "judge" in (llm_request.tools_dict or {})
        answered = any(
            part.function_response is not None
            for content in llm_request.contents
            for part in (content.parts or [])
        )
        if has_judge and not answered:
            args = {"findings_json": json.dumps(FINDINGS, ensure_ascii=False)}
            part = types.Part(function_call=types.FunctionCall(name="judge", args=args))
        else:
            part = types.Part(text="fake-response")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


jin_cli.main.FakeLlm = ScriptedLlm
jin_cli.main.app(["run", sys.argv[1], "本文", "--model", "fake", "--trace", sys.argv[2]])
"""


def test_the_judge_tool_row_carries_the_verdict(tmp_path: Path) -> None:
    """ガイド §3-4。判定の正本は `judge` ツールの応答行で、`verdict.py` がそこから読む。

    `jin run --model fake` にはツールを呼ばせる手段が無いので、`jin_cli.main.FakeLlm` を
    Judge 陣にだけツールを呼ばせる台本に差し替えて別プロセスで走らせる
    （`test_cli_contract._scripted_run` と同じ手口）。
    """
    trace = tmp_path / "trace.jsonl"
    result = _python("-c", _SCRIPTED_RUN, str(JIN_FILE), str(trace))
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line]
    tool_rows = [row for row in rows if row["kind"] == "tool"]
    assert [row["pointer"] for row in tool_rows] == [JUDGE_TOOL_POINTER, JUDGE_TOOL_POINTER]
    response = tool_rows[1]["output"]
    assert set(response) == {"result"}, "FunctionTool は文字列の戻り値を {'result': ...} に包む"
    assert json.loads(response["result"])["verdict"] == "OK"

    verdict = _python(str(VERDICT), str(trace))
    assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    assert json.loads(verdict.stdout)["verdict"] == "OK"


def test_verdict_script_returns_1_for_ng(tmp_path: Path) -> None:
    """`verdict.py` の終了コード契約: NG は 1。"""
    trace = tmp_path / "trace.jsonl"
    row = {
        "seq": 1,
        "ts": 0.0,
        "agent": JUDGE,
        "kind": "tool",
        "name": "judge",
        "pointer": JUDGE_TOOL_POINTER,
        "input": None,
        "output": {"result": json.dumps({"verdict": "NG", "reasons": ["x"]})},
    }
    trace.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = _python(str(VERDICT), str(trace))
    assert result.returncode == 1, result.stdout + result.stderr
