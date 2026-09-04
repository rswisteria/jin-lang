"""ADK 識別子 → JSON Pointer の対応表（ADR-009 / DP-JIN-TRACE-POINTER-01 案 B）。

要件書 §3.4 はトレース行に pointer（レンダラの `data-jin` と同じ鍵）を要求するが、
`adk-api-probe.md` の実測どおり ADK の `Event` は pointer を持たない。
そこで**コード生成時に**「ADK 上の識別子 → JSON Pointer」の対応表を作り、実行時に引く。

案 A（実行時に Event の内容からモデルを逆引きする）を採らない理由は ADR-009 のとおり:
`tools[].name` は circle 内一意であって**ファイル内一意ではない**ので、同名 tool を
一意に引けない。だから表の第 1 段は必ず**エージェント名**（`Event.author`）で切る。

この表は**生成物には書き出さない**。ADR-009 の決定文どおり「生成物とは別に保持」する
（生成プロジェクトの構造は要件書 §3.1 のとおり 3 ファイルちょうどでなければならない）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PointerMap:
    """生成時に確定する対応表。

    キーはすべて**生成された ADK 上の名前**（`Event.author` と突き合わせるため）で、
    Jin の circle 名とは一致しないことがある（`flow.exit` の判定エージェントなど）。
    """

    #: エージェント名 → circle の pointer（`/circles/<i>`）。
    agents: dict[str, str] = field(default_factory=dict)
    #: エージェント名 → `core` の pointer（`/circles/<i>/core`）。核なし circle には無い。
    cores: dict[str, str] = field(default_factory=dict)
    #: エージェント名 → tool 名 → tool の pointer（`/circles/<i>/tools/<j>`）。
    tools: dict[str, dict[str, str]] = field(default_factory=dict)
    #: エージェント名 → guard の `on` → pointer の並び（同種が複数あり得る）。
    guards: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    #: エージェント名 → 委譲先エージェント名 → `/circles/<i>/delegate/<k>`。
    delegates: dict[str, dict[str, str]] = field(default_factory=dict)
    #: 判定エージェント名 → `/circles/<i>/flow/exit`。
    exits: dict[str, str] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "agents": self.agents,
            "cores": self.cores,
            "tools": self.tools,
            "guards": self.guards,
            "delegates": self.delegates,
            "exits": self.exits,
        }

    def all_pointers(self) -> list[str]:
        """表に載っている pointer を重複なく返す（テストの網羅確認用）。"""
        seen: list[str] = []
        for pointer in [
            *self.agents.values(),
            *self.cores.values(),
            *self.exits.values(),
            *(p for by_name in self.tools.values() for p in by_name.values()),
            *(p for by_name in self.delegates.values() for p in by_name.values()),
            *(p for by_on in self.guards.values() for ps in by_on.values() for p in ps),
        ]:
            if pointer not in seen:
                seen.append(pointer)
        return seen


__all__ = ["PointerMap"]
