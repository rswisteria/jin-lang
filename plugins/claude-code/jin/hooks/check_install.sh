#!/bin/sh
# SessionStart: `jin` が入っているか確かめ、無ければ入れ方を出す（要件書 §8）。
set -eu

if command -v jin >/dev/null 2>&1; then
  exit 0
fi

cat >&2 <<'MESSAGE'
jin コマンドが見つかりません。`.jin` の診断・定義ジャンプは jin-lsp が担うので、
先に入れてください:

    uv tool install jin-cli

リポジトリの中で開発しているなら `uv sync` のあと `uv run jin --version` で確認できます。
MESSAGE
exit 0
