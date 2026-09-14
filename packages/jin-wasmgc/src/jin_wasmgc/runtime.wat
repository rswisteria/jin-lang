  ;; Jin v2 wasm-GC ランタイム部（docs/spec/v2/jil.md §6.4。プレリュード prelude.lua に相当）。jil: 6
  ;;
  ;; `jin_wasmgc.assemble` が `(module` の直後にそのまま連結し、その後ろに生成部（<program>）を置く。
  ;; ホストが呼ぶ export は input / boot / tick の 3 つ（jil.md §6.2）。import は無い（module はホストを呼ばない）。
  ;; 引数も戻りも UTF-8 の JSON 1 本を線形メモリで越える: ホストは input(n) が返す番地に JSON を書き、
  ;; boot(n) / tick(n) を呼ぶ。tick は結果の (先頭, 長さ) を多値で返す。boot に結果は無い（核の手順の
  ;; エラーは最初の tick の結果に載る・Lua と同じ）。
  ;;
  ;; 線形メモリの配置（生成部が決める。runtime.wat はグローバル $in_base で受ける）:
  ;;   [0, 128)                 ランタイム部の文字列（下の data。128 を超えない・codegen.DATA_BASE と 1:1）
  ;;   [128, $in_base)          生成部の文字列（公開 state の鍵など）
  ;;   [$in_base, +$in_cap)     入力域（input(n) が広げる）
  ;;   [$in_base+$in_cap, …)    出力域（result() が書く。足りなければ memory.grow）
  ;;
  ;; 生成部が定義するもの（codegen.py と 1:1。ここを変えたら JIL の版を上げる）:
  ;;   (memory (export "memory") <pages>)      data と入力域 + 出力域 64 KiB が入る大きさ
  ;;   (global $in_base i32 (i32.const <N>))   入力域の先頭（生成部の data の直後・16 の倍数）
  ;;   (global $ROOT i32 (i32.const <i>))      root の陣の添字（0 始まり）
  ;;   $prog_fresh_state                        全陣を idle にし state を init で作って確定する（fresh_state）
  ;;   $prog_enter_root                         root を entered にして核の手順を走らせる（ENTER(ROOT)）
  ;;   $prog_publish_all                        out の state を確定する（publish_all）
  ;;   $prog_pub_all                            公開 state の JSON 断片を陣の順に書く（各 pub_i は先頭で $pub_comma）
  ;;   $prog_advance                            陣の進行（ADVANCE。root が done なら $DONE）
  ;; Sub-Issue A（#73）の範囲: 上の 5 つと整数の数値書式・fmod。文字列 / list / 純関数 / ホスト能力 /
  ;; 非整数の書式 / 命令数の上限は #74、配達 / 再開 / イベント / flow / トレース / snapshot は #75。

  ;; ---------------------------------------------------------------- ランタイム部の文字列（[0, 128)）
  (data (i32.const 0) "NaN")                                  ;; 0..3
  (data (i32.const 3) "Infinity")                             ;; 3..11
  (data (i32.const 11) "{\"ops\":[],\"audio\":[],\"done\":")  ;; 11..39
  (data (i32.const 39) ",\"error\":null,\"public\":{")        ;; 39..63
  (data (i32.const 63) "true")                                ;; 63..67
  (data (i32.const 67) "false")                               ;; 67..72
  (data (i32.const 72) "}}")                                  ;; 72..74

  ;; ---------------------------------------------------------------- 実行時の状態
  (global $in_cap (mut i32) (i32.const 65536))   ;; 入力域の大きさ（input(n) が広げる）
  (global $out_start (mut i32) (i32.const 0))    ;; 出力域の先頭（result() のたびに $in_base + $in_cap）
  (global $out_ptr (mut i32) (i32.const 0))      ;; 出力の書き込み位置
  (global $DONE (mut i32) (i32.const 0))
  (global $SEED (mut i64) (i64.const 0))         ;; PCG32 の種（#74）
  (global $TICK (mut i64) (i64.const -1))        ;; トレースの tick（#75）
  (global $first (mut i32) (i32.const 1))        ;; public のコンマ（$pub_comma）

  ;; ---------------------------------------------------------------- 線形メモリ
  ;; 少なくとも $bytes バイトある状態にする（足りなければ memory.grow。失敗はホストの資源切れなので trap）。
  (func $ensure (param $bytes i32)
    (local $have i32) (local $need i32)
    (local.set $have (i32.mul (memory.size) (i32.const 65536)))
    (if (i32.gt_u (local.get $bytes) (local.get $have))
      (then
        (local.set $need
          (i32.div_u
            (i32.add (i32.sub (local.get $bytes) (local.get $have)) (i32.const 65535))
            (i32.const 65536)))
        (if (i32.eq (memory.grow (local.get $need)) (i32.const -1)) (then (unreachable))))))

  ;; ホスト境界: 引数 n バイトの入力域を確保しその先頭を返す（jil.md §6.2）。
  (func (export "input") (param $n i32) (result i32)
    (if (i32.gt_u (local.get $n) (global.get $in_cap)) (then (global.set $in_cap (local.get $n))))
    (call $ensure
      (i32.add (global.get $in_base) (i32.add (global.get $in_cap) (i32.const 65536))))
    (global.get $in_base))

  ;; ---------------------------------------------------------------- 出力（JSON の書き手）
  (func $out_begin
    (global.set $out_start (i32.add (global.get $in_base) (global.get $in_cap)))
    (global.set $out_ptr (global.get $out_start)))

  (func $putc (param $b i32)
    (call $ensure (i32.add (global.get $out_ptr) (i32.const 1)))
    (i32.store8 (global.get $out_ptr) (local.get $b))
    (global.set $out_ptr (i32.add (global.get $out_ptr) (i32.const 1))))

  ;; data 区画（[0, $in_base)）の文字列を写す。
  (func $puts (param $off i32) (param $len i32)
    (call $ensure (i32.add (global.get $out_ptr) (local.get $len)))
    (memory.copy (global.get $out_ptr) (local.get $off) (local.get $len))
    (global.set $out_ptr (i32.add (global.get $out_ptr) (local.get $len))))

  (func $put_bool (param $b i32)
    (if (local.get $b)
      (then (call $puts (i32.const 63) (i32.const 4)))
      (else (call $puts (i32.const 67) (i32.const 5)))))

  (func $put_digits (param $v i64)
    (if (i64.ge_u (local.get $v) (i64.const 10))
      (then (call $put_digits (i64.div_u (local.get $v) (i64.const 10)))))
    (call $putc (i32.add (i32.const 48) (i32.wrap_i64 (i64.rem_u (local.get $v) (i64.const 10))))))

  ;; 数値の書式（runtime.md §6 = Python の repr(float) の配置。プレリュードの NUMSTR と同じ）。
  ;; A では NaN / Infinity / 整数の速い経路（|x| < 2^53。-0.0 は "0"）だけ。非整数の最短往復表現は
  ;; #74（Sub-Issue B）で入る。それまでは trap（jil.md §6.2 の規約: trap は生成系の不備）。
  (func $put_num (param $x f64)
    (local $i i64)
    (if (f64.ne (local.get $x) (local.get $x))
      (then (call $puts (i32.const 0) (i32.const 3)) (return)))
    (if (f64.eq (local.get $x) (f64.const inf))
      (then (call $puts (i32.const 3) (i32.const 8)) (return)))
    (if (f64.eq (local.get $x) (f64.const -inf))
      (then (call $putc (i32.const 45)) (call $puts (i32.const 3) (i32.const 8)) (return)))
    (if (i32.and
          (f64.eq (local.get $x) (f64.floor (local.get $x)))
          (f64.lt (f64.abs (local.get $x)) (f64.const 9007199254740992)))
      (then
        (local.set $i (i64.trunc_f64_s (local.get $x)))
        (if (i64.lt_s (local.get $i) (i64.const 0))
          (then
            (call $putc (i32.const 45))
            (local.set $i (i64.sub (i64.const 0) (local.get $i)))))
        (call $put_digits (local.get $i))
        (return)))
    (unreachable))

  ;; JSON の数値（プレリュードの JN）: NaN / Infinity / -Infinity は JSON には文字列として載せる（runtime.md §6）。
  (func $put_jn (param $x f64)
    (if (i32.or
          (f64.ne (local.get $x) (local.get $x))
          (f64.eq (f64.abs (local.get $x)) (f64.const inf)))
      (then
        (call $putc (i32.const 34))
        (call $put_num (local.get $x))
        (call $putc (i32.const 34)))
      (else (call $put_num (local.get $x)))))

  ;; 公開 state の断片の前のコンマ（生成部の pub_i が先頭で呼ぶ）。
  (func $pub_comma
    (if (global.get $first)
      (then (global.set $first (i32.const 0)))
      (else (call $putc (i32.const 44)))))

  ;; tick の結果（runtime.md §1.2 のキーの順。A は ops / audio が空で trace / storage / asks / snapshot は無い）。
  (func $result (result i32 i32)
    (call $out_begin)
    (call $puts (i32.const 11) (i32.const 28))
    (call $put_bool (global.get $DONE))
    (call $puts (i32.const 39) (i32.const 24))
    (global.set $first (i32.const 1))
    (call $prog_pub_all)
    (call $puts (i32.const 72) (i32.const 2))
    (global.get $out_start)
    (i32.sub (global.get $out_ptr) (global.get $out_start)))

  ;; ---------------------------------------------------------------- 入力（JSON の読み手）
  ;; A の最小形: 入力域の最初の `:` の後ろの整数（`{"seed": 7, …}` / `{"t": 3, …}`）。
  ;; manifest / inputs の汎用の読み手は #74 / #75。
  (func $read_first_int (param $n i32) (result i64)
    (local $p i32) (local $end i32) (local $c i32) (local $neg i32) (local $v i64)
    (local.set $p (global.get $in_base))
    (local.set $end (i32.add (local.get $p) (local.get $n)))
    (block $colon
      (loop $scan
        (br_if $colon (i32.ge_u (local.get $p) (local.get $end)))
        (local.set $c (i32.load8_u (local.get $p)))
        (local.set $p (i32.add (local.get $p) (i32.const 1)))
        (br_if $colon (i32.eq (local.get $c) (i32.const 58)))
        (br $scan)))
    (block $spaces
      (loop $skip
        (br_if $spaces (i32.ge_u (local.get $p) (local.get $end)))
        (br_if $spaces (i32.ne (i32.load8_u (local.get $p)) (i32.const 32)))
        (local.set $p (i32.add (local.get $p) (i32.const 1)))
        (br $skip)))
    (if (i32.and
          (i32.lt_u (local.get $p) (local.get $end))
          (i32.eq (i32.load8_u (local.get $p)) (i32.const 45)))
      (then (local.set $neg (i32.const 1)) (local.set $p (i32.add (local.get $p) (i32.const 1)))))
    (block $digits
      (loop $next
        (br_if $digits (i32.ge_u (local.get $p) (local.get $end)))
        (local.set $c (i32.sub (i32.load8_u (local.get $p)) (i32.const 48)))
        (br_if $digits (i32.gt_u (local.get $c) (i32.const 9)))
        (local.set $v
          (i64.add (i64.mul (local.get $v) (i64.const 10)) (i64.extend_i32_u (local.get $c))))
        (local.set $p (i32.add (local.get $p) (i32.const 1)))
        (br $next)))
    (if (local.get $neg) (then (local.set $v (i64.sub (i64.const 0) (local.get $v)))))
    (local.get $v))

  ;; ---------------------------------------------------------------- 算術
  ;; C の fmod（結果の符号は a）。wasm に fmod は無いので、b·2^k を引く反復で**正確に**求める
  ;; （t ≤ x ≤ 2t なら x − t は正確・Sterbenz）。
  (func $fmod (param $a f64) (param $b f64) (result f64)
    (local $x f64) (local $y f64) (local $t f64)
    (if (i32.or
          (i32.or (f64.ne (local.get $a) (local.get $a)) (f64.ne (local.get $b) (local.get $b)))
          (i32.or
            (f64.eq (f64.abs (local.get $a)) (f64.const inf))
            (f64.eq (local.get $b) (f64.const 0))))
      (then (return (f64.const nan))))
    (if (f64.eq (f64.abs (local.get $b)) (f64.const inf)) (then (return (local.get $a))))
    (local.set $x (f64.abs (local.get $a)))
    (local.set $y (f64.abs (local.get $b)))
    (block $done
      (loop $outer
        (br_if $done (f64.lt (local.get $x) (local.get $y)))
        (local.set $t (local.get $y))
        (block $fits
          (loop $double
            (br_if $fits (f64.ge (f64.mul (local.get $t) (f64.const 2)) (local.get $x)))
            (local.set $t (f64.mul (local.get $t) (f64.const 2)))
            (br $double)))
        (local.set $x (f64.sub (local.get $x) (local.get $t)))
        (br $outer)))
    (f64.copysign (local.get $x) (local.get $a)))

  ;; Lua 5.4 の `a % b`（luai_nummod: fmod の後、余りが 0 でなく符号が b と違えば b を足す = floor 除算の余り）。
  (func $lmod (param $a f64) (param $b f64) (result f64)
    (local $m f64)
    (local.set $m (call $fmod (local.get $a) (local.get $b)))
    (if (i32.and
          (f64.ne (local.get $m) (f64.const 0))
          (i32.ne (f64.lt (local.get $m) (f64.const 0)) (f64.lt (local.get $b) (f64.const 0))))
      (then (local.set $m (f64.add (local.get $m) (local.get $b)))))
    (local.get $m))

  ;; ---------------------------------------------------------------- ホスト境界（runtime.md §1 の wasm 版）
  (func (export "boot") (param $n i32)
    (global.set $SEED (call $read_first_int (local.get $n)))
    (global.set $DONE (i32.const 0))
    (global.set $TICK (i64.const -1))
    (call $prog_fresh_state)
    (call $prog_enter_root)
    (call $prog_advance)
    (call $prog_publish_all))

  (func (export "tick") (param $n i32) (result i32 i32)
    (global.set $TICK (call $read_first_int (local.get $n)))
    (if (i32.eqz (global.get $DONE))
      (then
        (call $prog_publish_all)
        (call $prog_advance)))
    (call $result))
