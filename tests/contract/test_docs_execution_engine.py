"""`docs/execution-engine.md`（実行エンジンの実装の地図）が実装から離れたら気づく。

この文書は正典ではなく、`tests/spec/` の突合の網の外にある。せめて名指しするファイルが消えたら赤くし、
すぐ腐る行番号の参照（`foo.py:123`）を書かない規律を機械で固定する。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "execution-engine.md"

#: 本文が名指しするリポジトリ内のパス（`docs/spec/…` のような相対リンクは `spec/` から始まるので別に見る）。
_PATH = re.compile(r"(?<![\w/.-])((?:packages|apps|scripts|tests|schemas|docs)/[\w./*-]+)")
_LINK = re.compile(r"\]\(([^)#]+?)(?:#[^)]*)?\)")
#: ビルドの出力（gitignore）。CI の Python ジョブには無いので実在を問わない。
_BUILD_OUTPUTS = frozenset({"apps/player/dist"})
_LINE_REF = re.compile(r"\.(?:py|ts|tsx|lua|wat|md|json)[:#]L?\d+")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_every_repository_path_named_in_the_document_exists() -> None:
    paths = {p.rstrip(".") for p in _PATH.findall(_text())} - _BUILD_OUTPUTS
    assert len(paths) >= 20, f"パスの抜き出しが壊れている: {sorted(paths)}"
    missing = sorted(
        p for p in paths if not (any(REPO_ROOT.glob(p)) if "*" in p else (REPO_ROOT / p).exists())
    )
    assert not missing, f"文書が名指しするパスが無い: {missing}"


def test_every_relative_link_resolves() -> None:
    links = [link for link in _LINK.findall(_text()) if "://" not in link]
    assert links, "相対リンクを 1 つも拾えていない"
    missing = sorted(link for link in links if not (DOC.parent / link).exists())
    assert not missing, f"リンク先が無い: {missing}"


def test_the_document_does_not_cite_line_numbers() -> None:
    found = _LINE_REF.findall(_text())
    assert not found, f"行番号の参照は腐るので記号名で書く: {found}"
