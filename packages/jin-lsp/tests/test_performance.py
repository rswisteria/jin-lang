"""応答性（NFR-PERF-001 / 要件書 §6.4「1000 行以下のファイルで診断 1 秒以内」）と
打鍵のデバウンス（`delivery/20260904-1445-jin/check-text-benchmark.md` の人間 constraint）。

計測するのは **LSP のラウンドトリップ全体**である（`jin_core.check_text` 単体の実測は
`delivery/20260904-1445-jin/bench/bench_check_text.py` が済ませている。ここで見るのは
プロトコル・位置変換・UTF-16 換算を挟んでも 1 秒に収まること）。

`didOpen` にはデバウンスを掛けない。掛けるとこの計測にデバウンス値が混ざり、
「速いかどうか」ではなく「どれだけ待つと決めたか」を測ることになる。
"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest
import pytest_lsp
from jin_core import canonical
from jin_core.model import JinFile
from jin_lsp.server import DEBOUNCE_SECONDS, JinLanguageServer
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import SCHEMA_URL, make_client

URI = "file:///workspace/big.jin"

#: 要件書 §6.4 の上限（秒）。
BUDGET_SECONDS = 1.0


def big_document(circles: int = 58) -> str:
    """現実的な 1000 行弱の `.jin`（正準形）。

    `bench_check_text.py` のケース A と同じ形（circle 1 つ約 17 行）。
    敵対的なケース（名前 128 字 × 未解決参照多数）は**意図的に使わない**:
    そちらは 1000 行以内でも最悪 5.1 秒かかることが実測済みで、要件を満たさない
    ことも人間が判断済みである（Issue #8 / check-text-benchmark.md の「残存」）。
    """
    names = [f"C{index}" for index in range(circles)]
    body = [{"name": "Root", "flow": {"kind": "sequence", "steps": names}}]
    body += [
        {
            "name": name,
            "core": "gemini-2.5-flash",
            "instruction": {"rune": f"処理する {{s{index}}}"},
            "state": [{"name": f"s{index}", "type": "str", "out": True}],
        }
        for index, name in enumerate(names)
    ]
    return canonical.dumps(
        JinFile.model_validate(
            {"$schema": SCHEMA_URL, "version": 1, "root": "Root", "circles": body}
        )
    )


def test_the_benchmark_document_is_about_a_thousand_lines() -> None:
    """計測対象が要件の想定（1000 行以下）に収まっていること。

    生成器が壊れて 10 行になると、計測は常に緑になるが何も守らない。
    """
    lines = big_document().count("\n") + 1
    assert 800 <= lines <= 1000, lines


@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=[sys.executable, "-m", "jin_lsp"], client_factory=make_client
    ),
)
async def client(lsp_client: LanguageClient):
    await lsp_client.initialize_session(
        types.InitializeParams(capabilities=types.ClientCapabilities())
    )
    yield
    await lsp_client.shutdown_session()


@pytest.mark.asyncio
async def test_diagnostics_for_a_thousand_lines_arrive_within_a_second(
    client: LanguageClient,
) -> None:
    """machine: 1000 行の `.jin` に対する診断応答が 1 秒以内。"""
    text = big_document()
    started = time.perf_counter()
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(uri=URI, language_id="jin", version=1, text=text)
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    elapsed = time.perf_counter() - started
    assert list(client.diagnostics[URI]) == []
    assert elapsed < BUDGET_SECONDS, f"{elapsed:.3f} 秒かかった（上限 {BUDGET_SECONDS} 秒）"


# --------------------------------------------------------------------------------------
# デバウンス（check-text-benchmark.md の constraint）
# --------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_burst_of_edits_runs_the_analysis_once() -> None:
    """打鍵を連打しても診断は**最後の 1 回**だけ走る。

    「デバウンスし、古い要求をキャンセルする」（Issue #8 の人間判断）を数で固定する。
    サーバをプロセスとして起こさず、ハンドラを直接叩いて回数を数える
    （プロトコルを挟むと回数が観測できない）。
    """
    server = JinLanguageServer(debounce=0.05)
    text = big_document(circles=2)
    for version in range(1, 11):
        server.schedule_analysis(URI, text, version)
    await asyncio.sleep(0.3)
    assert server.diagnostics_runs == 1, f"{server.diagnostics_runs} 回走った（連打が積み上がった）"
    state = server.state_of(URI)
    assert state is not None and state.version == 10, "最後の版で診断していない"


@pytest.mark.asyncio
async def test_did_open_is_not_debounced() -> None:
    """`didOpen` は待たずに走る（NFR-PERF-001 の計測にデバウンス値を混ぜない）。"""
    server = JinLanguageServer(debounce=10.0)
    server.analyze_now(URI, big_document(circles=2))
    assert server.diagnostics_runs == 1


@pytest.mark.asyncio
async def test_closing_a_document_cancels_a_pending_analysis() -> None:
    """閉じたドキュメントの診断は走らせない（長寿命プロセスで無駄を残さない）。"""
    server = JinLanguageServer(debounce=0.05)
    server.schedule_analysis(URI, big_document(circles=2), 1)
    server.cancel_pending(URI)
    await asyncio.sleep(0.2)
    assert server.diagnostics_runs == 0


def test_the_debounce_value_is_the_recorded_decision() -> None:
    """デバウンス値は要件書に無い。**決めた値**を定数として固定する。

    `delivery/20260904-1445-jin/decision-conformance.md` に根拠を書いた
    （DP-IMPL-JIN-P4-DEBOUNCE-01・2026-09-07 に toyota が確定）。
    値を変えるならそちらも直す（仕様側とコード側は同じ欠陥・片方だけ直さない）。
    """
    assert DEBOUNCE_SECONDS == 0.15
