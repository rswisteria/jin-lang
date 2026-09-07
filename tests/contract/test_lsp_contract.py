"""パッケージ横断契約: LSP の出力が CLI の出力とバイト一致すること（design.yaml machine 5・6）。

> formatting の出力が `jin fmt` の出力とバイト一致する
> `jin/renderSvg` の出力が `jin render` の出力とバイト一致する

要件書 §6 が「CLI・Claude Code・VS Code・視覚エディタの全てが `jin_core` の同じ関数を
LSP 経由で使う」と定めている以上、この 2 つが食い違うことは**あってはならない**。
片方だけを見るテストでは食い違いを検出できないので、**実際に両方を別プロセスで動かして**
バイト列を突き合わせる。

`packages/jin-lsp/tests/` からは `jin_cli` を import できない（layers 契約）ので、
この突合はここにしか置けない（`tests/contract/test_render_contract.py` と同じ理由）。
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from lsprotocol import types
from pytest_lsp import ClientServerConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
JIN = Path(sys.executable).parent / "jin"
LSP_SRC = REPO_ROOT / "packages" / "jin-lsp" / "src" / "jin_lsp"

EXAMPLE_FILES = sorted(EXAMPLES.glob("*/*.jin"))


def test_there_are_examples_to_compare() -> None:
    """突合の対象が消えたら気づく（0 件でも parametrize は緑になる）。"""
    assert len(EXAMPLE_FILES) == 2, EXAMPLE_FILES


async def _ask_server(path: Path, method: str, extra: dict | None = None) -> dict:
    """`python -m jin_lsp` を起こして 1 リクエストだけ投げる。"""
    sys.path.insert(0, str(REPO_ROOT / "packages" / "jin-lsp" / "tests"))
    from jin_lsp.protocol import jin_converter
    from pytest_lsp.client import LanguageClient, register_lsp_features

    config = ClientServerConfig(
        server_command=[sys.executable, "-m", "jin_lsp"],
        client_factory=lambda: _make_client(LanguageClient, register_lsp_features, jin_converter),
    )
    client = await config.start()
    try:
        await client.initialize_session(
            types.InitializeParams(capabilities=types.ClientCapabilities())
        )
        uri = path.as_uri()
        client.text_document_did_open(
            types.DidOpenTextDocumentParams(
                text_document=types.TextDocumentItem(
                    uri=uri,
                    language_id="jin",
                    version=1,
                    text=path.read_text(encoding="utf-8", newline=""),
                )
            )
        )
        await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
        if method == "formatting":
            edits = await client.text_document_formatting_async(
                types.DocumentFormattingParams(
                    text_document=types.TextDocumentIdentifier(uri=uri),
                    options=types.FormattingOptions(tab_size=2, insert_spaces=True),
                )
            )
            return {"edits": list(edits or [])}
        result = await client.protocol.send_request_async(method, {"uri": uri, **(extra or {})})
        # `jin_lsp.protocol.jin_converter` を渡しているので応答は素の dict のまま届く。
        return {"svg": result["svg"]}
    finally:
        await client.shutdown_session()
        await client.stop()


def _make_client(language_client, register, converter):
    client = language_client(converter_factory=converter)
    register(client)
    return client


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.parent.name)
def test_render_svg_over_lsp_is_byte_identical_to_jin_render(path: Path, tmp_path: Path) -> None:
    """machine: `jin/renderSvg` の出力が `jin render` の出力とバイト一致する。"""
    out = tmp_path / "cli.svg"
    completed = subprocess.run(
        [str(JIN), "render", str(path), "-o", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    from_cli = out.read_bytes()

    from_lsp = asyncio.run(_ask_server(path, "jin/renderSvg"))["svg"].encode("utf-8")
    assert from_lsp == from_cli, f"{path.name}: LSP と CLI の SVG が違う"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.parent.name)
def test_formatting_over_lsp_is_byte_identical_to_jin_fmt(path: Path, tmp_path: Path) -> None:
    """machine: formatting の出力が `jin fmt` の出力とバイト一致する。

    `examples/` は既に正準形なので、`jin fmt --check` は差分なしで通り、LSP の
    formatting も空の編集を返す。**それだけでは「どちらも何もしない」ことしか
    確かめられない**ので、崩したコピーを作って両方に整形させ、結果を突き合わせる。
    """
    original = path.read_text(encoding="utf-8", newline="")
    messy_source = json.dumps(json.loads(original), ensure_ascii=False, indent=8)
    messy = tmp_path / path.name
    messy.write_text(messy_source, encoding="utf-8", newline="")

    completed = subprocess.run(
        [str(JIN), "fmt", str(messy)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    from_cli = messy.read_bytes()

    messy.write_text(messy_source, encoding="utf-8", newline="")
    edits = asyncio.run(_ask_server(messy, "formatting"))["edits"]
    assert len(edits) == 1, "整形の必要があるのに編集が返っていない"
    assert edits[0].new_text.encode("utf-8") == from_cli, f"{path.name}: LSP と CLI の正準形が違う"


# --------------------------------------------------------------------------------------
# DP-COMMON-14: stdio の stdout は JSON-RPC の通信路である
# --------------------------------------------------------------------------------------
def test_the_lsp_package_never_prints_to_stdout() -> None:
    """`jin_lsp` に `print(...)` を 1 つも置かない。

    stdio モードでは stdout が通信路そのもので、1 行の印字がセッションを壊す
    （しかも中身がクライアントへ渡る）。ログは `jin_lsp.logs.configure` が
    stderr へ固定するが、`print` はそこを通らないので**構文として**禁じる。
    `sys.stdout` への直接の書き込みも同じ理由で禁じる。
    """
    offenders: list[str] = []
    for path in sorted(LSP_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                offenders.append(f"{path.name}: print()")
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "sys"
                and node.value.attr == "stdout"
            ):
                offenders.append(f"{path.name}: sys.stdout.{node.attr}")
    assert offenders == [], offenders


def test_the_stdout_scan_would_catch_a_print() -> None:
    """上の走査が壊れて何も見ていない状態を検出する（偽緑を防ぐ）。"""
    tree = ast.parse("print('x')\nimport sys\nsys.stdout.write('y')\n")
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert len(found) == 1
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "stdout"
    ]
    assert len(writes) == 1


def test_the_lsp_package_has_no_dynamic_imports() -> None:
    """`jin_lsp` に動的 import を置かない（`ws` で外に口が開いているパッケージである）。

    `tests/contract/test_packaging_contract.py` が `jin_cli.resolver` と
    `jin_adk.runtime` の 2 つに厳密一致で閉じているが、そちらは「2 つだけ」を見る形なので、
    ここでは jin_lsp を名指しで見る（走査の対象が変わっても jin_lsp は守られる）。
    """
    forbidden = {"importlib", "runpy"}
    offenders: list[str] = []
    for path in sorted(LSP_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if a.name.split(".")[0] in forbidden
                ]
            elif (
                isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in forbidden
            ):
                offenders.append(f"{path.name}: from {node.module}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "exec", "eval"}
            ):
                offenders.append(f"{path.name}: {node.func.id}()")
    assert offenders == [], offenders
