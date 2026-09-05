"""生成コードのテンプレート（Jinja2）。

テンプレートに渡す値は **`jin_adk.codegen` が Python リテラル / 検査済み識別子にしたもの**だけ。
`autoescape` は HTML 用なので使わない（Python コードに `&quot;` を書いても意味がない）。
代わりに、テンプレート側に `.jin` の生の値が届く経路を作らない、という約束で守る
（`test_jin_strings_cannot_inject_statements`）。
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, StrictUndefined

_ENV = Environment(
    autoescape=False,
    undefined=StrictUndefined,  # 渡し忘れた変数を空文字で埋めない
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_agent_py(
    *,
    header: str,
    agent_classes: list[str],
    tool_imports: list[str],
    uses_agent_tool: bool,
    has_exit: bool,
    ref_imports: list[str],
    blocks: list[str],
) -> str:
    # importlib.resources は使わない（importlib を使うモジュールは runtime.py と jin_cli.resolver の
    # 2 つだけ、という契約テストに引っかかる）。パッケージ内のファイルを直接読む。
    source = Path(__file__).with_name("agent.py.j2").read_text(encoding="utf-8")
    return _ENV.from_string(source).render(
        header=header,
        agent_classes=agent_classes,
        tool_imports=tool_imports,
        uses_agent_tool=uses_agent_tool,
        has_exit=has_exit,
        ref_imports=ref_imports,
        blocks=blocks,
    )


__all__ = ["render_agent_py"]
