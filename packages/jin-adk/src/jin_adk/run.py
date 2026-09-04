"""`jin run <file> "<prompt>"` の本体（要件書 §3.4）。

「生成コードを一時ディレクトリに書き出して import し、`Runner` + `InMemorySessionService`
で実行、イベントを標準出力に流す」。実測（`adk-api-probe.md`）どおり `Runner` は
**全キーワード引数**で `session_service` が必須。

`--model fake` は `BaseLlm` を継承した `FakeLlm` に差し替える（`jin_adk.fake_llm`）。
**生成物には現れない**（ADR-008）。
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jin_core.model import JinFile

from jin_adk.codegen import GeneratedProject
from jin_adk.fake_llm import DEFAULT_RESPONSE, install_fake_llm
from jin_adk.loader import load_root_agent
from jin_adk.project import write_project
from jin_adk.trace import TraceBuilder, TraceEvent


def initial_state(model: JinFile) -> dict[str, str]:
    """`state[]` の宣言から初期セッション状態を作る（要件書 §2.1「state[] → session.state」）。

    値は**空文字**にする。`state[].type` は自由記述の文字列（`"str"` / `"bool"` …）で、
    Jin は型を解釈しないので、型ごとのゼロ値を当てると要件書に無い値を捏造することになる。
    「まだ生成されていない」ことを表すのに空文字がいちばん近い。

    なぜ必要か（google-adk 2.8.0 実測）: ADK の instruction テンプレート展開
    （`google/adk/utils/instructions_utils.py` の `_replace_match`）は、
    `{key}` の `key` が `session.state` に**無い**と `KeyError` を投げる。
    examples/researcher の rune は自分の `output_key` である `{findings}` を参照するので、
    1 ターン目は必ずそこで落ちる。

    **これは `jin run` だけの手当てである。** 要件書 §3.3 は「`out: true` 以外の `state[]` は
    静的検証とエディタ表示のための宣言」と定めているので、生成コードには何も出さない。
    その結果 `adk run <out>/<root_name>` は空のセッションで始まり、同じ `KeyError` に当たる。
    要件書 §2.1（`{state_key}` テンプレートは透過）と §3.3 のどちらを曲げるかは
    仕様側の判断なので実装者が決めない。未決として
    `delivery/20260904-1445-jin/implementation-plan.json` の `undecided[]` /
    `undecided_details[]` に `DP-JIN-STATE-SEED-01` で起票してある
    （`docs/pending-decisions.md` は自動生成なので親の再生成待ち）。
    """
    return {state.name: "" for circle in model.circles for state in circle.state}


#: `Runner` に渡す既定の利用者 ID。`InMemorySessionService` は永続化しないので、
#: 値そのものに意味は無い。**`user` は ADK の予約語**（agent 名として）だが、
#: `user_id` は別空間なのでそのまま使ってよい（実測: 制約は agent 名にだけ掛かる）。
DEFAULT_USER_ID = "jin"


@dataclass(frozen=True, slots=True)
class RunResult:
    """1 回の実行の結果。"""

    project: GeneratedProject
    trace: list[TraceEvent]
    #: `--model fake` で差し替えたエージェント名（空なら差し替えていない）。
    faked_agents: list[str]


def run(
    model: JinFile,
    prompt: str,
    *,
    source_dir: Path | None = None,
    session_id: str | None = None,
    use_fake_model: bool = False,
    fake_response: str = DEFAULT_RESPONSE,
    on_event: Callable[[TraceEvent], None] | None = None,
) -> RunResult:
    """同期の入口。CLI はここだけを呼ぶ。

    `source_dir` は `.jin` が置かれたディレクトリ。`tools[].ref` が指すユーザの
    パッケージは普通そこにあるので `sys.path` に足す（`jin_adk.loader` の docstring）。

    **`import` はユーザのコードを実行する。** `jin run` は実行するためのコマンドなので
    それが目的だが、`.jin` の出どころは利用者が確かめること（CLI の `--help` に明記）。
    """
    return asyncio.run(
        _run_async(
            model,
            prompt,
            source_dir=source_dir,
            session_id=session_id,
            use_fake_model=use_fake_model,
            fake_response=fake_response,
            on_event=on_event,
        )
    )


async def _run_async(
    model: JinFile,
    prompt: str,
    *,
    source_dir: Path | None,
    session_id: str | None,
    use_fake_model: bool,
    fake_response: str,
    on_event: Callable[[TraceEvent], None] | None,
) -> RunResult:
    # ADK は import が重い（数秒）。`jin check` / `jin build` に負担を掛けないよう
    # 実行するときにだけ読む。
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    with tempfile.TemporaryDirectory(prefix="jin-run-") as temporary:
        out = Path(temporary)
        project = write_project(model, out)
        root_agent = load_root_agent(
            out, project.root_name, extra_paths=[source_dir] if source_dir else []
        )

        faked = install_fake_llm(root_agent, fake_response) if use_fake_model else []

        session_service = InMemorySessionService()
        session = await session_service.create_session(
            app_name=project.root_name,
            user_id=DEFAULT_USER_ID,
            session_id=session_id,
            state=initial_state(model),
        )
        runner = Runner(
            app_name=project.root_name,
            agent=root_agent,
            session_service=session_service,
        )

        builder = TraceBuilder(
            project.pointer_map,
            model_of={c.name: c.core for c in model.circles if c.core is not None},
        )
        trace: list[TraceEvent] = []
        async for event in runner.run_async(
            user_id=DEFAULT_USER_ID,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            for line in builder.events_from(event):
                trace.append(line)
                if on_event is not None:
                    on_event(line)
        return RunResult(project=project, trace=trace, faked_agents=faked)


__all__ = ["DEFAULT_USER_ID", "RunResult", "initial_state", "run"]
