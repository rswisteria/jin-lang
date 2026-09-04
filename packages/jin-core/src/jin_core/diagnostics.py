"""診断の型とコード表。

正本は `docs/spec/diagnostics.md`。診断 JSON の形式は要件書 §5 / FR-CLI-002 と 1:1。

**行・列の基点（DP-JIN-POINTER-RANGE-01 の追加確定値・docs/spec/diagnostics.md §5.1）**:

- `line` / `col` はいずれも **1 始まり**（lark がネイティブに 1 始まりで、変換しないことでズレを作らない）
- `range.end` は **排他**（lark の `end_column` の意味に合わせる）
- 列は **Unicode コードポイント単位**

LSP（0 始まり / UTF-16 コードユニット）への変換は `jin-lsp` の 1 モジュールだけが行う（Phase 4）。
`jin_core` は LSP を知らない。ここに 0 始まりの値や UTF-16 換算を持ち込まないこと。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Position:
    """1 始まりの行・列（列はコードポイント単位）。"""

    line: int
    col: int

    def to_json_dict(self) -> dict[str, int]:
        return {"line": self.line, "col": self.col}


@dataclass(frozen=True, slots=True)
class Range:
    """`start` を含み `end` を含まない範囲。"""

    start: Position
    end: Position

    def to_json_dict(self) -> dict[str, dict[str, int]]:
        return {"start": self.start.to_json_dict(), "end": self.end.to_json_dict()}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """要件書 §5 の診断 JSON に 1:1 対応する。"""

    file: str
    pointer: str
    range: Range
    code: str
    severity: Severity
    message: str
    hint: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "file": self.file,
            "pointer": self.pointer,
            "range": self.range.to_json_dict(),
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.hint is not None:
            payload["hint"] = self.hint
        return payload


#: 正典コード（要件書 §2.4 の 12 件）。docs/spec/diagnostics.md §2 と一致させること。
CANONICAL_CODES: dict[str, Severity] = {
    "JIN001": "error",
    "JIN002": "error",
    "JIN010": "error",
    "JIN011": "error",
    "JIN020": "error",
    "JIN022": "error",
    "JIN030": "error",
    "JIN031": "error",
    "JIN040": "warning",
    "JIN050": "error",
    "JIN060": "error",
    "JIN070": "warning",
}

#: 追加提案コード（ADR-007 / DP-JIN-SEMANTIC-GAPS-01・**人間承認待ち**）。
#: 採番の根拠は docs/spec/diagnostics.md §3.1。
PROPOSED_CODES: dict[str, Severity] = {
    "JIN012": "error",
    "JIN013": "error",
}

#: 実装が出しうる全コード。
ALL_CODES: dict[str, Severity] = {**CANONICAL_CODES, **PROPOSED_CODES}

#: 要素数の上限（JIN020）。要件書 §2.4「tools または state が 12 を超えた」。
MAX_ELEMENTS = 12


def severity_of(code: str) -> Severity:
    try:
        return ALL_CODES[code]
    except KeyError as exc:  # pragma: no cover - 実装ミスの早期検出用
        raise KeyError(f"未知の診断コードです: {code}") from exc


def has_error(diagnostics: list[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diagnostics)


__all__ = [
    "ALL_CODES",
    "CANONICAL_CODES",
    "MAX_ELEMENTS",
    "PROPOSED_CODES",
    "Diagnostic",
    "Position",
    "Range",
    "Severity",
    "has_error",
    "severity_of",
]
