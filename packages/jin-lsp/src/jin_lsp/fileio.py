"""`jin/open` / `jin/save` — ws モードのエディタ専用のファイル I/O（ADR-011 / DP-JIN-EDITOR-PROTOCOL-01）。

人間確定済みの案 C: 「独自リクエスト `jin/open` と `jin/save` を 2 本追加し、**ws モードの
エディタだけが使う**」。stdio のクライアント（Claude Code / VS Code）は従来どおり
クライアント側がファイル I/O を担うので、この経路を通らない。

hazard: read -> path.open
hazard: write -> tempfile.mkstemp
guard: write -> os.replace
guard: resolve -> raw.resolve

## なぜ防御が要るか

`jin lsp --ws PORT` はローカルに WebSocket の待ち受けを開く。**WebSocket には
same-origin 制限が無い**ので、ブラウザで開いている任意のページが `ws://127.0.0.1:PORT`
へ繋いで `jin/save` を打てる。素で実装すると「ページを開いただけでローカルの
ファイルが書き換わる」経路になる。そこで 3 段で閉じる:

1. **既定で無効** — `--root` を明示したときだけ有効になる。`jin lsp --ws PORT` だけでは
   `jin/open` / `jin/save` は常に拒否される
2. **起動トークン** — 起動時に `secrets.token_urlsafe` で作り、**stderr** に出す。
   クライアントは `jin/open` / `jin/save` の params に `token` として毎回添える。
   一致しなければ拒否する。トークンは起動したプロセスの stderr を読める者
   （Phase 5 の `jin editor`）にしか渡らない。`initialize` の
   `initializationOptions` ではなく毎回のリクエストに載せるのは、pygls の
   `initialize` ハンドラを差し替えずに済み、検証の位置が読む側から見て
   「使う場所のすぐ隣」になるからである
3. **場所と種類** — 解決後のパスが `--root` の実体の配下にあり、拡張子が `.jin` で
   あることを要求する。`..` を含む URI も、root の外を指す symlink も、
   `resolve()` してから `relative_to` で見るので通らない。**書き先そのものが
   symlink なら拒む**（root の中に張られたリンク経由で、利用者が意識していない
   実体を書き換えないため）

## 残存（Phase 5 で `jin editor` を作るときに再確認すること）

- Origin ヘッダは見ていない。pygls 2.1.1 の `start_ws(host, port)` は `websockets` の
  サーバ生成オプションを露出しないため（実測）。トークンで代替している
- 同じマシンの**別のローカルプロセス**はポートに繋げる。トークンを知らなければ
  `jin/open` / `jin/save` は通らないが、それ以外のリクエスト（診断・描画）は打てる
"""

from __future__ import annotations

import contextlib
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

#: 起動トークンの長さ（バイト）。`secrets.token_urlsafe` に渡す。
TOKEN_BYTES = 32

#: 読み書きを許す拡張子。エディタが扱うのは `.jin` だけである（要件書 §7）。
ALLOWED_SUFFIX = ".jin"


class FileAccessDenied(Exception):
    """要求を拒んだ。`reason` はクライアントにそのまま見せてよい文言。"""

    def __init__(self, reason: str, hint: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.hint = hint


@dataclass(frozen=True, slots=True)
class FileAccess:
    """`--root` と起動トークンで縛られたファイル I/O。

    `root` が `None` なら**全ての要求を拒む**（`jin lsp --ws` を `--root` 無しで
    起動したときの既定）。
    """

    root: Path | None
    token: str

    @classmethod
    def create(cls, root: Path | None) -> FileAccess:
        """トークンを生成して束ねる。`root` は実体へ解決してから持つ。"""
        return cls(root=root.resolve() if root is not None else None, token=new_token())

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def authorize(self, presented: object) -> None:
        """クライアントが示したトークンを検証する。

        比較は `secrets.compare_digest` で行う（一致した先頭バイト数が応答時間に
        出ないようにする）。
        """
        if not self.enabled:
            raise FileAccessDenied(
                "jin/open と jin/save は無効です",
                "サーバを `jin lsp --ws PORT --root <ディレクトリ>` で起動してください",
            )
        # **バイト列で比べる。** `secrets.compare_digest` は非 ASCII の str を渡すと
        # `TypeError: comparing strings with non-ASCII characters is not supported` を
        # 投げる（実測）。攻撃者は任意の文字列を送れるので、素の str 比較のままだと
        # 拒否理由が「型エラー」に化けて、防御が働いたのかどうか読めなくなる。
        if not isinstance(presented, str) or not secrets.compare_digest(
            presented.encode("utf-8"), self.token.encode("utf-8")
        ):
            raise FileAccessDenied(
                "トークンが一致しません",
                "jin/open / jin/save の params に token を添えてください"
                "（サーバ起動時に stderr へ出た値）",
            )

    def resolve(self, uri: str) -> Path:
        """`file://` URI を `--root` 配下の `.jin` のパスへ解決する。

        guard: resolve -> raw.resolve
        """
        assert self.root is not None  # authorize() が先に呼ばれている
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise FileAccessDenied(
                f"file:// の URI だけを扱います（受け取った scheme: {parsed.scheme!r}）"
            )
        if parsed.netloc not in ("", "localhost"):
            raise FileAccessDenied(f"別のホストのファイルは扱いません（netloc: {parsed.netloc!r}）")
        raw = Path(unquote(parsed.path))
        if not raw.is_absolute():
            raise FileAccessDenied(f"絶対パスで指定してください: {raw}")
        # **root 配下かどうかは symlink を辿った先で見る**（`..` や、途中の
        # ディレクトリが root の外へ張られた symlink である場合を弾く）。
        try:
            raw.resolve().relative_to(self.root)
        except ValueError as exc:
            raise FileAccessDenied(
                "--root の外を指しています",
                f"許されるのは {self.root} の配下だけです",
            ) from exc
        # **返すのは symlink を辿る前のパス**である。`os.replace` はリンクそのものを
        # 置き換えるので、辿った先のパスを返すと「リンク経由で実体を書き換える」
        # 経路になる（実測で踏んだ: root 配下の link.jin → secret.jin で secret が
        # 書き換わった）。さらに最終要素が symlink なら**そもそも拒む**:
        # root の中だけを見ているつもりの利用者が、リンクの向こう側を
        # 意図せず触ることになる。`jin_cli` の `_write_in_place` が
        # `O_NOFOLLOW` で立てているのと同じ規律である。
        if raw.is_symlink():
            raise FileAccessDenied(
                "シンボリックリンクは扱いません",
                f"{raw} の実体を直接指定してください",
            )
        if raw.suffix != ALLOWED_SUFFIX:
            raise FileAccessDenied(f"{ALLOWED_SUFFIX} 以外は扱いません（拡張子: {raw.suffix!r}）")
        return raw

    def read(self, uri: str) -> str:
        """`.jin` を読む。

        hazard: read -> path.open

        改行を変換せずに読む（`jin_core.check.read_source` と同じ理由。CRLF を畳むと
        正準形との突き合わせが狂う）。
        """
        path = self.resolve(uri)
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                return handle.read()
        except OSError as exc:
            raise FileAccessDenied(
                f"読み込めません（{type(exc).__name__}）",
                f"{path} が存在し、読み取り権限があることを確認してください",
            ) from exc
        except UnicodeDecodeError as exc:
            raise FileAccessDenied(f"UTF-8 として読めません（位置 {exc.start}）") from exc

    def write(self, uri: str, text: str) -> Path:
        """`.jin` を原子的に書く。

        hazard: write -> tempfile.mkstemp
        guard: write -> os.replace

        同じディレクトリに一時ファイルを作って `os.replace` で置き換える。
        `os.replace` は**リンクを辿らず**リンクそのものを置き換えるので、
        書き先が書き込み直前に symlink へすり替えられても、その先の実体は壊れない
        （`resolve()` が symlink を辿る前のパスを返しているからこそ成り立つ）。
        途中で失敗したら一時ファイルを片付ける（残骸を置いていかない）。
        """
        path = self.resolve(uri)
        parent = path.parent
        if not parent.is_dir():
            raise FileAccessDenied(f"ディレクトリがありません: {parent}")
        handle_fd, temporary = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.replace(temporary, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise FileAccessDenied(
                f"書き込めません（{type(exc).__name__}）",
                f"{path} の親ディレクトリに書き込み権限があることを確認してください",
            ) from exc
        return path


def new_token() -> str:
    """起動トークンを作る。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


__all__ = [
    "ALLOWED_SUFFIX",
    "TOKEN_BYTES",
    "FileAccess",
    "FileAccessDenied",
    "new_token",
]
