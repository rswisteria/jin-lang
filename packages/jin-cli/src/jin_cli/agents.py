"""v1 の陣（LLM エージェント）に答える Python ホスト（runtime.md §11・設計書 §11 #55・Issue #69）。

v2 の `.jin` の `sigils[].kind = agent` が指す v1 の `.jin` を、`jin run`（v2）の間だけ走らせる。
`jin_wasm.runtime.run_headless` は「問いに答える呼び出し可能」を受けるだけで v1 を知らない（層の契約）。
両方を知る唯一の層がここ（`jin_cli`）である。

【危険】v1 を走らせるのは v1 の `jin run` と同じ経路（`jin_adk.runtime.run_model`）で、その `.jin` の
`ref` が指すモジュールを **import する = 任意コード実行**。`--model fake` でも `ref` は import される。
「v2 の `jin run` は任意コードを実行しない」は **`agent` の sigil を持たない v2** についての主張である
（`jin_cli.main` のモジュール docstring・CLAUDE.md）。信頼しない `.jin` に `agent` があるなら `jin run` しない。

閉じ込め: `file` は v2 の `.jin` の親ディレクトリの**中**に解決できなければならない（asset と同じ規則）。
リンクは拒み、`resolve()` した実体が親の中にあることを見る。

    guard: resolve_agent_file -> path.is_symlink
    guard: resolve_agent_file -> resolved.is_relative_to(base)
    hazard: answer -> adk_runtime.run_model
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jin_adk import runtime as adk_runtime
from jin_adk.fake_llm import FakeLlm
from jin_adk.runtime import RunError
from jin_core.check import JinReadError, check_file
from jin_core.model import JinFile
from jin_core.v2.model import JinFileV2, SigilAgent


class AgentError(Exception):
    """`agent` の `file` を走らせられない（走らせる前は exit 2、走らせてからは exit 1 の 1 行の診断）。"""


def resolve_agent_file(source: Path, file: str) -> Path:
    """`agent.file`（v2 の `.jin` から見た相対パス）を親ディレクトリの中に解決する。

    形（相対・`/` 区切り・`..` 無し・`.jin`）は schema が落としているので、ここで見るのは実体:
    リンクでない・`resolve()` した先が親の中にある・普通のファイルである。

    guard: resolve_agent_file -> path.is_symlink
    guard: resolve_agent_file -> resolved.is_relative_to(base)
    """
    base = source.resolve().parent
    path = base.joinpath(*file.split("/"))
    if path.is_symlink():
        raise AgentError(f"{path}: シンボリックリンクなので v1 の陣として走らせません")
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise AgentError(f"{path}: {source.name} の親ディレクトリの外にあるので走らせません")
    if not resolved.is_file():
        raise AgentError(f"{path}: v1 の .jin がありません")
    return resolved


@dataclass(slots=True)
class AgentHost:
    """v2 の `.jin` の `agent` ごとに v1 のモデルを持ち、問いに答える（`run_headless(answer=...)`）。"""

    #: `"<陣名>.<sigil 名>"` → (v1 の `.jin` の実体, 検査済みの v1 モデル)
    agents: dict[str, tuple[Path, JinFile]]
    #: `--model fake`（`FakeLlm`・固定応答・ネットワーク不要）
    fake: bool = False
    #: 生成モジュールの import の間だけ `sys.path` の末尾に足す（v1 の `run` と同じ `[os.getcwd()]`）
    extra_sys_path: Sequence[str] = field(default_factory=lambda: [os.getcwd()])

    @classmethod
    def prepare(
        cls,
        source: Path,
        model: JinFileV2,
        *,
        fake: bool,
        extra_sys_path: Sequence[str] | None = None,
    ) -> AgentHost | None:
        """`agent` の sigil を集めて v1 の `.jin` を走らせる前に検査する。sigil が無ければ None。

        断る（`AgentError`）: 親の外 / リンク / 無い / 読めない / `jin check` が通らない / `version: 1` でない。
        """
        agents: dict[str, tuple[Path, JinFile]] = {}
        for circle in model.circles:
            for sigil in circle.sigils:
                if not isinstance(sigil, SigilAgent):
                    continue
                path = resolve_agent_file(source, sigil.file)
                try:
                    result = check_file(path)
                except JinReadError as exc:
                    raise AgentError(str(exc)) from exc
                if not result.ok or result.model is None:
                    errors = [d for d in result.diagnostics if d.severity == "error"]
                    head = errors[0].message if errors else "診断に error があります"
                    raise AgentError(f"{path}: jin check が通りません（{head}）")
                if not isinstance(result.model, JinFile):
                    raise AgentError(
                        f"{path}: version: 1 の .jin ではありません（agent は v1 の陣を呼びます）"
                    )
                agents[f"{circle.name}.{sigil.name}"] = (path, result.model)
        if not agents:
            return None
        return cls(
            agents=agents,
            fake=fake,
            extra_sys_path=list(extra_sys_path) if extra_sys_path is not None else [os.getcwd()],
        )

    def answer(self, ask: dict[str, Any]) -> str:
        """問い `{"id", "circle", "name", "prompt"}` に v1 の陣を走らせて答える（runtime.md §11）。

        問いごとに新しいセッション（state は問いをまたいで続かない）。答えは v1 のトレースの**最後のモデル応答**
        （`final` 行。root が flow で最後の行が `escalate` なら `final` は付かないので、最後の `model` 行）の
        output、無ければ `""`。正規化（改行 → 空白など）は `run_headless` が行う。

        hazard: answer -> adk_runtime.run_model
        """
        key = f"{ask.get('circle')}.{ask.get('name')}"
        try:
            path, model = self.agents[key]
        except KeyError as exc:
            raise AgentError(
                f"問い {ask.get('id')} の宛先 '{key}' は agent の sigil にありません"
            ) from exc
        prompt = str(ask.get("prompt", ""))
        try:
            result = adk_runtime.run_model(
                model,
                prompt,
                llm=FakeLlm() if self.fake else None,
                session_id=f"agent-{ask.get('id')}",
                source_name=path.name,
                extra_sys_path=self.extra_sys_path,
            )
        except RunError as exc:
            raise AgentError(f"{path}: 問い {ask.get('id')} の実行に失敗しました（{exc}）") from exc
        for row in reversed(result.rows):
            if row.kind in ("final", "model"):
                return row.output if isinstance(row.output, str) else ""
        return ""


__all__ = ["AgentError", "AgentHost", "resolve_agent_file"]
