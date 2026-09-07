"""`plugins/claude-code/jin/skills/jin-lang/reference/` を正典から同期する（要件書 §8）。

SKILL.md は「`reference/jin.schema.json` と `model.md` を読む」から始めろと書いている。
その 2 本が古ければ、LLM は**古い仕様に沿って正しく書こうとして失敗する**。しかも
`jin check` は通ってしまうことがあるので、ずれは静かに効く。

コピーであって symlink ではない。プラグインは `git-subdir` ソースでマーケットプレイスに
配布される（要件書 §8）ので、リポジトリの外へ持ち出された時点でリンク先が消える。

使い方:

    uv run python scripts/sync_plugin_reference.py          # 同期する
    uv run python scripts/sync_plugin_reference.py --check   # ずれていたら exit 1

`--check` は CI が走らせる。ずれは `tests/contract/test_plugin_contract.py` も
バイト一致で落とす（生成器とテストの二重の網）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = REPO_ROOT / "plugins" / "claude-code" / "jin" / "skills" / "jin-lang" / "reference"

#: コピー元 → コピー先。**ここに足したら `test_plugin_contract.py` の期待も足す。**
SOURCES: dict[Path, Path] = {
    REPO_ROOT / "docs" / "spec" / "model.md": REFERENCE / "model.md",
    REPO_ROOT / "schemas" / "jin.schema.json": REFERENCE / "jin.schema.json",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="書き換えず、ずれていたら exit 1")
    args = parser.parse_args(argv)

    stale: list[str] = []
    for source, target in SOURCES.items():
        content = source.read_bytes()
        current = target.read_bytes() if target.is_file() else None
        if current == content:
            continue
        if args.check:
            stale.append(
                f"{target.relative_to(REPO_ROOT)} が {source.relative_to(REPO_ROOT)} と違う"
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"同期しました: {target.relative_to(REPO_ROOT)}")

    if stale:
        for line in stale:
            print(line, file=sys.stderr)
        print(
            "`uv run python scripts/sync_plugin_reference.py` を走らせてコミットしてください",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
