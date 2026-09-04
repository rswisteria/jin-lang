"""正準形（canonical form）writer。

ADR-005 / DP-JIN-CANONICAL-01（案 C）: `json.dumps` の引数調整や Pydantic の `model_dump` 後処理ではなく、
**Pydantic のフィールド定義順を走査する独自 writer をここ 1 箇所に置く**。

同 DP の constraints[]:

- 「§2.3 の 5 規則は canonical writer 1 箇所にのみ実装し、Pydantic 設定と後処理へ分散させない」
  → 本モジュールが唯一の実装箇所。`model_dump` / `model_dump_json` は使わない
- 「Pydantic のモデル定義変更に writer が追随することをテストで担保する」
  → writer は `type(obj).model_fields` を走査するだけで、キー名も順序もハードコードしない
- 「JSON エスケープ処理を自前で書くことによるバグリスクを、非 ASCII・制御文字・サロゲートペアの
  fixture で必ず検証する」→ `packages/jin-core/tests/test_canonical.py` と
  `tests/fixtures/errors/` 以外の `tests/fixtures/canonical/` で検証する

規則（docs/spec/model.md §7）:

1. インデントは 2 スペース
2. キー順はスキーマ定義順（= Pydantic のフィールド定義順）
3. 配列は宣言順を保持
4. 末尾に改行 1 つ
5. 非 ASCII はエスケープしない
6. `$schema` と `version` は先頭固定（= `JinFile` のフィールド定義順がそうなっている）
7. 省略可能なキーは値が既定値のとき出力しない
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

INDENT = "  "

#: 規則 5 のため、エスケープするのは JSON が必須とする文字だけに限る。
#: U+007F（DEL）と U+0080 以上はエスケープしない。
_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def encode_string(value: str) -> str:
    """JSON 文字列リテラルへ変換する（規則 5 準拠の最小エスケープ）。"""
    out = ['"']
    for ch in value:
        short = _SHORT_ESCAPES.get(ch)
        if short is not None:
            out.append(short)
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        elif 0xD800 <= ord(ch) <= 0xDFFF:
            # 孤立サロゲート。そのまま出すと呼び出し側の `write_text` が
            # UnicodeEncodeError で落ちる（トレースバックが表に出る fail-open）。
            # 通常は段 2（`jin_core.model`）で JIN002 として弾かれるが、
            # `dumps` を直接呼ぶ経路のために writer 側でも閉じておく。
            raise ValueError(
                f"JSON 文字列に孤立サロゲート U+{ord(ch):04X} が含まれています"
                "（UTF-8 に符号化できません）"
            )
        else:
            # サロゲートペア（BMP 外）を含め、そのまま出す。
            out.append(ch)
    out.append('"')
    return "".join(out)


def encode_number(value: float) -> str:
    """数値リテラルへ変換する。

    ``bool`` は ``int`` の派生なので呼び出し側で先に判定すること。
    ``float`` は Python の ``repr`` を使う（往復で値が変わらない最短表現）。
    """
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"JSON に書けない数値です: {value!r}")
    return repr(value)


def _is_default(field: Any, value: Any) -> bool:
    """規則 7: フィールドの値が既定値かどうか。"""
    if field.default is not PydanticUndefined:
        return bool(value == field.default)
    if field.default_factory is not None:
        try:
            return bool(value == field.default_factory())
        except TypeError:  # pragma: no cover - 引数付き default_factory は本モデルに無い
            return False
    return False


def _members(model: BaseModel) -> list[tuple[str, Any]]:
    """出力すべき (JSON キー名, 値) を **フィールド定義順** で返す（規則 2 / 7）。"""
    out: list[tuple[str, Any]] = []
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if _is_default(field, value):
            continue
        out.append((field.alias or name, value))
    return out


def _write(value: Any, depth: int, buf: list[str]) -> None:
    pad = INDENT * depth
    inner_pad = INDENT * (depth + 1)

    if isinstance(value, BaseModel):
        members = _members(value)
        if not members:
            buf.append("{}")
            return
        buf.append("{\n")
        for i, (key, member) in enumerate(members):
            buf.append(inner_pad)
            buf.append(encode_string(key))
            buf.append(": ")
            _write(member, depth + 1, buf)
            buf.append(",\n" if i < len(members) - 1 else "\n")
        buf.append(pad)
        buf.append("}")
        return

    if isinstance(value, list):
        if not value:
            buf.append("[]")
            return
        buf.append("[\n")
        for i, item in enumerate(value):
            buf.append(inner_pad)
            _write(item, depth + 1, buf)
            buf.append(",\n" if i < len(value) - 1 else "\n")
        buf.append(pad)
        buf.append("]")
        return

    if value is None:
        buf.append("null")
    elif isinstance(value, bool):  # bool は int より先に判定する
        buf.append("true" if value else "false")
    elif isinstance(value, (int, float)):
        buf.append(encode_number(value))
    elif isinstance(value, str):
        buf.append(encode_string(value))
    else:  # pragma: no cover - モデルに他の型は無い
        raise TypeError(f"正準形に書けない型です: {type(value)!r}")


def dumps(model: BaseModel) -> str:
    """意味モデルを正準形のテキストにする（規則 1〜7・末尾改行つき）。"""
    buf: list[str] = []
    _write(model, 0, buf)
    buf.append("\n")
    return "".join(buf)


__all__ = ["dumps", "encode_number", "encode_string"]
