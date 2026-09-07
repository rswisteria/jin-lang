"""独自リクエスト（エディタ API・要件書 §6.3）の**中身**。

プロトコル露出（`@server.feature(...)`）は `jin_lsp.server` が行い、ここには
「状態 → 応答 dict」の純関数だけを置く。こうしておくと stdio / ws のどちらの
トランスポートでも**同じ関数**が答えることがテストで確かめられる（要件書 §6.1）。

4 リクエスト（要件書 §6.3）:

| リクエスト | 応答 |
|---|---|
| `jin/model` | `{"model": ..., "pointers": [...], "stale": bool}` |
| `jin/renderSvg` | `{"svg": str, "stale": bool}` |
| `jin/applyOps` | `{"ok": bool, "model": ..., "inverses": [...], "diagnostics": [...], "text": str}` |
| `jin/ops` | `{"operations": [...]}` |

**`stale`**: `true` なら現在のテキストが壊れていて **last-good モデル**で答えた
（NFR-AVAIL-001 のエラー回復）。黙って古い図を返すとエディタが「編集が効かない」と
見えるので、必ず伝える（NFR-FAIL-001「黙って落とさない」の同じ精神）。
"""

from __future__ import annotations

from typing import Any

from jin_core import canonical, ops
from jin_core.model import JinFile
from jin_core.parser import PointerTable
from jin_render import render
from jin_render.overlay import TraceRowError

from jin_lsp.session import DocumentState


class RequestError(Exception):
    """リクエストを処理できなかった。`code` は診断コード（`docs/spec/ops.md` §4）。"""

    def __init__(self, code: str, message: str, hint: str = "", pointer: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.pointer = pointer

    def to_json(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "pointer": self.pointer,
        }


#: `jin/ops` が返す一覧。**`docs/spec/ops.md` §2 の表と同内容**であることを
#: `tests/spec/test_spec_consistency.py` が突合する（仕様側とコード側は同じ欠陥・
#: 片方だけ直さない）。ここに 20 個目を足さない（要件書 §6.3 の v1 は 19 件）。
OPERATION_SPECS: tuple[dict[str, str], ...] = (
    {"name": "addCircle", "target": "/circles", "inverse": "removeCircle"},
    {"name": "removeCircle", "target": "/circles/<i>", "inverse": "addCircle"},
    {"name": "setCore", "target": "/circles/<i>", "inverse": "setCore"},
    {"name": "setDescription", "target": "/circles/<i>", "inverse": "setDescription"},
    {"name": "setRune", "target": "/circles/<i>", "inverse": "setRune"},
    {"name": "addTool", "target": "/circles/<i>/tools", "inverse": "removeTool"},
    {"name": "removeTool", "target": "/circles/<i>/tools/<j>", "inverse": "addTool"},
    {"name": "moveTool", "target": "/circles/<i>/tools/<j>", "inverse": "moveTool"},
    {"name": "addState", "target": "/circles/<i>/state", "inverse": "removeState"},
    {"name": "removeState", "target": "/circles/<i>/state/<j>", "inverse": "addState"},
    {"name": "setState", "target": "/circles/<i>/state/<j>", "inverse": "setState"},
    {"name": "setFlow", "target": "/circles/<i>", "inverse": "setFlow"},
    {"name": "addDelegate", "target": "/circles/<i>/delegate", "inverse": "removeDelegate"},
    {"name": "removeDelegate", "target": "/circles/<i>/delegate/<j>", "inverse": "addDelegate"},
    {"name": "setGuard", "target": "/circles/<i>/boundary/guards/<j>", "inverse": "setGuard"},
    {"name": "removeGuard", "target": "/circles/<i>/boundary/guards/<j>", "inverse": "setGuard"},
    {"name": "toggleAwait", "target": "/circles/<i>", "inverse": "toggleAwait"},
    {"name": "setRoot", "target": "", "inverse": "setRoot"},
    {"name": "rename", "target": "対象要素（circle / tool / state）", "inverse": "rename"},
)


def _range_to_json(table: PointerTable) -> list[dict[str, Any]]:
    """pointer→range 対応表を JSON にする。

    座標は **`jin_core` の系のまま**（1 始まり・コードポイント・end 排他）で載せる。
    LSP の `Position` に変換しないのは、この対応表が要件書 §5 の診断 JSON と
    同じ座標系で読まれるものだからである（`jin dump` の出力と揃う）。

    **`jin dump` は `{pointer: range}` の辞書で出すが、ここは配列にする**
    （DP-IMPL-JIN-P4-POINTER-SHAPE-01）。JSON Pointer は `/` を含むので、
    JSON-RPC クライアントによってはオブジェクトのキーとして往復しない:
    pygls 2.1.1 のクライアントは未知メソッドの応答 dict を namedtuple 風の
    `pygls.protocol.Object` に変換し、識別子にできないキーを `_0` / `_1` へ
    **黙って置き換える**（2026-09-07 実測）。鍵が消えれば対応表は使えない。
    配列なら任意のクライアントで壊れない。順序は pointer の辞書順で決定的。
    """
    return [
        {"pointer": pointer, **range_.to_json_dict()}
        for pointer, range_ in sorted(table.value_ranges.items())
    ]


def _require_model(state: DocumentState | None, uri: str) -> tuple[JinFile, bool]:
    """表示用のモデルと `stale` を返す。どちらも無ければ `RequestError`。"""
    if state is None:
        raise RequestError(
            "JIN002",
            f"開かれていないドキュメントです: {uri}",
            "先に textDocument/didOpen を送ってください",
        )
    model = state.model_for_display
    if model is None:
        raise RequestError(
            "JIN001",
            "モデルがありません（JSON 構文エラーで、直前の正常な版もありません）",
            "JSON の構文を直してください。診断 JIN001 の位置を参照",
        )
    return model, state.model is None


def jin_model(state: DocumentState | None, uri: str) -> dict[str, Any]:
    """`jin/model`: モデル JSON + pointer→range 対応表（要件書 §6.3）。"""
    model, stale = _require_model(state, uri)
    assert state is not None  # _require_model が None を弾いている
    table = state.table_for_display
    return {
        "model": model.model_dump(by_alias=True, mode="json"),
        "pointers": _range_to_json(table) if table is not None else [],
        "stale": stale,
    }


def jin_render_svg(
    state: DocumentState | None,
    uri: str,
    *,
    focus: str | None = None,
    trace: list[dict[str, Any]] | None = None,
    upto: int | None = None,
) -> dict[str, Any]:
    """`jin/renderSvg`: `{ uri, focus?, trace?, upto? }` → SVG 文字列。

    `jin_render.render` が**唯一の入口**（要件書 §4 最終項）。ここで独自に
    レイアウトを持たないので、`jin render` の出力とバイト一致する。
    **SVG はキャッシュしない**（DP-COMMON-07）。
    """
    model, stale = _require_model(state, uri)
    try:
        svg = render(model, focus=focus, trace=trace, upto=upto)
    except TraceRowError as exc:
        # **どの行が悪いのかを言う**（NFR-FAIL-001）。`TraceRowError.index` は
        # `trace` 配列の中の位置（0 始まり）で、**JSONL の行番号ではない**。
        # 行番号はプロトコルを渡るときに失われる（クライアントが JSONL を読んで
        # 配列にしてから送る）ので、ここで言えるのは位置までである。
        # `jin render --trace` は同じ `index` を実ファイル行番号へ写して `path:N:` と出す。
        raise RequestError(
            "JIN002",
            f"描画できません: トレースの {exc.index + 1} 件目: {exc}",
            "trace の各行に seq（1 始まりの整数）と pointer（文字列 または null）を入れてください",
        ) from exc
    except Exception as exc:  # RenderError / ValueError
        raise RequestError(
            "JIN002",
            f"描画できません: {exc}",
            "focus に定義済みの circle 名を、trace に seq / pointer を持つ行を渡してください",
        ) from exc
    return {"svg": svg, "stale": stale}


def jin_ops() -> dict[str, Any]:
    """`jin/ops`: 利用可能なオペレーションの一覧（`docs/spec/ops.md` と同内容）。"""
    return {"operations": [dict(spec) for spec in OPERATION_SPECS]}


def jin_apply_ops(state: DocumentState | None, uri: str, op_list: list[dict[str, Any]]) -> Any:
    """`jin/applyOps`: 意味オペレーション列を当て、新モデル・診断・逆オペレーションを返す。

    `jin_core.ops.apply_ops` は「1 つでも失敗したら何も適用しない」（`docs/spec/ops.md` §6）。
    その原子性をここで崩さない。失敗は例外にせず `ok: false` と診断コードで返す
    （エディタが undo スタックを壊さずに済む）。

    テキストへの反映は**正準形を通す**（`docs/spec/ops.md` §1）。差分の
    `workspace/applyEdit` 送出は呼び出し側（`jin_lsp.server`）が行う。
    """
    if state is None:
        raise RequestError(
            "JIN002",
            f"開かれていないドキュメントです: {uri}",
            "先に textDocument/didOpen を送ってください",
        )
    if state.model is None:
        # last-good に当てるとユーザーが見ていない版を書き戻すことになる。**拒む**。
        raise RequestError(
            "JIN001",
            "JSON 構文エラーのあるテキストにはオペレーションを当てられません",
            "先に構文エラーを直してください（renderSvg / hover は直前の正常な版で答えます）",
        )
    if not isinstance(op_list, list):
        raise RequestError("JIN002", "ops は配列で渡してください", '例: [{"op": "setRoot", ...}]')
    try:
        result = ops.apply_ops(state.model, op_list)
    except ops.OpError as exc:
        return {
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "hint": exc.hint,
                "pointer": exc.pointer,
            },
        }
    return {
        "ok": True,
        "model": result.model.model_dump(by_alias=True, mode="json"),
        "inverses": result.inverses,
        "text": canonical.dumps(result.model),
    }


__all__ = [
    "OPERATION_SPECS",
    "RequestError",
    "jin_apply_ops",
    "jin_model",
    "jin_ops",
    "jin_render_svg",
]
