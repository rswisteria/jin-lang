"""`docs/tetris-tutorial.md`（プログラミング入門教材）の段階サンプルが実際に動くことを固定する。

教材は「章ごとに動く `.jin` を 1 本ずつ積み上げ、最終段は `examples-v2/tetris/tetris.jin` そのもの」を
約束している。段階サンプル（`docs/samples/tetris/`）は `examples-v2/` の 4 本（本数が固定されている）とは
別枠なので、ここで独立に check / fmt / ヘッドレス実行を走らせ、本文の抜粋がサンプルからずれていないことも見る。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import child_env

REPO_ROOT = Path(__file__).resolve().parents[2]
JIN = Path(sys.executable).parent / "jin"  # test_cli_contract と同じ引き方
GUIDE = REPO_ROOT / "docs" / "tetris-tutorial.md"
SAMPLE = REPO_ROOT / "docs" / "samples" / "tetris"
FINAL = REPO_ROOT / "examples-v2" / "tetris" / "tetris.jin"

#: 教材の章の順（本文の目次と 1:1。増減したら本文も直す）
STAGES = [
    "01-canvas",
    "02-fall",
    "03-move",
    "04-piece",
    "05-fits",
    "06-board",
    "07-lines",
    "08-controls",
    "09-tetris",
]

#: 本文の抜粋の目印。この行の直後の ```json ブロックが、名指しされたファイルの一部であることを見る。
EXCERPT = re.compile(
    r"<!-- excerpt: (docs/samples/tetris/[\w.-]+\.jin) -->\n```json\n(.*?)```", re.DOTALL
)


def _jin(*args: str) -> subprocess.CompletedProcess[str]:
    assert JIN.exists(), f"jin コマンドが見つからない: {JIN}"
    return subprocess.run(
        [str(JIN), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=child_env(),
        check=False,
    )


def _stage(name: str) -> Path:
    return SAMPLE / f"{name}.jin"


def _squash(text: str) -> str:
    """行頭の空白を落として比べる（抜粋は入れ子の深さを変えて引用してよい）。"""
    return "\n".join(line.strip() for line in text.strip().splitlines())


def test_the_stages_are_exactly_the_files_in_the_sample_directory() -> None:
    """章とファイルが 1:1。増やしたら本文の目次と STAGES の両方を直す。"""
    found = sorted(p.stem for p in SAMPLE.glob("*.jin"))
    assert found == STAGES


def test_every_sample_path_named_in_the_guide_exists() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    paths = set(re.findall(r"docs/samples/tetris/[\w./-]+", text))
    assert paths, "教材がサンプルのパスを 1 つも参照していない"
    missing = sorted(p for p in paths if not (REPO_ROOT / p).exists())
    assert not missing, f"教材が参照するファイルが無い: {missing}"


def test_the_guide_walks_through_every_stage_in_order() -> None:
    """本文に全段階が出てきて、出てくる順が番号の順である。"""
    text = GUIDE.read_text(encoding="utf-8")
    positions = [text.find(f"docs/samples/tetris/{name}.jin") for name in STAGES]
    assert all(p >= 0 for p in positions), (
        f"本文に出てこない段階がある: {dict(zip(STAGES, positions))}"
    )
    assert positions == sorted(positions), "本文の段階の順が番号の順と違う"


def test_check_and_fmt_pass_on_every_stage() -> None:
    """全段階が診断 0 件で正準形（`jin check` / `jin fmt --check` はディレクトリごと）。"""
    check = _jin("check", str(SAMPLE))
    assert check.returncode == 0, check.stdout + check.stderr
    assert f"{len(STAGES)} ファイル / error 0 件 / warning 0 件" in check.stderr, (
        check.stdout + check.stderr
    )
    fmt = _jin("fmt", "--check", str(SAMPLE))
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr


@pytest.mark.parametrize("name", STAGES)
def test_every_stage_runs_headless_without_a_runtime_error(name: str, tmp_path: Path) -> None:
    """各段階を 90 tick（3 秒）走らせて実行時エラーの行が無い。"""
    trace = tmp_path / "t.jsonl"
    run = _jin("run", str(_stage(name)), "--ticks", "90", "--debug", "--trace", str(trace))
    assert run.returncode == 0, run.stdout + run.stderr
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert rows, "トレースが空"
    errors = [r for r in rows if r["kind"] == "error"]
    assert not errors, errors


def test_the_final_stage_is_the_example_itself() -> None:
    """教材の最終形は examples-v2 の tetris とバイト一致する（片方を直したらもう片方も直す）。"""
    assert _stage("09-tetris").read_bytes() == FINAL.read_bytes()


def test_each_stage_only_adds_to_the_previous_one() -> None:
    """段階は積み上げ: 前の段階にあった state と手順の名前は次の段階にも残る（教材が「消す」章を持たない）。"""

    def names(path: Path) -> tuple[set[str], set[str]]:
        doc = json.loads(path.read_text(encoding="utf-8"))
        play = next(c for c in doc["circles"] if c["name"] == "Play")
        return (
            {s["name"] for s in play.get("state", [])},
            {r["name"] for r in play.get("rites", [])},
        )

    previous = names(_stage(STAGES[0]))
    for name in STAGES[1:]:
        current = names(_stage(name))
        if name == "04-piece":
            # 04 で「1 マス」の x / y と paint が型紙 piece / paintBoard 系に置き換わる（本文 §4 が説明する唯一の例外）
            previous = (set(), {"begin"})
        if name == "05-fits":
            # 05 で 04 の touches（底に着いたか）は fits に吸収される（本文 §5）
            previous = (previous[0], previous[1] - {"touches"})
        if name == "06-board":
            # 06 で paint は盤面も描く paintBoard に改名される（本文 §6）
            previous = (previous[0], previous[1] - {"paint"})
        missing_state = previous[0] - current[0]
        missing_rites = previous[1] - current[1]
        assert not missing_state and not missing_rites, (name, missing_state, missing_rites)
        previous = current


def test_the_excerpts_in_the_guide_are_copied_from_the_samples() -> None:
    """本文の ```json 抜粋（`<!-- excerpt: … -->` の直後）が、名指しされたサンプルの一部である。

    サンプルは正準形なので、コピーした抜粋なら行頭の空白を除いて一致する。字面がずれたら
    サンプルを直した人が本文も直す（入門教材は抜粋の字面が命）。
    """
    text = GUIDE.read_text(encoding="utf-8")
    excerpts = EXCERPT.findall(text)
    assert len(excerpts) >= len(STAGES), f"抜粋が少なすぎる: {len(excerpts)} 個"
    for rel, body in excerpts:
        source = _squash((REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert _squash(body) in source, f"{rel} に無い抜粋:\n{body}"


def test_the_stage_files_stay_within_the_language_limits_the_guide_teaches() -> None:
    """本文 §5 が教える上限（手順直下 12 ステップ・入れ子 3 段）を、サンプル自身が守っている。

    `jin check` が JIN210 / JIN211 で落とすので二重だが、教材の主張（「上限の中で書く」）を
    テストの名前で残す。
    """

    def depth(steps: list[dict], d: int = 0) -> int:
        worst = d
        for s in steps:
            for key in ("then", "else", "steps"):
                if key in s and isinstance(s[key], list):
                    worst = max(worst, depth(s[key], d + 1))
        return worst

    for name in STAGES:
        doc = json.loads(_stage(name).read_text(encoding="utf-8"))
        for circle in doc["circles"]:
            for rite in circle.get("rites", []):
                assert len(rite["steps"]) <= 12, (name, rite["name"])
                assert depth(rite["steps"]) <= 3, (name, rite["name"])
