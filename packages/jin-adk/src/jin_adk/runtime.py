"""`jin run`: 生成コードを一時ディレクトリへ書いて import し、`Runner` で実行する（要件書 §3.4）。

## これは任意コード実行である

生成コードは `.jin` の `ref` が指すモジュールを `from research.tools import web_search` の形で
**実際に import する**。Python の import はモジュールのトップレベルを実行するので、
`jin run` は `jin check --resolve` と同じく「`.jin` を書いた相手にこのプロセスの権限で任意の
コードを実行させる」操作である（CLAUDE.md「`--resolve` と `jin run` の危険性」）。

- 動的 import（`importlib` / `__import__` / `exec` / `eval` / `runpy`）を使う jin の実装は
  `jin_cli.resolver`（`--resolve`）と**このモジュール**の 2 つだけ
  （`tests/contract/test_packaging_contract.py` が厳密一致で固定）。`jin_core` / `jin_lsp` には置かない
- 一時ディレクトリは `tempfile.mkdtemp`（所有者だけが読める 0700）に作り、終了時に必ず消す
  （消せなかったときは stderr に 1 行出す。黙らない・F-W-P2-008）
- 生成コードの **import 中**の例外は `KeyboardInterrupt` 以外の `BaseException` まで捕まえて
  `RunError` にする（`sys.exit(0)` で成功扱いにしない・Phase 1 の S2 と同型）
- **実行中**（Runner の中のツール関数）の `sys.exit(0)` は asyncio が `SystemExit` をタスクの結果に
  せず**ループの外へ再送出する**ので、コルーチン側の `except BaseException` では捕まらない
  （そこに来るのは `CancelledError` だけ）。同期 `run_model` と CLI が `asyncio.run` を包んで
  `RunError` / exit 1 にする（F-S-P2-102・修正ラウンド 1 の回帰）。`run_model_async` を自前の
  ループで回す呼び出し側（Phase 4 の pygls）は同じ包みを自分で持つこと
- **ツール由来の cancel も成功扱いにしない**（F-S-P2-201 / 202）。ツール関数が `asyncio.CancelledError` を
  投げると、root が LlmAgent のときは ADK の `_cleanup_root_task` が root の cancel を warning で握って
  **正常復帰**する（`jin run` が exit 0・「1 イベント」に見える = `sys.exit(0)` と同型の fail-open）。
  root が workflow agent のときは `CancelledError` が Runner から外へ出る。対策は 2 段:
  (1) Runner 完走後、**応答が無い function_call** のうち `Event.long_running_tool_ids`（`boundary.await` の
  正規 pause）に無いものがあれば `RunError`（`_unanswered`）。(2) `run_model_async` に届いた `CancelledError` は
  `asyncio.current_task().cancelling()` で区別し、shutdown 由来（`SystemExit` / `KeyboardInterrupt` の巻き添え・
  外からの `task.cancel()`）なら再送出、ツール由来（0）なら `RunError`。CLI と同期 `run_model` にも保険の
  `except CancelledError` → 1 行・exit 1
- `sys.path` は `extra_sys_path` で頼まれた項目を**生成モジュールの import の間だけ**末尾に足し、
  import が終わったら（例外時も）`finally` で必ず取り除く（`_sys_path_window`）。Runner 実行中は
  cwd が `sys.path` に無い（DP-IMPL-JIN-P2-SYSPATH-01 の再々判断・F-S-P2-101）。頼まれなければ触らない

`guard:` は防御の所在、`hazard:` は**危険な操作の所在**（防御ではない。読み手が防御と誤読しないための
別タグ・F-S-P2-010）。検査は `tests/contract/test_guard_claims.py` が両タグを同じ規則で照合する。

    guard: load_generated -> tempfile.mkdtemp
    guard: load_generated -> shutil.rmtree
    hazard: _import_agent_module -> importlib.util.spec_from_file_location
    hazard: _sys_path_window -> sys.path.append
    guard: _sys_path_window -> sys.path.remove

## FakeLlm の差し替え（ADR-008）

生成物は FakeLlm を知らない。`swap_models` が import 後の agent 木（`sub_agents` /
`AgentTool.agent`）を走査し、`LlmAgent.model` を差し替える。StateCheckAgent（BaseAgent）は触らない。

## 宣言済み state の seed

実測（google-adk 2.8.0）: `instruction` の `{key}` が session.state に無いと ADK は `KeyError` を
投げて実行が落ちる（`google/adk/utils/instructions_utils.py:174`）。`examples/researcher` の
`{findings}` は自分の `output_key` なので初回は必ず未設定になる。`jin run` は `.jin` が宣言した
全 circle の `state[].name` を **`None` で seed** する（ADK は None を空文字で描画する・実測）。
これは `jin run` の挙動であり、生成物を `adk run` で単体実行したときには効かない
（`docs/spec/adk-mapping.md` §6）。
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import shutil
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.models import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import BaseTool
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
from jin_core.model import JinFile

from jin_adk.build import write_project
from jin_adk.codegen import GeneratedProject, generate
from jin_adk.trace import TRANSFER_TOOL_NAME, RuntimeTable, TraceRow, TraceSink, TraceWriter


class RunError(Exception):
    """生成コードの import / 実行に失敗した（利用者向けの文で伝える。トレースバックは出さない）。"""


@dataclass(frozen=True)
class RunResult:
    rows: list[TraceRow]
    final_state: dict[str, Any]
    unresolved: list[str]


def _import_agent_module(path: Path) -> ModuleType:
    """`agent.py` を一意なモジュール名で import する。

    `root_name` をそのままモジュール名にすると `json` のような名前で `sys.modules` を汚す。
    `sys.path` は触らない（生成コード自身の import は呼び出し側の `sys.path` で解決される。
    cwd を足したいなら `load_generated` の `extra_sys_path` に渡し、`_sys_path_window` に任せる）。

    hazard: _import_agent_module -> importlib.util.spec_from_file_location
    """
    name = f"_jin_run_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 自分で書いたファイル
        raise RunError(f"生成コードを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        sys.modules.pop(name, None)
        raise RunError(
            f"生成コードの import に失敗しました（{type(exc).__name__}: {exc}）。"
            "ref が指すモジュールが cwd / PYTHONPATH から import できるか確認してください"
        ) from exc
    return module


def _report_cleanup_failure(_func: object, path: str, exc: BaseException) -> None:
    """一時ディレクトリを消せなかったことを stderr に出す（`RunError` にはしない）。"""
    print(f"一時ディレクトリを消せませんでした: {path}（{exc}）", file=sys.stderr)


@contextlib.contextmanager
def _sys_path_window(extra_sys_path: Sequence[str]) -> Iterator[None]:
    """import 窓: `extra_sys_path` を `sys.path` の**末尾**に足し、抜けるとき（例外時も）必ず取り除く。

    元から `sys.path` にある値は足さないし取り除かない（呼び出し側の環境を壊さない）。
    窓の中で `ref` 先のモジュールが import され `sys.modules` に残るので、Runner 実行中に
    cwd が `sys.path` に無くてもツール関数は動く。**残存**: ref 先の関数が自分の中で実行時に
    遅延 import する名前は cwd から解決できない（PYTHONPATH に委ねる）。窓の中では
    `google.adk.tools` の遅延 import が未インストールの任意依存（`mcp` など）を cwd から探す
    経路が残る（builtin を書くのは `.jin` 作者）。

    hazard: _sys_path_window -> sys.path.append
    guard: _sys_path_window -> sys.path.remove
    """
    added = [entry for entry in extra_sys_path if entry not in sys.path]
    for entry in added:
        sys.path.append(entry)
    try:
        yield
    finally:
        for entry in added:
            with contextlib.suppress(ValueError):
                sys.path.remove(entry)


@contextlib.contextmanager
def load_generated(
    project: GeneratedProject, *, extra_sys_path: Sequence[str] = ()
) -> Iterator[ModuleType]:
    """一時ディレクトリに書いて import し、抜けるときに消す。

    `extra_sys_path` は**生成モジュールの import の間だけ** `sys.path` の末尾に足す
    （CLI は cwd を渡す）。`yield` の時点では取り除かれている。

    guard: load_generated -> tempfile.mkdtemp
    guard: load_generated -> shutil.rmtree
    """
    directory = tempfile.mkdtemp(prefix="jin-run-")
    module: ModuleType | None = None
    try:
        write_project(project, Path(directory))
        with _sys_path_window(extra_sys_path):
            module = _import_agent_module(Path(directory) / project.root_name / "agent.py")
        yield module
    finally:
        if module is not None:
            sys.modules.pop(module.__name__, None)
        shutil.rmtree(directory, onexc=_report_cleanup_failure)


def _walk(agent: BaseAgent, seen: set[int]) -> Iterator[BaseAgent]:
    if id(agent) in seen:
        return
    seen.add(id(agent))
    yield agent
    for child in agent.sub_agents:
        yield from _walk(child, seen)
    if isinstance(agent, LlmAgent):
        for tool in agent.tools:
            if isinstance(tool, AgentTool):
                yield from _walk(tool.agent, seen)


def swap_models(root: BaseAgent, llm: BaseLlm) -> list[str]:
    """木の中の全 `LlmAgent.model` を `llm` に差し替え、差し替えた agent 名を返す。"""
    swapped: list[str] = []
    for agent in _walk(root, set()):
        if isinstance(agent, LlmAgent):
            agent.model = llm
            swapped.append(agent.name)
    return swapped


def _tool_name(tool: object) -> str:
    if isinstance(tool, BaseTool):
        return tool.name
    return getattr(tool, "__name__", type(tool).__name__)


def bind_runtime_table(project: GeneratedProject, root: BaseAgent) -> RuntimeTable:
    table = RuntimeTable.from_pointer_map(project.pointers)
    for agent in _walk(root, set()):
        if isinstance(agent, LlmAgent):
            table.bind_tools(agent.name, [_tool_name(t) for t in agent.tools])
    return table


def _declared_state(model: JinFile) -> dict[str, Any]:
    return {state.name: None for circle in model.circles for state in circle.state}


async def _run_async(
    root: BaseAgent,
    writer: TraceWriter,
    *,
    prompt: str,
    initial_state: dict[str, Any],
    session_id: str,
    user_id: str,
) -> dict[str, Any]:
    service = InMemorySessionService()
    app_name = root.name
    await service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id, state=initial_state
    )
    runner = Runner(agent=root, app_name=app_name, session_service=service)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    pending: dict[str, str] = {}  # function_call の id → ツール名（応答が来たら消す）
    long_running: set[str] = set()  # `await` 対象（LongRunningFunctionTool）の function_call id
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        writer.push(event)
        for call in event.get_function_calls():
            if call.id and call.name != TRANSFER_TOOL_NAME:
                pending[call.id] = call.name or ""
        for response in event.get_function_responses():
            if response.id:
                pending.pop(response.id, None)
        long_running.update(event.long_running_tool_ids or ())
    writer.close()
    session = await service.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    state = dict(session.state) if session is not None else {}
    return state, _unanswered(pending, long_running)


def _unanswered(pending: dict[str, str], long_running: set[str]) -> list[str]:
    """応答が返らなかった function_call のツール名（`await` の正規 pause は除く）。

    F-S-P2-201: ツール関数が `asyncio.CancelledError` を投げると、root が LlmAgent のとき ADK は root の
    cancel を握って正常復帰し、トレースは「呼び出し行だけ」で終わる。この形は `boundary.await` の
    LongRunningFunctionTool が `None` を返す正規の pause と同じなので、`Event.long_running_tool_ids`
    に無い呼び出しだけを「応答を返さずに終了した」とみなす（誤検知しない）。
    """
    return [name for call_id, name in pending.items() if call_id not in long_running]


async def run_model_async(
    model: JinFile,
    prompt: str,
    *,
    project: GeneratedProject | None = None,
    llm: BaseLlm | None = None,
    session_id: str = "jin",
    user_id: str = "user",
    source_name: str | None = None,
    trace_sink: TraceSink | None = None,
    on_row: Callable[[TraceRow], None] | None = None,
    extra_sys_path: Sequence[str] = (),
) -> RunResult:
    """`.jin` を生成 → import → 実行し、トレース行を返す（async 版・稼働中のイベントループから呼べる）。

    **`SystemExit` は捕まえない（捕まえられない）。** ツール関数の `sys.exit()` は asyncio が
    タスクの結果にせずループの外へ再送出し、この関数には `CancelledError` しか届かない。
    `asyncio.run` を呼ぶ側（同期 `run_model`・CLI の `run`・Phase 4 の pygls）が
    `except SystemExit` で包んで失敗扱いにすること（F-S-P2-102）。

    `project` を渡すと生成をスキップする（CLI は `--trace` を開く**前**に `generate()` を済ませ、
    `BuildError` で既存トレースを失わないようにする・F-S-P2-006）。
    `llm` を渡すと全 LlmAgent の model を差し替える（`--model fake` → `FakeLlm()`）。
    渡さなければ `.jin` の `core` のモデルをそのまま使う（API キーが要る・human_only）。
    `session_id` はトレース表示用のラベルで、`InMemorySessionService` は呼び出しごとに新しく作る
    （state は次の呼び出しへ引き継がれない・`docs/spec/adk-mapping.md` §6）。
    `extra_sys_path` は生成モジュールの import の間だけ `sys.path` に足す（`load_generated`）。

    ツール由来の `asyncio.CancelledError` は成功扱いにしない（F-S-P2-201 / 202）: Runner 完走後に応答の無い
    function_call（`await` の pause を除く）があれば `RunError`、Runner から出てきた `CancelledError` は
    `Task.cancelling()` が 0（外からのキャンセルでも shutdown でもない）なら `RunError`。
    """
    if project is None:
        project = generate(model, source_name=source_name)
    with load_generated(project, extra_sys_path=extra_sys_path) as module:
        root = module.root_agent
        if llm is not None:
            swap_models(root, llm)
        table = bind_runtime_table(project, root)
        writer = TraceWriter(table, sink=trace_sink, on_row=on_row)
        try:
            final_state, unanswered = await _run_async(
                root,
                writer,
                prompt=prompt,
                initial_state=_declared_state(model),
                session_id=session_id,
                user_id=user_id,
            )
        except KeyboardInterrupt:
            writer.close()
            raise
        except asyncio.CancelledError as exc:
            writer.close()
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                # shutdown 由来（SystemExit / KeyboardInterrupt の巻き添え）か外からの task.cancel()。
                # ここで RunError にすると shutdown 中の未処理例外としてトレースバックが漏れる
                raise
            # ツール由来（F-S-P2-202: workflow agent 配下では Runner から素通りしてくる）
            raise RunError(
                "実行に失敗しました（CancelledError: ref の関数が asyncio.CancelledError を投げました）。"
                "--trace で直前のイベントを確認し、関数側を直してください"
            ) from exc
        except BaseException as exc:
            writer.close()
            raise RunError(
                f"実行に失敗しました（{type(exc).__name__}: {exc}）。"
                "--trace で直前のイベントを確認し、ref の関数の例外なら関数側を直してください"
            ) from exc
    if unanswered:
        # F-S-P2-201: root が LlmAgent のとき ADK は root の cancel を握って正常復帰する
        names = " / ".join(f"'{name}'" for name in unanswered)
        raise RunError(
            f"ツール {names} が応答を返さずに実行が終了しました（キャンセルされた可能性。"
            "ref の関数が asyncio.CancelledError を投げていないか確認してください）"
        )
    return RunResult(rows=writer.rows, final_state=final_state, unresolved=list(table.unresolved))


def run_model(model: JinFile, prompt: str, **kwargs: Any) -> RunResult:
    """`run_model_async` の同期の包み。**イベントループが動いていない**呼び出し側（テスト・スクリプト）用。

    pygls（Phase 4）や notebook のようにループが稼働している場所では `asyncio.run` が
    `RuntimeError` になるので `run_model_async` を使う（F-C-P2-019）。

    ツール関数の `sys.exit()` は `asyncio.run` の外へ `SystemExit` として出てくるので、ここで
    `RunError` にする（`sys.exit(0)` で成功扱いにしない・F-S-P2-102）。`KeyboardInterrupt` は通す。
    """
    try:
        return asyncio.run(run_model_async(model, prompt, **kwargs))
    except KeyboardInterrupt:
        raise
    except asyncio.CancelledError as exc:
        # 保険（F-S-P2-202）: run_model_async が区別できなかった CancelledError も失敗扱い
        raise RunError(
            "実行がキャンセルされました（ref の関数が asyncio.CancelledError を投げた可能性）"
        ) from exc
    except SystemExit as exc:
        raise RunError(
            f"実行に失敗しました（SystemExit: {exc.code}）。"
            "ref の関数が sys.exit() を呼んでいます。関数側を直してください"
        ) from exc


__all__ = [
    "RunError",
    "RunResult",
    "bind_runtime_table",
    "load_generated",
    "run_model",
    "run_model_async",
    "swap_models",
]
