#!/bin/sh
# PostToolUse（Write / Edit）: 触ったファイルが `.jin` なら診断を出す（要件書 §8）。
#
# 標準入力に届く JSON から `tool_input.file_path` を取り出す。`jq` が無い環境でも
# 動くよう、素の sed で 1 つのキーだけを拾う（診断そのものは `jin check --json` が出す）。
#
# 出力の約束（Claude Code の hook 契約）:
# - error が 1 件でもあれば **exit 2** で stderr に診断を出し、モデルに直させる
# - error が無ければ何も出さず exit 0（成功時に喋らない）
set -eu

payload=$(cat)
file=$(printf '%s' "$payload" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')

case "$file" in
  *.jin) ;;
  *) exit 0 ;;
esac

[ -f "$file" ] || exit 0

if ! command -v jin >/dev/null 2>&1; then
  # SessionStart 側で入れ方を案内済み。ここで毎回騒がない。
  exit 0
fi

if output=$(jin check --json "$file" 2>&1); then
  exit 0
fi

printf '%s\n' "$output" >&2
printf '%s は診断エラーを含みます。上の JSON の hint に従って直してください。\n' "$file" >&2
exit 2
