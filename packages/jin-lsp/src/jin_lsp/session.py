"""開いているドキュメントの状態と last-good モデル（DP-COMMON-07 / NFR-AVAIL-001）。

要件書 §6.4 の最後の項「JSON 構文エラー中も、直前の正常なモデルで hover / renderSvg を
提供する（エラー回復）」を成立させるための最小の記憶である。

DP-COMMON-07（人間確定）の決定内容:

- **last-good モデルは 1 世代だけ**保持する。履歴を積まない（長寿命プロセスで際限なく太る）
- **SVG はキャッシュしない**。`jin_render.render` は純関数なので毎回呼ぶ
- `jin_core` / `jin_render` はキャッシュの存在を知らない純関数のままとする
  （＝この記憶は `jin_lsp` 側にだけ置く）

**「正常」の定義はパースでき schema を通ったところまで**である（phase3-handoff §5）。
意味エラー（未定義 circle への `summon` / JIN012 の循環 …）を含むモデルでも
`jin_render.render` は例外を投げない契約なので、意味エラーを理由に last-good を
捨てると「壊れかけの陣を図で見ながら直す」という本来の使い方ができなくなる。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jin_core.check import CheckResult, check_text
from jin_core.diagnostics import Diagnostic
from jin_core.model import JinFile
from jin_core.parser import PointerTable


@dataclass(frozen=True, slots=True)
class LastGood:
    """パースでき schema を通った最後の状態（**1 世代だけ**保持する）。

    `text` と `lines` を一緒に持つのは、この世代の pointer→range 対応表が
    **そのテキストの座標**を指すからである。現在の（壊れた）テキストの行で
    位置変換すると、行数が変わっているときに範囲がずれる。
    """

    text: str
    lines: list[str]
    model: JinFile
    table: PointerTable


@dataclass(slots=True)
class DocumentState:
    """1 つの `.jin` ドキュメントの状態。

    `model` は**現在のテキスト**のモデル（壊れていれば `None`）。
    `last_good` は直前に schema を通った世代（無ければ `None`）。
    """

    uri: str
    text: str
    version: int = 0
    lines: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    model: JinFile | None = None
    table: PointerTable | None = None
    last_good: LastGood | None = None

    @property
    def model_for_display(self) -> JinFile | None:
        """hover / renderSvg が使うモデル。現在が壊れていれば last-good に落ちる。"""
        if self.model is not None:
            return self.model
        return self.last_good.model if self.last_good is not None else None

    @property
    def table_for_display(self) -> PointerTable | None:
        """`model_for_display` と**同じ世代**の pointer→range 対応表。"""
        if self.model is not None:
            return self.table
        return self.last_good.table if self.last_good is not None else None

    @property
    def lines_for_display(self) -> list[str]:
        """`table_for_display` の座標が指すテキストの行。"""
        if self.model is not None:
            return self.lines
        return self.last_good.lines if self.last_good is not None else self.lines


def split_lines(text: str) -> list[str]:
    """改行を**含めた**まま行に分ける（UTF-16 換算に行の中身が要る）。

    `str.splitlines` は行末の改行を落とすうえ、`\\x0b` / `\\u2028` などでも切る。
    JSON の文字列リテラル内にそれらが生（エスケープされずに）現れることは JSON 仕様上
    無いが、`keepends=True` で分けたうえで**連結すると元に戻る**ことをテストで固定する。
    """
    return text.splitlines(keepends=True)


class DocumentStore:
    """URI → `DocumentState`。`didClose` で捨てる。

    LSP サーバは長寿命なので、開いたドキュメントを溜めない。
    pygls も `Workspace` に同じテキストを持つが、こちらが持つのは**診断済みの結果**
    （モデル・対応表・last-good）であり、テキストの正本は pygls 側である。
    """

    def __init__(self) -> None:
        self._documents: dict[str, DocumentState] = {}

    def get(self, uri: str) -> DocumentState | None:
        return self._documents.get(uri)

    def close(self, uri: str) -> None:
        self._documents.pop(uri, None)

    def update(self, uri: str, text: str, *, version: int = 0) -> DocumentState:
        """テキストを診断し直し、状態を差し替える。

        `check_text` が段 1 → 段 2 → 段 3 の順で止まる（`jin_core.check`）ので、
        段階診断の規則は**ここで再実装しない**。LSP 側は結果を運ぶだけである
        （要件書 §6「LSP 固有のロジックは位置変換とプロトコル露出だけに限定する」）。
        """
        previous = self._documents.get(uri)
        result: CheckResult = check_text(text, self._file_name(uri))
        lines = split_lines(text)
        state = DocumentState(
            uri=uri,
            text=text,
            version=version,
            lines=lines,
            diagnostics=list(result.diagnostics),
            model=result.model,
            table=result.table,
            last_good=previous.last_good if previous is not None else None,
        )
        if result.model is not None and result.table is not None:
            # **1 世代だけ**差し替える（DP-COMMON-07）。前の世代への参照は残さない。
            state.last_good = LastGood(
                text=text, lines=lines, model=result.model, table=result.table
            )
        self._documents[uri] = state
        return state

    @staticmethod
    def _file_name(uri: str) -> str:
        """診断の `file` に載せる名前。

        `jin check` はパスを載せるが、LSP のクライアントは URI で文書を識別しており、
        `Diagnostic` は `PublishDiagnosticsParams.uri` 側で対象を示す。ここは
        **表示用の短い名前**でよいので URI の末尾を使う（`file://` のホスト部や
        パーセントエンコードを解く実装をここに増やさない）。
        """
        return uri.rsplit("/", 1)[-1] or uri


__all__ = ["DocumentState", "DocumentStore", "LastGood", "split_lines"]
