"""jin-lsp のテスト共有ヘルパ（最小の `.jin` テキスト）。

他パッケージのテストと同じ流儀で `from .conftest import ...` して使う
（`packages/jin-render/tests/conftest.py` を参照）。

`$schema` / `version` / `root` / `circles` は必須（`jin_core.model.JinFile`）。
核なし circle は `flow` を要求される（JIN022）ので、最小の有効例には `core` を持たせる。
**正準形**（`jin_core.canonical.dumps` の出力）に合わせてある。合わせておかないと
formatting のテストが「差分が出る例」しか作れない。
"""

from __future__ import annotations

SCHEMA_URL = "https://xtone.internal/jin/schemas/jin.schema.json"


def minimal(root: str = "A", *, rune: str | None = None) -> str:
    """circle 1 つの最小の有効な `.jin`（正準形）。"""
    instruction = ""
    if rune is not None:
        instruction = f'      "instruction": {{\n        "rune": "{rune}"\n      }},\n'
    return (
        "{\n"
        f'  "$schema": "{SCHEMA_URL}",\n'
        '  "version": 1,\n'
        f'  "root": "{root}",\n'
        '  "circles": [\n'
        "    {\n"
        f'      "name": "{root}",\n'
        '      "core": "gemini-2.5-flash",\n' + instruction + '      "state": [\n'
        "        {\n"
        '          "name": "answer",\n'
        '          "type": "string"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )


#: 段 1（JSON 構文）で落ちる。閉じ括弧が無い。
BROKEN = '{\n  "$schema": "x",\n'

#: 段 2（スキーマ）で落ちる。`version` が 1 でない。
SCHEMA_ERROR = minimal().replace('"version": 1', '"version": 2')

#: 段 3（意味）で落ちる。`root` が定義されていない circle を指す（JIN060 / JIN011）。
SEMANTIC_ERROR = minimal().replace('"root": "A"', '"root": "Nope"', 1)

__all__ = ["BROKEN", "SCHEMA_ERROR", "SCHEMA_URL", "SEMANTIC_ERROR", "minimal"]


def as_plain(value: object) -> object:
    """pygls の `Object`（未知メソッドの応答を包む namedtuple 風）を素の JSON 値へ戻す。

    サーバは独自リクエストの応答を **素の dict** で返す（Phase 5 のブラウザ エディタは
    JSON をそのまま読む）。pygls のクライアント側デシリアライザがそれを属性アクセスの
    `Object` に変換するので、テストでは元の形に戻して突き合わせる。
    """
    if isinstance(value, list):
        return [as_plain(item) for item in value]
    fields = getattr(type(value), "_fields", None)
    if fields is not None:  # namedtuple 風（pygls.protocol.Object）
        return {name: as_plain(getattr(value, name)) for name in fields}
    if isinstance(value, dict):
        return {key: as_plain(item) for key, item in value.items()}
    return value
