# jin — Claude Code プラグイン

Jin(陣) の `.jin` を Claude Code で書くためのプラグイン（要件書 §8）。

## 何が入るか

| 中身 | 役割 |
|---|---|
| `.lsp.json` | `jin lsp`（stdio）を言語サーバとして登録する。`.jin` の診断・定義ジャンプ・補完が効く |
| `skills/jin-lang/SKILL.md` | `.jin` を書く手順。仕様は `reference/` を読ませる |
| `skills/jin-lang/reference/` | `docs/spec/model.md` と `schemas/jin.schema.json` の**コピー**（下記） |
| `hooks/hooks.json` | `Write` / `Edit` で `.jin` を触ったら `jin check --json` を走らせる。`SessionStart` で `jin` の有無を見る |

## 前提

`jin` コマンドが PATH にあること。

```bash
uv tool install jin-cli
```

リポジトリの中で開発しているなら `uv sync` のあと `uv run jin --version` で確認できる。

## reference/ は生成物である

`reference/model.md` と `reference/jin.schema.json` はリポジトリの
`docs/spec/model.md` / `schemas/jin.schema.json` の**コピー**で、
`scripts/sync_plugin_reference.py` が同期する。**手で編集しない。**

```bash
uv run python scripts/sync_plugin_reference.py        # 同期する
uv run python scripts/sync_plugin_reference.py --check # ずれていたら exit 1（CI が走らせる）
```

ずれは `tests/contract/test_plugin_contract.py` が**バイト一致**で落とす。

## 注記（要件書 §8）

現状の Claude Code の LSP 連携は診断・定義ジャンプ・参照といった読み取り系が中心で、
`jin/applyOps` のような独自リクエストをモデル側から呼ぶ経路は無い。
LLM はテキストを直接編集し、診断で修正するのが v1 の前提である。
意味オペレーションを LLM からも使わせたくなった場合は、同じ `jin_core.ops` を
MCP サーバとして露出する（v1.1 候補）。
