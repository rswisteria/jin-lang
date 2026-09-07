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


def make_client():
    """`jin_lsp.protocol.jin_converter` を使うテストクライアント。

    pytest-lsp の `make_test_lsp_client()` は pygls の既定 converter を使うため、
    未知メソッド（`jin/*`）の**応答**が `namedtuple(rename=True)` に変換され、
    `$schema` や `await` のような識別子にできないキーが `_0` へ黙って置き換わる。
    サーバ側と同じ converter を渡して素の JSON で受け取る。
    """
    from jin_lsp.protocol import jin_converter
    from pytest_lsp.client import LanguageClient, register_lsp_features

    client = LanguageClient(converter_factory=jin_converter)
    register_lsp_features(client)
    return client


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


#: 19 オペレーションを全部当てられる構造を持つモデル（`jin_core` の `test_ops.py` の
#: sample() と同じ形）。LSP 経由の往復（design.yaml machine 4）で使う。
RICH_MODEL: dict = {
    "$schema": SCHEMA_URL,
    "version": 1,
    "root": "A",
    "circles": [
        {
            "name": "A",
            "core": "gemini-2.5-flash",
            "description": "説明",
            "instruction": {"rune": "{q} を調べる"},
            "tools": [
                {"name": "search", "kind": "tool", "ref": "m:search"},
                {"name": "summarize", "kind": "summon", "circle": "B"},
            ],
            "delegate": ["B"],
            "state": [{"name": "q", "type": "str"}],
            "boundary": {
                "guards": [{"on": "before_model", "ref": "m:guard"}],
                "await": ["search"],
            },
        },
        {"name": "B", "core": "gemini-2.5-flash"},
    ],
}

#: `jin/applyOps` に流す 19 種。**`jin_core.ops.OPERATIONS` の 19 件と過不足なく
#: 一致すること**をテストが等号で確認する（1 つ書き忘れても気づけるように）。
OPERATION_CASES: list[dict] = [
    {"op": "addCircle", "pointer": "/circles", "index": 1, "value": {"name": "C", "core": "m"}},
    {"op": "removeCircle", "pointer": "/circles/1"},
    {"op": "setCore", "pointer": "/circles/0", "value": "gemini-2.5-pro"},
    {"op": "setDescription", "pointer": "/circles/0", "value": "別の説明"},
    {"op": "setRune", "pointer": "/circles/0", "value": "{q} を要約する"},
    {
        "op": "addTool",
        "pointer": "/circles/0/tools",
        "index": 0,
        "value": {"name": "fetch", "kind": "tool", "ref": "m:fetch"},
    },
    {"op": "removeTool", "pointer": "/circles/0/tools/1"},
    {"op": "moveTool", "pointer": "/circles/0/tools/0", "index": 1},
    {
        "op": "addState",
        "pointer": "/circles/0/state",
        "index": 0,
        "value": {"name": "answer", "type": "str"},
    },
    {"op": "removeState", "pointer": "/circles/0/state/0"},
    {"op": "setState", "pointer": "/circles/0/state/0", "value": {"type": "int"}},
    {
        "op": "setFlow",
        "pointer": "/circles/1",
        "value": {"kind": "sequence", "steps": ["A"]},
    },
    {"op": "addDelegate", "pointer": "/circles/0/delegate", "index": 0, "value": "B"},
    {"op": "removeDelegate", "pointer": "/circles/0/delegate/0"},
    {
        "op": "setGuard",
        "pointer": "/circles/0/boundary/guards/0",
        "value": {"on": "after_model", "ref": "m:guard2"},
    },
    {"op": "removeGuard", "pointer": "/circles/0/boundary/guards/0"},
    {"op": "toggleAwait", "pointer": "/circles/0", "value": "search"},
    {"op": "setRoot", "pointer": "", "value": "B"},
    {"op": "rename", "pointer": "/circles/1", "value": "Bee"},
]
