"""コンパイル時エラー（NFR-FAIL-001「ADK に対応物のない Jin 構造は黙って落とさない」）。

意味検査（`jin_core.semantic`）が通っても、ADK に写せない構造は残る。例:

- circle 名が Python の識別子でない（ADK の `BaseAgent.name` は `str.isidentifier()` を要求する・実測）
- 1 つの circle に `out: true` の state が 2 件以上（`LlmAgent.output_key` は単一値）
- 核なし circle（workflow agent）に `instruction` / `tools` / `delegate` がある
  （`SequentialAgent` / `ParallelAgent` / `LoopAgent` にそれらのフィールドは無い・実測）

これらは**診断コードを増やさず**（`docs/spec/model.md` §3.3 / `docs/spec/adk-mapping.md` §5）、
`jin build` / `jin run` のコンパイル時エラーとして落とす。黙って生成物から落とすと、
「書いたのに効かない」という最も気づきにくい壊れ方になる。

診断（`jin check`）と同じく **pointer を必ず持つ**。pointer はファイル内の位置・描画・
トレースを結ぶ唯一の鍵であり（要件書 §10 #11）、エディタがそのまま該当箇所へ飛べる。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompileIssue:
    """コンパイルできない箇所 1 件。

    `message` は「何が悪いか」、`hint` は「どう直すか」を必ず含める（要件書 §5）。
    """

    pointer: str
    message: str
    hint: str

    def to_json_dict(self) -> dict[str, str]:
        return {"pointer": self.pointer, "message": self.message, "hint": self.hint}

    def __str__(self) -> str:
        return f"{self.pointer or '(root)'}: {self.message}\n  hint: {self.hint}"


class CompileError(Exception):
    """ADK へ写せない構造が 1 件以上あった。

    **1 件目で止めない**。`jin check` が全診断を返すのと同じで、直す側が
    1 回の実行で全部見られるほうがよい。
    """

    def __init__(self, issues: list[CompileIssue]) -> None:
        if not issues:
            raise ValueError("CompileError は 1 件以上の CompileIssue を要求する")
        self.issues = issues
        super().__init__("\n".join(str(issue) for issue in issues))


__all__ = ["CompileError", "CompileIssue"]
