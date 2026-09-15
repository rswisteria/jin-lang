"""`packages/jin-wasmgc/src/jin_wasmgc/runtime.wat`（wasm-GC のランタイム部）を部品から生成する（jil.md §6.4）。

`runtime.wat` は**生成物**で、手で編集しない。正典は `packages/jin-wasmgc/runtime/`:

    01_head.wat … 05_sched.wat   ランタイム部の本文（ファイル名順に連結する）
    strings.json                  data 区画の文字列の表 `[[名前, 文字列], …]`（この順に番地を振る）

本文の中の目印を置き換える:

    @K:name@      → `(i32.const <番地>) (i32.const <長さ>)`（`$puts` / `$mem_str` などの引数）
    @OFF:name@    → 番地、`@LEN:name@` → 長さ
    @DATA@        → `(data (i32.const <番地>) "…")` の列（[0, 2048) に閉じる。`codegen.DATA_BASE` と 1:1）
    @LISTS@       → list の 3 表現（`$Lf` / `$Li` / `$Lr`）の関数群（`LIST_TEMPLATE` を要素の型ごとに展開）

文字列を足す / 変えるときは `strings.json` を直して再生成する。番地は表の順に詰めて振るので、途中に足すと
後ろの番地が全部ずれるが、それは生成物の差分として見えるだけでよい（`test_runtime_strings_stay_below_the_program_data_base`
が生成物の番地と長さを data 区画と独立に突き合わせる）。

使い方:

    uv run python scripts/generate_runtime_wat.py            # runtime.wat を書き直す（変わらなければ触らない）
    uv run python scripts/generate_runtime_wat.py --check    # ずれていたら exit 1（pytest が走らせる）
    uv run python scripts/generate_runtime_wat.py --stdout   # 標準出力へ（CI が diff で比べる。ツリーを書き換えない）

このスクリプトは jin_wasmgc を import しない（`uv run` の外でも動くように）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PARTS_DIR = REPO_ROOT / "packages" / "jin-wasmgc" / "runtime"
STRINGS = PARTS_DIR / "strings.json"
OUTPUT = REPO_ROOT / "packages" / "jin-wasmgc" / "src" / "jin_wasmgc" / "runtime.wat"

#: ランタイム部の文字列が収まる範囲（`jin_wasmgc.codegen.DATA_BASE`。生成部の data はここから）。
DATA_BASE = 2048

#: list の 1 表現ぶんの関数群。`{s}` は表現の添字（f / i / r）、`{L}` / `{A}` は struct / array の型、`{T}` は要素の型。
LIST_TEMPLATE = """
  ;; list<{doc}>（{L}）
  (func $l{s}_new (param $cap i32) (result (ref {L}))
    (struct.new {L} (array.new_default {A} (select (local.get $cap) (i32.const 4) (i32.gt_u (local.get $cap) (i32.const 4)))) (i32.const 0)))

  (func $l{s}_push (param $l (ref null {L})) (param $v {T})
    (local $n i32) (local $arr (ref null {A})) (local $new (ref null {A}))
    (local.set $n (struct.get {L} 1 (local.get $l)))
    (local.set $arr (struct.get {L} 0 (local.get $l)))
    (if (i32.eq (local.get $n) (array.len (local.get $arr)))
      (then
        (local.set $new (array.new_default {A} (i32.mul (i32.add (local.get $n) (i32.const 1)) (i32.const 2))))
        (array.copy {A} {A} (local.get $new) (i32.const 0) (local.get $arr) (i32.const 0) (local.get $n))
        (struct.set {L} 0 (local.get $l) (ref.as_non_null (local.get $new)))
        (local.set $arr (local.get $new))))
    (array.set {A} (local.get $arr) (local.get $n) (local.get $v))
    (struct.set {L} 1 (local.get $l) (i32.add (local.get $n) (i32.const 1))))

  (func $l{s}_pushr (param $l (ref null {L})) (param $v {T}) (result (ref {L}))
    (call $l{s}_push (local.get $l) (local.get $v))
    (ref.as_non_null (local.get $l)))

  (func $l{s}_len (param $l (ref null {L})) (result i32) (struct.get {L} 1 (local.get $l)))

  (func $l{s}_get (param $l (ref null {L})) (param $k i32) (result {T})
    (array.get {A} (struct.get {L} 0 (local.get $l)) (local.get $k)))

  ;; 範囲外なら ERR して $dflt を返す（$Lr の要素は非 null へ ref.cast されるので null は返せない。生成部が型の既定値を渡す）
  (func $l{s}_at (param $l (ref null {L})) (param $i f64) (param $dflt {T}) (result {T})
    (local $k i32)
    (local.set $k (call $index_of (struct.get {L} 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return (local.get $dflt))))
    (array.get {A} (struct.get {L} 0 (local.get $l)) (local.get $k)))

  (func $l{s}_set (param $l (ref null {L})) (param $i f64) (param $v {T})
    (local $k i32)
    (local.set $k (call $index_of (struct.get {L} 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (array.set {A} (struct.get {L} 0 (local.get $l)) (local.get $k) (local.get $v)))

  (func $e_push_{s} (param $l (ref null {L})) (param $v {T})
    (if (global.get $ERRED) (then (return)))
    (call $l{s}_push (local.get $l) (local.get $v)))

  (func $e_remove_{s} (param $l (ref null {L})) (param $i f64)
    (local $k i32) (local $n i32) (local $arr (ref null {A}))
    (if (global.get $ERRED) (then (return)))
    (local.set $n (struct.get {L} 1 (local.get $l)))
    (local.set $k (call $index_of (local.get $n) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (local.set $arr (struct.get {L} 0 (local.get $l)))
    (array.copy {A} {A} (local.get $arr) (local.get $k) (local.get $arr) (i32.add (local.get $k) (i32.const 1))
      (i32.sub (i32.sub (local.get $n) (local.get $k)) (i32.const 1)))
    (struct.set {L} 1 (local.get $l) (i32.sub (local.get $n) (i32.const 1))))

  (func $e_clear_{s} (param $l (ref null {L}))
    (if (global.get $ERRED) (then (return)))
    (struct.set {L} 1 (local.get $l) (i32.const 0)))

  (func $f_contains_{s} (param $l (ref null {L})) (param $v {T}) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (struct.get {L} 1 (local.get $l)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if {eq}
          (then (return (i32.const 1))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $f_len_{s} (param $l (ref null {L})) (result f64)
    (f64.convert_i32_u (struct.get {L} 1 (local.get $l))))
"""

#: list の 3 表現（jil.md §6.3。要素が num / bool / 参照）。`eq` は `contains` の比較。
LIST_VARIANTS = [
    {
        "s": "f",
        "L": "$Lf",
        "A": "$lf",
        "T": "f64",
        "doc": "num",
        "eq": "(f64.eq (array.get $lf (struct.get $Lf 0 (local.get $l)) (local.get $i)) (local.get $v))",
    },
    {
        "s": "i",
        "L": "$Li",
        "A": "$li",
        "T": "i32",
        "doc": "bool",
        "eq": "(i32.eq (array.get $li (struct.get $Li 0 (local.get $l)) (local.get $i)) (local.get $v))",
    },
    {
        "s": "r",
        "L": "$Lr",
        "A": "$lr",
        "T": "anyref",
        "doc": "str / 型紙 / list",
        "eq": (
            "(ref.eq (ref.cast (ref null eq) (array.get $lr (struct.get $Lr 0 (local.get $l)) "
            "(local.get $i))) (ref.cast (ref null eq) (local.get $v)))"
        ),
    },
]


class GenerateError(Exception):
    pass


def wat_string(text: str) -> str:
    """WAT の文字列リテラル（UTF-8 のバイト列。印字可能な ASCII 以外は `\\xx`）。"""
    out = []
    for b in text.encode("utf-8"):
        if 0x20 <= b < 0x7F and b not in (0x22, 0x5C):
            out.append(chr(b))
        else:
            out.append(f"\\{b:02x}")
    return '"' + "".join(out) + '"'


def load_strings() -> list[tuple[str, str]]:
    try:
        table = json.loads(STRINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GenerateError(f"{STRINGS} を読めません: {exc}") from exc
    consts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in table:
        if not (
            isinstance(item, list) and len(item) == 2 and all(isinstance(v, str) for v in item)
        ):
            raise GenerateError(f"{STRINGS}: [名前, 文字列] の対ではありません: {item!r}")
        name, text = item
        if not re.fullmatch(r"[a-z_0-9]+", name):
            raise GenerateError(f"{STRINGS}: 名前は [a-z_0-9]+ です: {name!r}")
        if name in seen:
            raise GenerateError(f"{STRINGS}: 名前 {name!r} が重複しています")
        seen.add(name)
        consts.append((name, text))
    return consts


def generate() -> str:
    """部品を連結し、目印を置き換えた `runtime.wat` の本文。"""
    parts = sorted(PARTS_DIR.glob("*.wat"))
    if not parts:
        raise GenerateError(f"{PARTS_DIR} に部品（*.wat）がありません")
    body = "\n".join(p.read_text(encoding="utf-8") for p in parts)
    table: dict[str, tuple[int, int]] = {}
    off = 0
    data_lines = []
    for name, text in load_strings():
        raw = text.encode("utf-8")
        table[name] = (off, len(raw))
        data_lines.append(
            f"  (data (i32.const {off}) {wat_string(text)})  ;; {name} {off}..{off + len(raw)}"
        )
        off += len(raw)
    if off > DATA_BASE:
        raise GenerateError(
            f"ランタイム部の文字列が {off} バイトで DATA_BASE = {DATA_BASE} を超えます（jil.md §6.3）"
        )

    def lookup(m: re.Match[str]) -> tuple[int, int]:
        try:
            return table[m.group(1)]
        except KeyError:
            raise GenerateError(f"strings.json に無い名前を参照しています: {m.group(0)}") from None

    body = re.sub(
        r"@K:([a-z_0-9]+)@",
        lambda m: "(i32.const {}) (i32.const {})".format(*lookup(m)),
        body,
    )
    body = re.sub(r"@OFF:([a-z_0-9]+)@", lambda m: str(lookup(m)[0]), body)
    body = re.sub(r"@LEN:([a-z_0-9]+)@", lambda m: str(lookup(m)[1]), body)
    if body.count("@DATA@") != 1 or body.count("@LISTS@") != 1:
        raise GenerateError("部品の中に @DATA@ と @LISTS@ がちょうど 1 つずつ要ります")
    body = body.replace("@DATA@", "\n".join(data_lines))
    body = body.replace("@LISTS@", "".join(LIST_TEMPLATE.format(**v) for v in LIST_VARIANTS))
    unknown = re.findall(r"@[A-Z]+:[a-z_0-9]+@|@[A-Z]+@", body)
    if unknown:
        raise GenerateError(f"置き換えられない目印が残っています: {sorted(set(unknown))}")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="runtime.wat を部品から生成する")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="ずれていたら exit 1（書き換えない）")
    mode.add_argument("--stdout", action="store_true", help="標準出力へ書く（書き換えない）")
    args = parser.parse_args(argv)
    try:
        text = generate()
    except GenerateError as error:
        print(f"generate_runtime_wat: {error}", file=sys.stderr)
        return 1
    if args.stdout:
        sys.stdout.write(text)
        return 0
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else None
    if args.check:
        if current != text:
            print(
                f"{OUTPUT.relative_to(REPO_ROOT)} が部品からの生成物とずれています。"
                "`uv run python scripts/generate_runtime_wat.py` で再生成してください。",
                file=sys.stderr,
            )
            return 1
        print("runtime.wat は部品と一致しています")
        return 0
    if current == text:
        print(f"{OUTPUT.relative_to(REPO_ROOT)} は変わっていません")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"{OUTPUT.relative_to(REPO_ROOT)} を書きました（{len(text.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
