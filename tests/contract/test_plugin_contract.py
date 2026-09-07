"""パッケージ横断契約: Claude Code プラグイン（要件書 §8 / design.yaml machine 10・11）。

> claude plugin validate が plugins/claude-code/jin に対して PASS
> skills/jin-lang/reference/ の model.md と jin.schema.json が
> docs/spec/ と schemas/ の内容と一致する（同期ドリフト検出）

`reference/` は正典のコピーである。ずれても `jin check` は通るので、**静かに効く**
（LLM が古い仕様に沿って正しく書こうとして失敗する）。バイト一致で固定する。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "plugins" / "claude-code" / "jin"
REFERENCE = PLUGIN / "skills" / "jin-lang" / "reference"
SYNC = REPO_ROOT / "scripts" / "sync_plugin_reference.py"

#: 正典 → プラグイン内のコピー（要件書 §8 のレイアウト）。
COPIES = {
    REPO_ROOT / "docs" / "spec" / "model.md": REFERENCE / "model.md",
    REPO_ROOT / "schemas" / "jin.schema.json": REFERENCE / "jin.schema.json",
}


def test_the_plugin_has_the_layout_from_the_requirements() -> None:
    """要件書 §8 が名指しするファイルが全部ある。"""
    expected = [
        ".claude-plugin/plugin.json",
        ".lsp.json",
        "skills/jin-lang/SKILL.md",
        "skills/jin-lang/reference/model.md",
        "skills/jin-lang/reference/jin.schema.json",
        "hooks/hooks.json",
        "README.md",
    ]
    missing = [name for name in expected if not (PLUGIN / name).is_file()]
    assert missing == [], missing


def test_the_lsp_config_launches_jin_lsp_for_dot_jin() -> None:
    """`.lsp.json` が要件書 §8 のとおりであること。"""
    config = json.loads((PLUGIN / ".lsp.json").read_text(encoding="utf-8"))
    assert config == {
        "jin": {
            "command": "jin",
            "args": ["lsp"],
            "extensionToLanguage": {".jin": "jin"},
        }
    }


@pytest.mark.parametrize("source", sorted(COPIES), ids=lambda p: p.name)
def test_the_reference_copy_matches_the_canonical_source(source: Path) -> None:
    """machine: `reference/` の 2 本が正典とバイト一致する。"""
    target = COPIES[source]
    assert target.read_bytes() == source.read_bytes(), (
        f"{target.relative_to(REPO_ROOT)} が古い。"
        "`uv run python scripts/sync_plugin_reference.py` を走らせてコミットすること"
    )


def test_the_reference_files_are_real_copies_not_symlinks() -> None:
    """symlink にしない。

    プラグインは `git-subdir` ソースでマーケットプレイスへ配布される（要件書 §8）。
    リポジトリの外へ持ち出された時点でリンク先が消え、SKILL.md の 1 手目
    （「reference を読む」）が壊れる。
    """
    for target in COPIES.values():
        assert not target.is_symlink(), target


def test_the_sync_script_detects_a_drift(tmp_path: Path) -> None:
    """`--check` が**実際にずれを見つける**こと（検査が存在するだけでは足りない）。

    リポジトリを触らずに確かめるため、丸ごとコピーした上で片方を汚す。
    """
    work = tmp_path / "repo"
    work.mkdir()
    for relative in ("scripts", "docs/spec", "schemas", "plugins"):
        source = REPO_ROOT / relative
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)

    script = work / "scripts" / "sync_plugin_reference.py"
    clean = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True, check=False
    )
    assert clean.returncode == 0, clean.stderr

    stale = work / "plugins" / "claude-code" / "jin" / "skills" / "jin-lang" / "reference"
    (stale / "model.md").write_text("古い写し\n", encoding="utf-8")
    dirty = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True, check=False
    )
    assert dirty.returncode == 1, "ずれているのに --check が通った"
    assert "model.md" in dirty.stderr

    # 同期し直すと通るようになること（生成器が実際に直せる）。
    fixed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert fixed.returncode == 0, fixed.stderr
    again = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True, check=False
    )
    assert again.returncode == 0, again.stderr


def test_the_hooks_run_jin_check_on_dot_jin_writes() -> None:
    """`PostToolUse`（Write / Edit）で `jin check` を走らせる（要件書 §8）。"""
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    matchers = [entry["matcher"] for entry in hooks["hooks"]["PostToolUse"]]
    assert matchers == ["Write|Edit"]
    assert "SessionStart" in hooks["hooks"]


@pytest.mark.parametrize("name", ["check_jin.sh", "check_install.sh"])
def test_the_hook_scripts_are_executable(name: str) -> None:
    """hook のスクリプトに実行ビットが立っていること。

    立っていないと Claude Code は `Permission denied` で静かに失敗する
    （hook の失敗はセッションを止めない）。git は実行ビットを保持する。
    """
    mode = (PLUGIN / "hooks" / name).stat().st_mode
    assert mode & stat.S_IXUSR, f"{name} に実行ビットが無い"


@pytest.mark.parametrize("name", ["check_jin.sh", "check_install.sh"])
def test_the_hook_scripts_pass_a_shell_syntax_check(name: str) -> None:
    """`sh -n` で構文を見る（hook は壊れていても静かなので、ここで落とす）。"""
    completed = subprocess.run(
        ["sh", "-n", str(PLUGIN / "hooks" / name)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_the_skill_tells_the_model_to_read_the_reference_first() -> None:
    """SKILL.md の 1 手目が「reference を読む」であること（要件書 §8）。

    ここが崩れると、LLM は記憶でキー名を書き始める。
    """
    body = (PLUGIN / "skills" / "jin-lang" / "SKILL.md").read_text(encoding="utf-8")
    assert body.startswith("---"), "frontmatter が無い"
    assert "reference/jin.schema.json" in body
    assert "reference/model.md" in body
    assert "記憶で書かない" in body
    # 要件書 §8「例は 2 つだけ載せ、仕様は reference を参照させる」
    assert body.count("```json") == 2, "例は 2 つだけ（要件書 §8）"


CLAUDE_CLI = shutil.which("claude")


@pytest.mark.skipif(CLAUDE_CLI is None, reason="claude CLI が無い環境（CI の test job を含む）")
def test_claude_plugin_validate_passes() -> None:
    """machine: `claude plugin validate` が PASS すること。

    **このテスト自体は CI の `test` job では skip される**（ubuntu-latest の Python 環境に
    `claude` CLI を入れていないため。2026-09-07 の実機 CI で 1 skipped として実測）。
    CI で validate を実際に走らせるのは専用の `plugin` job のほうであり
    （`.github/workflows/ci.yml`・Node + `@anthropic-ai/claude-code`）、
    その job が存在し続けることは `test_ci_contract.py` が固定する。
    ここは `claude` を持っている手元で同じ検査を回すための入口である。
    """
    assert CLAUDE_CLI is not None
    completed = subprocess.run(
        [CLAUDE_CLI, "plugin", "validate", str(PLUGIN)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CI": "1"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
