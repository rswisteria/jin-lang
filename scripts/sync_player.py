"""`apps/player/dist/` のビルド物を `packages/jin-wasm/src/jin_wasm/player/` に同梱する（runtime.md §9）。

`jin build`（v2）は `jin_wasm/player/` に `index.html` / `player.js` / `wasmoon.wasm` の 3 つが揃って
いるときだけ、それらを `<out>/` に一緒に書く（`--single` はこの 3 つを `index.html` 1 本に埋める）。
同梱先は **gitignore**（ビルド物をコミットしない。`prelude.lua` と同じくパッケージディレクトリの
中にあるので wheel には入る）。

使い方:

    cd apps/player && pnpm install && pnpm build       # ビルド物を作る
    uv run python scripts/sync_player.py               # 同梱する（3 ファイルをバイトごと複製）
    uv run python scripts/sync_player.py --check       # 同梱がビルド物とずれていたら exit 1
    uv run python scripts/sync_player.py --remove      # 同梱を外す（プレイヤー無しの振る舞いを試す）

CI の player ジョブは `pnpm build` → `sync_player.py` → `jin build --single` の実プロセスを回す。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYER_DIST = REPO_ROOT / "apps" / "player" / "dist"
TARGET = REPO_ROOT / "packages" / "jin-wasm" / "src" / "jin_wasm" / "player"
#: `jin_wasm.bundle.PLAYER_FILES` と同じ 3 つ（このスクリプトは jin_wasm を import しない。
#: `uv run` の外でも動くように）。ずれは `tests/contract/test_player_contract.py` が見る。
PLAYER_FILES = ("index.html", "player.js", "wasmoon.wasm")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="書き換えず、ずれていたら exit 1")
    group.add_argument("--remove", action="store_true", help="同梱を外す")
    args = parser.parse_args(argv)

    if args.remove:
        if TARGET.is_dir():
            shutil.rmtree(TARGET)
            print(f"外しました: {TARGET.relative_to(REPO_ROOT)}/")
        return 0

    missing = [name for name in PLAYER_FILES if not (PLAYER_DIST / name).is_file()]
    if missing:
        print(
            f"{PLAYER_DIST.relative_to(REPO_ROOT)}/ に {' / '.join(missing)} がありません。"
            "先に `cd apps/player && pnpm install && pnpm build` を実行してください",
            file=sys.stderr,
        )
        return 1

    stale: list[str] = []
    for name in PLAYER_FILES:
        content = (PLAYER_DIST / name).read_bytes()
        target = TARGET / name
        if target.is_file() and target.read_bytes() == content:
            continue
        if args.check:
            stale.append(
                f"{target.relative_to(REPO_ROOT)} が {PLAYER_DIST.relative_to(REPO_ROOT)}/{name} と違う"
            )
            continue
        TARGET.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"同梱しました: {target.relative_to(REPO_ROOT)}")

    if stale:
        for line in stale:
            print(line, file=sys.stderr)
        print("`uv run python scripts/sync_player.py` を走らせてください", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
