"""診断パイプライン: JSON 構文（JIN001）→ スキーマ（JIN002）→ 意味（段 3）。

docs/spec/diagnostics.md §1 のとおり、前段に error があれば後段は実行しない。
`jin check --json` と（Phase 4 の）LSP `publishDiagnostics` はこの同じ関数を通る。

JIN002 の検出器は **Pydantic に一本化**する（ADR-006 の constraints）。
`schemas/jin.schema.json` は外部 JSON ツールと LLM 向けの公開契約であり、内部検証には使わない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from jin_core import semantic
from jin_core.diagnostics import Diagnostic, Position, Range, has_error, severity_of
from jin_core.model import JinFile
from jin_core.parser import JinSyntaxError, PointerTable, parse_text
from jin_core.pointer import is_index_token, loc_to_pointer, parent_of, split_pointer
from jin_core.resolver import RefResolver


class JinReadError(Exception):
    """ファイルを読めなかった（存在しない / ディレクトリ / 権限など）。

    JSON の中身の問題ではないので診断コードは与えず、呼び出し側（CLI）が
    使い方の誤りとして表示し、非 0 で終了する。**黙って握り潰さない**（NFR-FAIL-001）。
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def read_source(path: Path) -> str:
    """`.jin` のテキストを**改行を変換せずに**読む。

    `newline=""` を外すと Python が CRLF を LF に畳んでしまい、
    `jin fmt --check` が「差分なし」と答えたあとで `jin fmt` がファイルを書き換える
    （correctness review D-2）。原文のバイト列と正準形を突き合わせるために変換を止める。
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError as exc:
        raise JinReadError(
            path, f"読み込めません（{type(exc).__name__}: {exc.strerror or exc}）"
        ) from exc


@dataclass(slots=True)
class CheckResult:
    """1 ファイル分の診断結果。

    `model` / `value` / `table` は段が進んだところまでしか埋まらない。
    """

    file: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    value: Any = None
    table: PointerTable | None = None
    model: JinFile | None = None

    @property
    def ok(self) -> bool:
        return not has_error(self.diagnostics)


def _unwrap(annotation: Any) -> list[type]:
    """Optional / list / Union を剥がして BaseModel サブクラスを集める。"""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        out: list[type] = []
        for arg in get_args(annotation):
            out.extend(_unwrap(arg))
        return out
    if origin in (list, tuple, set):
        args = get_args(annotation)
        return _unwrap(args[0]) if args else []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return []


def _model_at(pointer: str, document: Any) -> list[type[BaseModel]]:
    """pointer が指す位置のモデルクラス候補を返す。

    判別共用体（tools[]）はソース側の `kind` を見て 1 つに絞る。絞れなければ候補を全部返す。
    モデル定義から動的に辿るので、モデルを変えても追随する（キー名をハードコードしない）。
    """
    current: list[type[BaseModel]] = [JinFile]
    node = document
    for token in split_pointer(pointer):
        if isinstance(node, list):
            if is_index_token(token) and 0 <= int(token) < len(node):
                node = node[int(token)]
            else:
                return []
            if len(current) > 1 and isinstance(node, dict) and "kind" in node:
                current = [c for c in current if _kind_of(c) == node["kind"]] or current
            continue

        nxt: list[type[BaseModel]] = []
        for cls in current:
            for name, info in cls.model_fields.items():
                if (info.alias or name) == token:
                    nxt.extend(_unwrap(info.annotation))
        if not nxt:
            return []
        current = nxt
        if isinstance(node, dict) and token in node:
            node = node[token]
            if isinstance(node, dict) and "kind" in node and len(current) > 1:
                current = [c for c in current if _kind_of(c) == node["kind"]] or current
        else:
            return current
    return current


def _kind_of(cls: type[BaseModel]) -> str | None:
    info = cls.model_fields.get("kind")
    if info is None:
        return None
    args = get_args(info.annotation)
    return args[0] if args else None


def _allowed_keys(pointer: str, document: Any) -> list[str]:
    """pointer の親が許容するキー名（JIN002 の hint 用）。"""
    parent = parent_of(pointer)
    if parent is None:
        return []
    keys: list[str] = []
    for cls in _model_at(parent, document):
        for name, info in cls.model_fields.items():
            alias = info.alias or name
            if alias not in keys:
                keys.append(alias)
    return keys


def _hint_for(error: dict[str, Any], pointer: str, document: Any) -> str:
    kind = error["type"]
    if kind == "extra_forbidden":
        allowed = _allowed_keys(pointer, document)
        token = split_pointer(pointer)[-1] if pointer else ""
        near = semantic.close_names(token, allowed)
        head = f"近いキー: {' / '.join(near)}。" if near else ""
        return head + (
            "使えるキー: " + " / ".join(allowed) if allowed else "このキーは削除してください"
        )
    if kind == "missing":
        token = split_pointer(pointer)[-1] if pointer else ""
        return f"必須キー '{token}' を追加してください"
    if kind == "union_tag_invalid":
        return "kind は tool / builtin / summon のいずれかです"
    context = error.get("ctx") or {}
    if "expected" in context:
        return f"許容値: {context['expected']}"
    input_value = error.get("input")
    return f"許容されない値です: {input_value!r}。{error['msg']}"


def _schema_diagnostics(
    exc: ValidationError, document: Any, table: PointerTable, file: str
) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    seen: set[tuple[str, str]] = set()
    for error in exc.errors():
        pointer = loc_to_pointer(document, tuple(error["loc"]))
        signature = (pointer, error["type"])
        if signature in seen:
            continue
        seen.add(signature)
        out.append(
            Diagnostic(
                file=file,
                pointer=pointer,
                range=table.resolve_key_or_value(pointer),
                code="JIN002",
                severity=severity_of("JIN002"),
                message=f"スキーマ違反（{pointer or '/'}）: {error['msg']}",
                hint=_hint_for(error, pointer, document),
            )
        )
    return out


def check_text(text: str, file: str, *, resolver: RefResolver | None = None) -> CheckResult:
    """テキストを診断する。段 1 → 段 2 → 段 3 の順で、前段に error があれば止める。

    `resolver` を渡したときだけ JIN040（外部参照の解決）を検査する。
    `resolver` は**任意の Python コードを実行しうる**ので、`jin_core` には実装を置かない
    （`jin_core.resolver` の docstring / security review S1）。
    """
    result = CheckResult(file=file)

    # ---- 段 1: JSON 構文 ----------------------------------------------------------
    try:
        parsed = parse_text(text)
    except JinSyntaxError as exc:
        result.diagnostics.append(
            Diagnostic(
                file=file,
                pointer="",
                range=exc.range,
                code="JIN001",
                severity=severity_of("JIN001"),
                message=exc.message,
                hint=exc.hint,
            )
        )
        return result
    result.value = parsed.value
    result.table = parsed.table

    # ---- 段 2: スキーマ -----------------------------------------------------------
    try:
        model = JinFile.model_validate(parsed.value)
    except ValidationError as exc:
        result.diagnostics.extend(_schema_diagnostics(exc, parsed.value, parsed.table, file))
        return result
    result.model = model

    # ---- 段 3: 意味 ---------------------------------------------------------------
    result.diagnostics.extend(semantic.analyze(model, parsed.table, file, resolver=resolver))
    return result


def check_file(path: str | Path, *, resolver: RefResolver | None = None) -> CheckResult:
    """ファイルを読んで診断する。

    UTF-8 として読めないファイルは JIN001（段 1）にする。開けない・ディレクトリ・
    権限が無いといった入出力の失敗は `JinReadError` として呼び出し側へ返す。
    どちらも例外をそのまま外へ出さない（security review S5）。
    """
    path = Path(path)
    try:
        text = read_source(path)
    except UnicodeDecodeError as exc:
        result = CheckResult(file=str(path))
        result.diagnostics.append(
            Diagnostic(
                file=str(path),
                pointer="",
                range=Range(Position(1, 1), Position(1, 1)),
                code="JIN001",
                severity=severity_of("JIN001"),
                message=f"UTF-8 として読めません（位置 {exc.start}: {exc.reason}）",
                hint="期待: UTF-8 で符号化された JSON テキスト。エディタの文字コードを UTF-8 にしてください",
            )
        )
        return result
    return check_text(text, str(path), resolver=resolver)


__all__ = ["CheckResult", "JinReadError", "check_file", "check_text", "read_source"]
