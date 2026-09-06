"""トレース overlay の読み取り型と強調規則（`docs/spec/layout.md` §7）。

## `jin_adk` に依存しない

`jin_render` が import してよいのは `jin_core` と標準ライブラリだけである
（design.yaml rule 4・import-linter の layers 契約）。`jin_adk.trace` の `TraceEvent` /
`KIND_POINTERS` を取り込むと兄弟パッケージへの依存になるので、**overlay に必要な最小の
読み取り型をここに置く**。必要なのは各行の `seq`（1 始まりの int）と `pointer`（str または null）だけで、
他のキー（`ts` / `agent` / `kind` / `name` / `input` / `output`）は無視する。

**黙って捨てない**（NFR-FAIL-001）: `seq` が int でない行・`seq` が範囲外の行・
`pointer` が str でも null でもない行は `TraceRowError`（`ValueError` の子）で拒む。
読み飛ばすと「発火していないのに未強調」と区別できなくなる。例外には**並びの中の位置**
（0 始まり）を載せる。CLI はそれを JSONL の実ファイル行番号へ写して `path:N:` と出す
（空行を読み飛ばすので、並びの位置と行番号は一致しない・F-V-P3-004）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: `seq` の上限。`jin_adk.trace` は 1 始まりの連番しか書かないが、`--trace` は**外部データ**
#: なので JSON の任意精度整数がそのまま入りうる。5000 桁の整数は `json.loads` を通り、
#: 以降の比較・ソートで CPU を食う（F-S-P3-001 / F-C-P3-004）。64bit 符号付きの上限で切る。
SEQ_MAX = 2**63 - 1


#: エラーメッセージに載せる値の最大長。`--trace` は外部データなので、1 行に数 MB の
#: 文字列が入りうる（そのまま `!r` すると端末とログを埋める・F-S-P3-008）。
BRIEF_MAX = 80


def brief(value: object) -> str:
    """値をメッセージに載せられる長さへ丸めた `repr`。"""
    try:
        text = repr(value)
    except ValueError:
        # 4300 桁を超える int の `repr` は Python 自身が拒む（int_max_str_digits）。
        # 「読めない値の報告」で落ちては本末転倒なので型名だけにする。
        return f"<{type(value).__name__}>"
    return text if len(text) <= BRIEF_MAX else text[:BRIEF_MAX] + "…"


class TraceRowError(ValueError):
    """トレース 1 行が契約を満たさない。`index` は**並びの中の位置**（0 始まり）。"""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(message)
        self.index = index


@dataclass(frozen=True)
class TraceRow:
    """overlay が使うトレース 1 行の最小表現。"""

    seq: int
    pointer: str | None


def read_trace(rows: Sequence[Mapping[str, Any]]) -> list[TraceRow]:
    """トレース行の並びを検証して `TraceRow` の列にする（`seq` の昇順）。

    同じ `seq` が複数あっても拒まない（並びは元の順序を保つ安定ソート）。
    """
    # 型違いは `TypeError` ではなく `ValueError` にする。
    # ここは「Python の呼び出し規約の誤り」ではなく「**外部データ**（`--trace` の JSONL）が
    # 契約を満たしていない」ことの報告であり、CLI は `--focus` の誤りと同じ入力エラー
    # （exit 2）として一括で扱う。`TypeError` にすると呼び出し側が 2 種類を捕まえることになる。
    out: list[TraceRow] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TraceRowError(
                index, f"トレース行がオブジェクトではありません: {type(row).__name__}"
            )
        if "seq" not in row:
            raise TraceRowError(index, "トレース行に seq がありません")
        seq = row["seq"]
        # `bool` は `int` の子なので明示的に外す（True が seq 1 として通ってしまう）。
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise TraceRowError(index, f"トレース行の seq が整数ではありません: {brief(seq)}")
        if not 1 <= seq <= SEQ_MAX:
            # `jin_adk.trace` の `seq` は 1 始まりの連番（adk-mapping §6）。
            raise TraceRowError(index, f"トレース行の seq が 1..{SEQ_MAX} の外です: {brief(seq)}")
        if "pointer" not in row:
            raise TraceRowError(index, "トレース行に pointer がありません")
        pointer = row["pointer"]
        if pointer is not None and not isinstance(pointer, str):
            raise TraceRowError(
                index, f"トレース行の pointer が文字列でも null でもありません: {brief(pointer)}"
            )
        out.append(TraceRow(seq=seq, pointer=pointer))
    out.sort(key=lambda row: row.seq)
    return out


def is_ancestor_or_same(candidate: str, pointer: str) -> bool:
    """`candidate` が `pointer` と同じか、その**祖先**か（`/` 区切りの前方一致）。

    `/circles/1` は `/circles/10/core` の祖先では**ない**（次の文字が `/` でない）。
    ルート `""`（= 文書全体）は祖先に数えない（layout.md §7.1: 強調は描いた要素にだけ付く）。
    prefix を materialize しないので、pointer の長さに比例するメモリを使わない
    （F-S-P3-002: 100 KB の pointer で 5 GB を確保していた）。
    """
    if candidate == pointer:
        return True
    if not candidate:
        return False
    return (
        len(candidate) < len(pointer)
        and pointer.startswith(candidate)
        and pointer[len(candidate)] == "/"
    )


__all__ = [
    "BRIEF_MAX",
    "SEQ_MAX",
    "TraceRow",
    "TraceRowError",
    "brief",
    "is_ancestor_or_same",
    "read_trace",
]
