"""jin-wasmgc のテスト用ヘルパ: ランタイム部の関数を test だけの export で叩く。

通常のビルドの export は 4 つのまま（`test_module_has_no_imports_and_exactly_the_host_exports`）。
ここでは `module_text` の閉じ括弧の前に test 用の関数を足した module を作り、文字列は入力域
（`input(n)` の番地）で渡して出力域（`$flush`）で受ける。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jin_core.check import check_file
from jin_core.v2.model import JinFileV2
from jin_wasmgc.assemble import module_text, runtime_source
from jin_wasmgc.codegen import generate_program
from wasmtime import Engine, Instance, Module, Store, wat2wasm

REPO_ROOT = Path(__file__).resolve().parents[3]
FIB = REPO_ROOT / "examples-v2" / "fib" / "fib.jin"

#: test だけの export（ランタイム部の内側の関数を線形メモリ越しに叩く）。
TEST_EXPORTS = """
  (func (export "t_numstr") (param $x f64) (result i32 i32)
    (global.set $OUT (call $buf_new (i32.const 64)))
    (call $put_num (local.get $x))
    (call $flush))
  (func (export "t_strtod") (param $n i32) (result f64)
    (call $strtod (call $mem_str (global.get $in_base) (local.get $n))))
  (func (export "t_num") (param $n i32) (result f64)
    (call $f_num (call $mem_str (global.get $in_base) (local.get $n))))
  (func (export "t_js") (param $n i32) (result i32 i32)
    (global.set $OUT (call $buf_new (i32.const 64)))
    (call $put_js (call $mem_str (global.get $in_base) (local.get $n)))
    (call $flush))
  (func (export "t_len") (param $n i32) (result f64)
    (call $f_len (call $mem_str (global.get $in_base) (local.get $n))))
  (func (export "t_sub") (param $n i32) (param $i f64) (param $k f64) (result i32 i32)
    (global.set $OUT (call $buf_new (i32.const 64)))
    (call $put_str (call $f_sub (call $mem_str (global.get $in_base) (local.get $n)) (local.get $i) (local.get $k)))
    (call $flush))
  (func (export "t_cmp") (param $n1 i32) (param $n2 i32) (result f64)
    (call $f_cmp (call $mem_str (global.get $in_base) (local.get $n1))
      (call $mem_str (i32.add (global.get $in_base) (local.get $n1)) (local.get $n2))))
  (func (export "t_sin") (param $x f64) (result f64) (call $f_sin (local.get $x)))
  (func (export "t_cos") (param $x f64) (result f64) (call $f_cos (local.get $x)))
  (func (export "t_atan2") (param $y f64) (param $x f64) (result f64) (call $f_atan2 (local.get $y) (local.get $x)))
  (func (export "t_round") (param $x f64) (result f64) (call $f_round (local.get $x)))
  (func (export "t_min") (param $a f64) (param $b f64) (result f64) (call $f_min (local.get $a) (local.get $b)))
  (func (export "t_max") (param $a f64) (param $b f64) (result f64) (call $f_max (local.get $a) (local.get $b)))
  (func (export "t_floor") (param $x f64) (result f64) (call $f_floor (local.get $x)))
  (func (export "t_lmod") (param $a f64) (param $b f64) (result f64) (call $lmod (local.get $a) (local.get $b)))
  (func (export "t_rng_seed") (param $s i64) (call $rng_seed (local.get $s)))
  (func (export "t_rng_step") (result i32) (call $rng_step))
  ;; JSON を読んで書き戻す（読み手の検算）
  (func $t_j_put (param $v (ref null $J))
    (local $k i32) (local $n i32) (local $kind i32)
    (local.set $kind (call $j_kind (local.get $v)))
    (if (i32.eqz (local.get $kind)) (then (call $puts (i32.const @NULL@) (i32.const 4)) (return)))
    (if (i32.eq (local.get $kind) (i32.const 1))
      (then (call $put_bool (f64.ne (struct.get $J 1 (local.get $v)) (f64.const 0))) (return)))
    (if (i32.eq (local.get $kind) (i32.const 2)) (then (call $put_jn (struct.get $J 1 (local.get $v))) (return)))
    (if (i32.eq (local.get $kind) (i32.const 3)) (then (call $put_js (struct.get $J 2 (local.get $v))) (return)))
    (if (i32.eq (local.get $kind) (i32.const 4))
      (then
        (call $putc (i32.const 91))
        (local.set $n (call $j_len (local.get $v)))
        (block $done (loop $next
          (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
          (if (local.get $k) (then (call $putc (i32.const 44))))
          (call $t_j_put (call $j_at (local.get $v) (local.get $k)))
          (local.set $k (i32.add (local.get $k) (i32.const 1)))
          (br $next)))
        (call $putc (i32.const 93))
        (return)))
    (call $putc (i32.const 123))
    (local.set $n (struct.get $Lr 1 (struct.get $J 3 (local.get $v))))
    (block $done2 (loop $next2
      (br_if $done2 (i32.ge_u (local.get $k) (local.get $n)))
      (if (local.get $k) (then (call $putc (i32.const 44))))
      (call $put_js (ref.cast (ref null $str) (array.get $lr (struct.get $Lr 0 (struct.get $J 3 (local.get $v))) (local.get $k))))
      (call $putc (i32.const 58))
      (call $t_j_put (ref.cast (ref null $J) (array.get $lr (struct.get $Lr 0 (struct.get $J 4 (local.get $v))) (local.get $k))))
      (local.set $k (i32.add (local.get $k) (i32.const 1)))
      (br $next2)))
    (call $putc (i32.const 125)))
  (func (export "t_json") (param $n i32) (result i32 i32)
    (local $v (ref null $J))
    (local.set $v (call $parse_input (local.get $n)))
    (global.set $OUT (call $buf_new (i32.const 64)))
    (call $t_j_put (local.get $v))
    (call $flush))
"""


def load(path: Path) -> JinFileV2:
    result = check_file(path)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.model, JinFileV2)
    return result.model


class Probe:
    """test 用 export を持つ module（生成部は fib）。文字列は入力域で渡し、出力域で受ける。"""

    def __init__(self) -> None:
        wat = module_text(generate_program(load(FIB)), source_name="fib.jin")
        assert wat.endswith(")\n")
        null = re.search(r'\(data \(i32\.const (\d+)\) "null"\)', runtime_source())
        assert null is not None
        wat = wat[:-2] + TEST_EXPORTS.replace("@NULL@", null.group(1)) + ")\n"
        self.store = Store(Engine())
        self.instance = Instance(self.store, Module(self.store.engine, wat2wasm(wat)), [])
        self.exports = self.instance.exports(self.store)
        self.memory = self.exports["memory"]

    def _read(self, pair: Any) -> str:
        ptr, length = (int(v) for v in pair)
        return bytes(self.memory.read(self.store, ptr, ptr + length)).decode("utf-8")

    def _write(self, *texts: str) -> list[int]:
        raw = [t.encode("utf-8") for t in texts]
        ptr = self.exports["input"](self.store, sum(len(r) for r in raw))
        self.memory.write(self.store, b"".join(raw), ptr)
        return [len(r) for r in raw]

    def numstr(self, x: float) -> str:
        return self._read(self.exports["t_numstr"](self.store, x))

    def strtod(self, text: str) -> float:
        return self.exports["t_strtod"](self.store, *self._write(text))

    def num(self, text: str) -> float:
        return self.exports["t_num"](self.store, *self._write(text))

    def js(self, text: str) -> str:
        return self._read(self.exports["t_js"](self.store, *self._write(text)))

    def json_roundtrip(self, value: Any) -> Any:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.loads(self._read(self.exports["t_json"](self.store, *self._write(text))))

    def length(self, text: str) -> float:
        return self.exports["t_len"](self.store, *self._write(text))

    def sub(self, text: str, i: float, n: float) -> str:
        return self._read(self.exports["t_sub"](self.store, *self._write(text), float(i), float(n)))

    def cmp(self, a: str, b: str) -> float:
        return self.exports["t_cmp"](self.store, *self._write(a, b))

    def call(self, name: str, *args: Any) -> Any:
        return self.exports[name](self.store, *args)


@pytest.fixture(scope="module")
def probe() -> Probe:
    return Probe()
