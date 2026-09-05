"""パッケージ横断契約: 生成コードが前提にする google-adk の版と、実際に入っている版の一致（NFR-VER-001）。

テンプレートの引数名（`max_iterations` / `session_service` 必須 / `EventActions.escalate` …）は
`delivery/20260904-1445-jin/adk-api-probe.md` の **2.8.0 実測**に固定してある。
`uv.lock` が別の版を解決するようになった瞬間にここが赤くなり、「probe を取り直してテンプレートを
見直し、`jin_adk.TARGET_ADK_VERSION` を更新する」手順へ誘導する。
"""

from __future__ import annotations

import ast
from importlib.metadata import version
from pathlib import Path

from jin_adk import TARGET_ADK_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
ADK_SRC = REPO_ROOT / "packages" / "jin-adk" / "src" / "jin_adk"


def test_installed_google_adk_matches_the_version_the_templates_were_probed_against() -> None:
    assert version("google-adk") == TARGET_ADK_VERSION, (
        f"google-adk {version('google-adk')} が入っているが、テンプレートは {TARGET_ADK_VERSION} の"
        "実測に固定されている。adk-api-probe.md を取り直してから TARGET_ADK_VERSION を更新すること"
    )


def test_probe_document_records_the_same_version() -> None:
    probe = (REPO_ROOT / "delivery" / "20260904-1445-jin" / "adk-api-probe.md").read_text(
        encoding="utf-8"
    )
    # PyPI 表の行に絞る（`"2.8.0" in probe` は文書のどこにでも当たって空虚になる）
    assert f"| google-adk | {TARGET_ADK_VERSION} |" in probe


def test_jin_adk_does_not_import_jin_cli_or_later_packages() -> None:
    """design.yaml rules 3: jin-adk は jin-core に依存する。jin-render / jin-lsp / jin-cli に依存しない。

    import-linter とは独立した二重の網（`tests/contract/test_dependency_direction.py` と同型）。
    """
    for path in sorted(ADK_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(("jin_cli", "jin_render", "jin_lsp")), f"{path}: {name}"
