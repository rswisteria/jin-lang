"""`examples-v2/tetris-plus` の遊び方の契約: 録画を `jin run --input` で Lua と wasm-GC の両方に流し、通しの流れを固定する。

tetris-plus は LSP(`jin lsp` の `jin/applyOps`)に編集操作を送って組み立てたサンプルで、既存の tetris に無い
7-bag・NEXT 3 つ・ホールド・ゴースト・レベル・ポーズ(`wait until`)・ハイスコア(`storage` と `num`)を持つ。
録画は 2 本(`tests/fixtures/jinrec/`):

- `tetris-plus-playthrough.jinrec`: ホールド → ポーズと再開 → ハードドロップを重ねて終わる → 新記録 → RETRY →
  2 回目(記録した最高点を読む)→ QUIT で root が done
- `tetris-plus-lines.jinrec`: 盤面を見て置き場所を選ぶ自動操縦の録画。行を消してレベルが 1 に上がる
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAM = REPO_ROOT / "examples-v2" / "tetris-plus" / "tetris-plus.jin"
RECORDINGS = REPO_ROOT / "tests" / "fixtures" / "jinrec"


def run(target: str, recording: str, tmp_path: Path) -> tuple[dict, list[dict], str]:
    frames = tmp_path / f"{recording}-{target}.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            "-P",
            "-m",
            "jin_cli.main",
            "run",
            str(PROGRAM),
            "--target",
            target,
            "--input",
            str(RECORDINGS / f"tetris-plus-{recording}.jinrec"),
            "--frames",
            str(frames),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    return (
        json.loads(proc.stdout),
        [json.loads(line) for line in frames.read_text(encoding="utf-8").splitlines()],
        proc.stderr,
    )


def test_the_sample_is_what_the_language_server_builds() -> None:
    """サンプルは手で書かず、`jin lsp` に `jin/applyOps` を送って組み立てる(`scripts/build_tetris_plus.py`)。
    op の意味や正準形が変わってずれたら、スクリプトを直して再生成する。"""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_tetris_plus.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr


def texts(frame: dict) -> list[str]:
    return [op[1] for op in frame["ops"] if op[0] == "text"]


@pytest.mark.parametrize("recording", ["playthrough", "lines"])
def test_both_targets_play_the_recording_identically(recording: str, tmp_path: Path) -> None:
    lua = run("lua", recording, tmp_path)
    wasm = run("wasm-gc", recording, tmp_path)
    assert wasm[0] == lua[0]
    assert wasm[1] == lua[1]


def test_a_playthrough_holds_pauses_records_retries_and_quits(tmp_path: Path) -> None:
    public, frames, stderr = run("lua", "playthrough", tmp_path)
    assert "tick 901 で done" in stderr  # QUIT で root の流れが終わる
    # 2 回目は 1 回目の最高点(207)を storage から読み、それを超えないので新記録ではない
    assert public["Play.best"] == 207
    assert public["Play.score"] < 207
    assert public["Play.record"] is False
    assert public["Result.quit"] is True
    by_tick = {f["tick"]: f for f in frames}
    assert "PAUSE" in texts(by_tick[70])  # P で止まり(落下は wait until で待つ)
    assert "PAUSE" not in texts(by_tick[100])  # もう一度 P で再開
    assert "新記録！" in texts(by_tick[300])  # 1 回目の結果画面(k6x8 の字形で描く)
    assert "新記録！" not in texts(by_tick[700])  # 2 回目の結果画面


def test_lines_raise_the_level_and_score_by_the_formula(tmp_path: Path) -> None:
    public, frames, _ = run("lua", "lines", tmp_path)
    assert public["Play.lines"] == 12
    assert public["Play.level"] == 1  # 10 行ごとに 1 つ上がり、落下が速くなる
    assert public["Play.score"] == 2848
    assert "LEVEL 1" in texts(frames[-1])
