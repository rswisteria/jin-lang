# ADR-016: google-adk を 2.8.0 に固定し Workflow 移行は別 Issue で扱う

> ⚠️ **AI 仮決定（ai_provisional）** — auto mode の仮判断であり人間確定ではない（DP-AUTOMODE-01）。PR レビュー後、`/decide` で approved / overridden に確定する。

- **ステータス**: proposed (ai_provisional)
- **日付**: 2026-09-05
- **決定者**: auto-decider
- **関連判断ポイント**: DP-IMPL-JIN-P2-ADKDEPRECATION-01

## コンテキスト

google-adk 2.8.0 で SequentialAgent / ParallelAgent / LoopAgent が Workflow への移行を理由に DeprecationWarning を出す（loop_agent.py:54 / sequential_agent.py:79 / parallel_agent.py:227）。ADK 自身が「Workflow cannot yet be used as an LlmAgent sub-agent」と言っており、Jin の delegate と両立しない。docs/spec/adk-mapping.md（人間確定の正典）は Sequential / Parallel / LoopAgent を指定している。

## 選択肢

| 選択肢 | 採否 |
|---|---|
| google-adk 2.8.0 固定（TARGET_ADK_VERSION）のまま進め、Workflow への移行は別 Issue で扱う | 採用 |
| 今 Workflow API を実測して adk-mapping.md を改訂する（要件書 §2.1 の対応表も変わる） | 不採用 |

## 決定

HANDOFF Q-JIN-P2-03 の推奨（1 つ目）を採用。根拠: (a) ADK 自身の deprecation 文言が「Workflow cannot yet be used as an LlmAgent sub-agent」と言っている（google/adk/agents/loop_agent.py:54 / sequential_agent.py:79・version-matrix.md §8.3 #11）。Jin の delegate（LlmAgent の sub_agents に flow circle を置く）と両立しないため、今 Workflow へ移ると要件書 §2.1 の対応表と summon / delegate の意味論が崩れる。(b) HANDOFF は Sequential / Loop を挙げるが ParallelAgent も同じ理由で deprecated（google/adk/agents/parallel_agent.py:227）であり、Jin の flow.kind 3 種すべてが対象。部分移行は成立しない。(c) docs/spec/adk-mapping.md は人間確定の正典で Sequential / Parallel / LoopAgent を指定しており、正典の改訂（案 2）は要件書 §2.1 の対応表変更を伴う人間判断が要る性質なので AI 仮判断では選ばない。(d) 版は tests/contract/test_adk_version_contract.py が 2.8.0 の厳密一致で固定しており（implementation-notes.md P2-5.1 #4・NFR-VER-001）、将来版で消えても「静かに壊れる」ことはなく契約テストで検出できる。DeprecationWarning は動作に影響しない（uv run pytest 696 passed・warnings のみ）。版固定と移行時期の方針はアーキテクチャに当たるので ADR 化する。

## 影響

TARGET_ADK_VERSION = 2.8.0 を tests/contract/test_adk_version_contract.py が厳密一致で固定する。版を上げるときは Workflow の sub-agent 可否を実測し、adk-mapping.md と要件書 §2.1 の対応表の改訂を別 Issue で扱う。生成物は 2.8.0 で動くことだけを保証する（NFR-VER-001）。
