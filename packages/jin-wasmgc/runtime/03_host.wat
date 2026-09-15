
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

  ;; ---------------------------------------------------------------- エラーと命令数の上限（jil.md §6.4 / §6.6）
  ;; 最初のエラーだけを残す（Lua の error は最初の 1 つでスケジューラの pcall へ抜ける）。
  (func $ERR (param $msg (ref null $str))
    (if (i32.eqz (global.get $ERRED))
      (then
        (global.set $ERRED (i32.const 1))
        (global.set $ERRMSG (local.get $msg))
        (global.set $DONE (i32.const 1)))))

  ;; 生成部がループの戻り辺と手順の呼び出しに埋める（値と文は Lua 経路の INSTRUCTION_BUDGET / _SETUP と同じ）。
  (func $bud
    (global.set $BUDGET (i32.sub (global.get $BUDGET) (i32.const 1)))
    (if (i32.le_s (global.get $BUDGET) (i32.const 0))
      (then (call $ERR (call $mem_str @K:msg_budget@)))))

  ;; ---------------------------------------------------------------- JSON の読み手（線形メモリ [$JP, $JEND)）
  (func $j_new (param $kind i32) (param $num f64) (param $s (ref null $str)) (param $keys (ref null $Lr)) (param $vals (ref null $Lr)) (result (ref $J))
    (struct.new $J (local.get $kind) (local.get $num) (local.get $s) (local.get $keys) (local.get $vals)))

  (func $jp_ws
    (local $c i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (global.get $JP) (global.get $JEND)))
        (local.set $c (i32.load8_u (global.get $JP)))
        (br_if $done (i32.eqz (i32.or (i32.or (i32.eq (local.get $c) (i32.const 32)) (i32.eq (local.get $c) (i32.const 9)))
                                      (i32.or (i32.eq (local.get $c) (i32.const 10)) (i32.eq (local.get $c) (i32.const 13))))))
        (global.set $JP (i32.add (global.get $JP) (i32.const 1)))
        (br $next))))

  (func $jp_peek (result i32)
    (if (result i32) (i32.lt_u (global.get $JP) (global.get $JEND))
      (then (i32.load8_u (global.get $JP)))
      (else (i32.const -1))))

  (func $jp_skip (param $n i32)
    (global.set $JP (i32.add (global.get $JP) (local.get $n)))
    (if (i32.gt_u (global.get $JP) (global.get $JEND)) (then (global.set $JP (global.get $JEND)))))

  (func $jp_hex4 (result i32)
    (local $i i32) (local $v i32) (local $c i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (i32.const 4)))
        (local.set $c (call $jp_peek))
        (call $jp_skip (i32.const 1))
        (if (i32.le_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9))
          (then (local.set $c (i32.sub (local.get $c) (i32.const 48))))
          (else (local.set $c (i32.add (i32.and (local.get $c) (i32.const 0xDF)) (i32.const -55)))))   ;; A-F / a-f → 10..15
        (local.set $v (i32.or (i32.shl (local.get $v) (i32.const 4)) (i32.and (local.get $c) (i32.const 15))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (local.get $v))

  ;; コードポイントを UTF-8 で書き手へ。
  (func $put_utf8 (param $cp i32)
    (if (i32.lt_u (local.get $cp) (i32.const 0x80))
      (then (call $putc (local.get $cp)) (return)))
    (if (i32.lt_u (local.get $cp) (i32.const 0x800))
      (then
        (call $putc (i32.or (i32.const 0xC0) (i32.shr_u (local.get $cp) (i32.const 6))))
        (call $putc (i32.or (i32.const 0x80) (i32.and (local.get $cp) (i32.const 0x3F))))
        (return)))
    (if (i32.lt_u (local.get $cp) (i32.const 0x10000))
      (then
        (call $putc (i32.or (i32.const 0xE0) (i32.shr_u (local.get $cp) (i32.const 12))))
        (call $putc (i32.or (i32.const 0x80) (i32.and (i32.shr_u (local.get $cp) (i32.const 6)) (i32.const 0x3F))))
        (call $putc (i32.or (i32.const 0x80) (i32.and (local.get $cp) (i32.const 0x3F))))
        (return)))
    (call $putc (i32.or (i32.const 0xF0) (i32.shr_u (local.get $cp) (i32.const 18))))
    (call $putc (i32.or (i32.const 0x80) (i32.and (i32.shr_u (local.get $cp) (i32.const 12)) (i32.const 0x3F))))
    (call $putc (i32.or (i32.const 0x80) (i32.and (i32.shr_u (local.get $cp) (i32.const 6)) (i32.const 0x3F))))
    (call $putc (i32.or (i32.const 0x80) (i32.and (local.get $cp) (i32.const 0x3F)))))

  ;; `"` の位置から文字列を読む（\uXXXX はサロゲート対を含めて UTF-8 に戻す）。
  (func $jp_string (result (ref $str))
    (local $old (ref null $buf)) (local $c i32) (local $cp i32) (local $lo i32)
    (local.set $old (call $fmt_begin))
    (call $jp_skip (i32.const 1))
    (block $done
      (loop $next
        (local.set $c (call $jp_peek))
        (br_if $done (i32.lt_s (local.get $c) (i32.const 0)))
        (call $jp_skip (i32.const 1))
        (br_if $done (i32.eq (local.get $c) (i32.const 34)))
        (if (i32.eq (local.get $c) (i32.const 92))
          (then
            (local.set $c (call $jp_peek))
            (call $jp_skip (i32.const 1))
            (if (i32.eq (local.get $c) (i32.const 110)) (then (call $putc (i32.const 10)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 114)) (then (call $putc (i32.const 13)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 116)) (then (call $putc (i32.const 9)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 98)) (then (call $putc (i32.const 8)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 102)) (then (call $putc (i32.const 12)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 117))
              (then
                (local.set $cp (call $jp_hex4))
                (if (i32.and (i32.ge_u (local.get $cp) (i32.const 0xD800)) (i32.le_u (local.get $cp) (i32.const 0xDBFF)))
                  (then
                    (if (i32.and
                          (i32.le_u (i32.add (global.get $JP) (i32.const 6)) (global.get $JEND))
                          (i32.and (i32.eq (i32.load8_u (global.get $JP)) (i32.const 92))
                                   (i32.eq (i32.load8_u (i32.add (global.get $JP) (i32.const 1))) (i32.const 117))))
                      (then
                        (call $jp_skip (i32.const 2))
                        (local.set $lo (call $jp_hex4))
                        (local.set $cp (i32.add (i32.const 0x10000)
                          (i32.or (i32.shl (i32.sub (local.get $cp) (i32.const 0xD800)) (i32.const 10))
                                  (i32.and (i32.sub (local.get $lo) (i32.const 0xDC00)) (i32.const 0x3FF)))))))))
                (call $put_utf8 (local.get $cp))
                (br $next)))
            (br_if $done (i32.lt_s (local.get $c) (i32.const 0)))
            (call $putc (local.get $c))
            (br $next)))
        (call $putc (local.get $c))
        (br $next)))
    (call $fmt_end (local.get $old)))

  (func $jp_number (result (ref $J))
    (local $old (ref null $buf)) (local $c i32)
    (local.set $old (call $fmt_begin))
    (block $done
      (loop $next
        (local.set $c (call $jp_peek))
        (br_if $done (i32.lt_s (local.get $c) (i32.const 0)))
        (br_if $done (i32.eqz (i32.or
          (i32.or (i32.le_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9)) (i32.eq (local.get $c) (i32.const 46)))
          (i32.or (i32.or (i32.eq (local.get $c) (i32.const 45)) (i32.eq (local.get $c) (i32.const 43)))
                  (i32.eq (i32.or (local.get $c) (i32.const 32)) (i32.const 101))))))
        (call $putc (local.get $c))
        (call $jp_skip (i32.const 1))
        (br $next)))
    (call $j_new (i32.const 2) (f64.add (call $strtod (call $fmt_end (local.get $old))) (f64.const 0))
      (ref.null $str) (ref.null $Lr) (ref.null $Lr)))

  (func $jp_array (result (ref $J))
    (local $vals (ref null $Lr)) (local $c i32)
    (local.set $vals (call $lr_new (i32.const 4)))
    (call $jp_skip (i32.const 1))
    (call $jp_ws)
    (if (i32.eq (call $jp_peek) (i32.const 93))
      (then (call $jp_skip (i32.const 1)))
      (else
        (block $done
          (loop $next
            (call $lr_push (local.get $vals) (call $jp_value))
            (call $jp_ws)
            (local.set $c (call $jp_peek))
            (if (i32.eq (local.get $c) (i32.const 44))
              (then (call $jp_skip (i32.const 1)) (call $jp_ws) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 93)) (then (call $jp_skip (i32.const 1))))
            (br $done)))))
    (call $j_new (i32.const 4) (f64.const 0) (ref.null $str) (ref.null $Lr) (local.get $vals)))

  (func $jp_object (result (ref $J))
    (local $keys (ref null $Lr)) (local $vals (ref null $Lr)) (local $c i32)
    (local.set $keys (call $lr_new (i32.const 4)))
    (local.set $vals (call $lr_new (i32.const 4)))
    (call $jp_skip (i32.const 1))
    (block $done
      (loop $next
        (call $jp_ws)
        (local.set $c (call $jp_peek))
        (if (i32.eq (local.get $c) (i32.const 125)) (then (call $jp_skip (i32.const 1)) (br $done)))
        (br_if $done (i32.ne (local.get $c) (i32.const 34)))
        (call $lr_push (local.get $keys) (call $jp_string))
        (call $jp_ws)
        (if (i32.eq (call $jp_peek) (i32.const 58)) (then (call $jp_skip (i32.const 1))))
        (call $lr_push (local.get $vals) (call $jp_value))
        (call $jp_ws)
        (local.set $c (call $jp_peek))
        (if (i32.eq (local.get $c) (i32.const 44)) (then (call $jp_skip (i32.const 1)) (br $next)))
        (if (i32.eq (local.get $c) (i32.const 125)) (then (call $jp_skip (i32.const 1))))
        (br $done)))
    (call $j_new (i32.const 5) (f64.const 0) (ref.null $str) (local.get $keys) (local.get $vals)))

  (func $jp_value (result (ref $J))
    (local $c i32)
    (call $jp_ws)
    (local.set $c (call $jp_peek))
    (if (i32.eq (local.get $c) (i32.const 123)) (then (return (call $jp_object))))
    (if (i32.eq (local.get $c) (i32.const 91)) (then (return (call $jp_array))))
    (if (i32.eq (local.get $c) (i32.const 34))
      (then (return (call $j_new (i32.const 3) (f64.const 0) (call $jp_string) (ref.null $Lr) (ref.null $Lr)))))
    (if (i32.eq (local.get $c) (i32.const 116))
      (then (call $jp_skip (i32.const 4)) (return (call $j_new (i32.const 1) (f64.const 1) (ref.null $str) (ref.null $Lr) (ref.null $Lr)))))
    (if (i32.eq (local.get $c) (i32.const 102))
      (then (call $jp_skip (i32.const 5)) (return (call $j_new (i32.const 1) (f64.const 0) (ref.null $str) (ref.null $Lr) (ref.null $Lr)))))
    (if (i32.eq (local.get $c) (i32.const 110))
      (then (call $jp_skip (i32.const 4)) (return (call $j_new (i32.const 0) (f64.const 0) (ref.null $str) (ref.null $Lr) (ref.null $Lr)))))
    (if (i32.or (i32.eq (local.get $c) (i32.const 45)) (i32.le_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9)))
      (then (return (call $jp_number))))
    (if (i32.ge_s (local.get $c) (i32.const 0)) (then (call $jp_skip (i32.const 1))))
    (call $j_new (i32.const 0) (f64.const 0) (ref.null $str) (ref.null $Lr) (ref.null $Lr)))

  ;; 入力域 [in_base, in_base + n) を読む。
  (func $parse_input (param $n i32) (result (ref $J))
    (global.set $JP (global.get $in_base))
    (global.set $JEND (i32.add (global.get $in_base) (local.get $n)))
    (call $jp_value))

  ;; 読み手の木のアクセス（形が合わなければ null / 0。Lua の RREC / RN / RB / RSTR と同じ姿勢）
  (func $j_kind (param $v (ref null $J)) (result i32)
    (if (result i32) (ref.is_null (local.get $v)) (then (i32.const 0)) (else (struct.get $J 0 (local.get $v)))))

  (func $j_get (param $o (ref null $J)) (param $key (ref null $str)) (result (ref null $J))
    (local $keys (ref null $Lr)) (local $i i32) (local $n i32)
    (if (i32.ne (call $j_kind (local.get $o)) (i32.const 5)) (then (return (ref.null $J))))
    (local.set $keys (struct.get $J 3 (local.get $o)))
    (local.set $n (struct.get $Lr 1 (local.get $keys)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (call $str_eq (ref.cast (ref null $str) (array.get $lr (struct.get $Lr 0 (local.get $keys)) (local.get $i))) (local.get $key))
          (then (return (ref.cast (ref null $J) (array.get $lr (struct.get $Lr 0 (struct.get $J 4 (local.get $o))) (local.get $i))))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (ref.null $J))

  ;; 鍵が data 区画の定数のとき。
  (func $j_getk (param $o (ref null $J)) (param $off i32) (param $len i32) (result (ref null $J))
    (call $j_get (local.get $o) (call $mem_str (local.get $off) (local.get $len))))

  (func $j_num (param $v (ref null $J)) (result f64)
    (if (result f64) (i32.eq (call $j_kind (local.get $v)) (i32.const 2))
      (then (struct.get $J 1 (local.get $v)))
      (else (f64.const 0))))

  ;; Lua の真偽（nil / false だけが偽）
  (func $j_truthy (param $v (ref null $J)) (result i32)
    (local $k i32)
    (local.set $k (call $j_kind (local.get $v)))
    (if (i32.eqz (local.get $k)) (then (return (i32.const 0))))
    (if (i32.eq (local.get $k) (i32.const 1)) (then (return (f64.ne (struct.get $J 1 (local.get $v)) (f64.const 0)))))
    (i32.const 1))

  (func $j_is_true (param $v (ref null $J)) (result i32)
    (if (i32.ne (call $j_kind (local.get $v)) (i32.const 1)) (then (return (i32.const 0))))
    (f64.eq (struct.get $J 1 (local.get $v)) (f64.const 1)))

  (func $j_str (param $v (ref null $J)) (result (ref null $str))
    (if (result (ref null $str)) (i32.eq (call $j_kind (local.get $v)) (i32.const 3))
      (then (struct.get $J 2 (local.get $v)))
      (else (ref.null $str))))

  (func $j_len (param $v (ref null $J)) (result i32)
    (if (result i32) (i32.eq (call $j_kind (local.get $v)) (i32.const 4))
      (then (struct.get $Lr 1 (struct.get $J 4 (local.get $v))))
      (else (i32.const 0))))

  (func $j_at (param $v (ref null $J)) (param $k i32) (result (ref null $J))
    (ref.cast (ref null $J) (array.get $lr (struct.get $Lr 0 (struct.get $J 4 (local.get $v))) (local.get $k))))

  ;; ---------------------------------------------------------------- list（jil.md §6.3。要素の表現ごとに 3 種）
  (func $index_of (param $n i32) (param $i f64) (result i32)
    (local $f f64) (local $k i64) (local $old (ref null $buf))
    (local.set $f (f64.floor (local.get $i)))
    (if (i32.and (f64.eq (local.get $f) (local.get $f)) (f64.lt (f64.abs (local.get $f)) (f64.const 9223372036854775808)))
      (then
        (local.set $k (i64.trunc_sat_f64_s (local.get $f)))
        (if (i32.and (i64.ge_s (local.get $k) (i64.const 0)) (i64.lt_s (local.get $k) (i64.extend_i32_u (local.get $n))))
          (then (return (i32.wrap_i64 (local.get $k)))))))
    ;; "添字 " .. NUMSTR(i) .. " は範囲外です（長さ " .. #list .. "）"
    (local.set $old (call $fmt_begin))
    (call $puts @K:msg_index1@)
    (call $put_num (local.get $i))
    (call $puts @K:msg_index2@)
    (call $put_digits (i64.extend_i32_u (local.get $n)))
    (call $puts @K:msg_close@)
    (call $ERR (call $fmt_end (local.get $old)))
    (i32.const -1))

@LISTS@

  ;; list<str> の contains は中身で比べる（Lua の文字列の == と同じ）。
  (func $f_contains_s (param $l (ref null $Lr)) (param $v (ref null $str)) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (struct.get $Lr 1 (local.get $l)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (call $str_eq (ref.cast (ref null $str) (array.get $lr (struct.get $Lr 0 (local.get $l)) (local.get $i))) (local.get $v))
          (then (return (i32.const 1))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  ;; ---------------------------------------------------------------- 純関数（expr.md §4.1）
  (func $f_abs (param $x f64) (result f64) (f64.abs (local.get $x)))
  ;; math.min / math.max は `<` の写し（f64.min / f64.max とは NaN と -0.0 の扱いが違う）
  (func $f_min (param $a f64) (param $b f64) (result f64)
    (select (local.get $b) (local.get $a) (f64.lt (local.get $b) (local.get $a))))
  (func $f_max (param $a f64) (param $b f64) (result f64)
    (select (local.get $b) (local.get $a) (f64.lt (local.get $a) (local.get $b))))
  ;; math.floor(x) + 0.0（-0.0 は 0.0 に潰れる）
  (func $f_floor (param $x f64) (result f64) (f64.add (f64.floor (local.get $x)) (f64.const 0)))
  (func $f_ceil (param $x f64) (result f64) (f64.add (f64.ceil (local.get $x)) (f64.const 0)))
  (func $f_round (param $x f64) (result f64)
    (local $f f64) (local $d f64)
    (local.set $f (call $f_floor (local.get $x)))
    (local.set $d (f64.sub (local.get $x) (local.get $f)))
    (if (f64.lt (local.get $d) (f64.const 0.5)) (then (return (local.get $f))))
    (if (f64.gt (local.get $d) (f64.const 0.5)) (then (return (f64.add (local.get $f) (f64.const 1)))))
    (if (f64.eq (call $lmod (local.get $f) (f64.const 2)) (f64.const 0)) (then (return (local.get $f))))
    (f64.add (local.get $f) (f64.const 1)))
  (func $f_sqrt (param $x f64) (result f64) (f64.sqrt (local.get $x)))
  (func $f_clamp (param $x f64) (param $lo f64) (param $hi f64) (result f64)
    (call $f_min (call $f_max (local.get $x) (local.get $lo)) (local.get $hi)))

  (func $f_len (param $s (ref null $str)) (result f64)
    (f64.convert_i32_u (call $cp_count (local.get $s))))

  ;; sub(s, i, n): i 文字目から n 文字（コードポイント）。プレリュードの F.sub と同じ切り詰め。
  (func $f_sub (param $s (ref null $str)) (param $i f64) (param $n f64) (result (ref $str))
    (local $total f64) (local $first i32) (local $last i32)
    (local.set $total (f64.convert_i32_u (call $cp_count (local.get $s))))
    (local.set $i (f64.floor (local.get $i)))
    (local.set $n (f64.floor (local.get $n)))
    (if (i32.or (f64.ne (local.get $i) (local.get $i)) (f64.ne (local.get $n) (local.get $n)))
      (then (return (call $str_empty))))
    (if (f64.lt (local.get $i) (f64.const 0))
      (then (local.set $n (f64.add (local.get $n) (local.get $i))) (local.set $i (f64.const 0))))
    (if (i32.or (f64.ge (local.get $i) (local.get $total)) (f64.le (local.get $n) (f64.const 0)))
      (then (return (call $str_empty))))
    (if (f64.gt (f64.add (local.get $i) (local.get $n)) (local.get $total))
      (then (local.set $n (f64.sub (local.get $total) (local.get $i)))))
    (local.set $first (call $cp_offset (local.get $s) (i32.trunc_sat_f64_s (local.get $i))))
    (local.set $last (call $cp_offset (local.get $s) (i32.trunc_sat_f64_s (f64.add (local.get $i) (local.get $n)))))
    (call $str_slice (local.get $s) (local.get $first) (local.get $last)))

  ;; cmp(a, b): バイト順で -1 / 0 / 1
  (func $f_cmp (param $a (ref null $str)) (param $b (ref null $str)) (result f64)
    (local $i i32) (local $na i32) (local $nb i32) (local $x i32) (local $y i32)
    (local.set $na (array.len (local.get $a)))
    (local.set $nb (array.len (local.get $b)))
    (block $done
      (loop $next
        (br_if $done (i32.or (i32.ge_u (local.get $i) (local.get $na)) (i32.ge_u (local.get $i) (local.get $nb))))
        (local.set $x (array.get_u $str (local.get $a) (local.get $i)))
        (local.set $y (array.get_u $str (local.get $b) (local.get $i)))
        (if (i32.ne (local.get $x) (local.get $y))
          (then (return (select (f64.const -1) (f64.const 1) (i32.lt_u (local.get $x) (local.get $y))))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (if (i32.eq (local.get $na) (local.get $nb)) (then (return (f64.const 0))))
    (select (f64.const -1) (f64.const 1) (i32.lt_u (local.get $na) (local.get $nb))))

  ;; ---------------------------------------------------------------- 乱数（abilities.md §6・PCG32・状態は i64）
  (func $rng_step (result i32)
    (local $old i64) (local $xorshifted i32) (local $rot i32)
    (local.set $old (global.get $RS))
    (global.set $RS (i64.add (i64.mul (local.get $old) (i64.const 6364136223846793005)) (global.get $RI)))
    (local.set $xorshifted (i32.wrap_i64 (i64.shr_u (i64.xor (i64.shr_u (local.get $old) (i64.const 18)) (local.get $old)) (i64.const 27))))
    (local.set $rot (i32.wrap_i64 (i64.shr_u (local.get $old) (i64.const 59))))
    (i32.rotr (local.get $xorshifted) (local.get $rot)))

  (func $rng_seed (param $seed i64)
    (global.set $RS (i64.const 0))
    (global.set $RI (i64.or (i64.shl (local.get $seed) (i64.const 1)) (i64.const 1)))
    (drop (call $rng_step))
    (global.set $RS (i64.add (global.get $RS) (local.get $seed)))
    (drop (call $rng_step)))

  (func $h_random_next (result f64)
    (f64.div (f64.convert_i32_u (call $rng_step)) (f64.const 4294967296)))

  (func $h_random_range (param $lo f64) (param $hi f64) (result f64)
    (local $n f64)
    (local.set $lo (call $f_floor (local.get $lo)))
    (local.set $hi (call $f_floor (local.get $hi)))
    (if (f64.lt (local.get $hi) (local.get $lo)) (then (return (local.get $lo))))
    (local.set $n (f64.add (f64.sub (local.get $hi) (local.get $lo)) (f64.const 1)))
    (f64.add (local.get $lo) (call $lmod (f64.convert_i32_u (call $rng_step)) (local.get $n))))

  ;; ---------------------------------------------------------------- 入力（abilities.md §3）
  (func $prepare_inputs (param $inputs (ref null $J))
    (local $ev (ref null $J)) (local $p (ref null $J)) (local $k i32) (local $n i32) (local $down i32)
    (local.set $ev (call $j_getk (local.get $inputs) @K:k_events@))
    (if (i32.eq (call $j_kind (local.get $ev)) (i32.const 4))
      (then (global.set $EVENTS (struct.get $J 4 (local.get $ev))))
      (else (global.set $EVENTS (ref.null $Lr))))
    (global.set $KEYS (call $j_getk (local.get $inputs) @K:k_keys@))
    (local.set $p (call $j_getk (local.get $inputs) @K:k_pointer@))
    (global.set $PX (f64.add (call $j_num (call $j_getk (local.get $p) @K:k_x@)) (f64.const 0)))
    (global.set $PY (f64.add (call $j_num (call $j_getk (local.get $p) @K:k_y@)) (f64.const 0)))
    (global.set $PDOWN (call $j_truthy (call $j_getk (local.get $p) @K:k_down@)))
    (struct.set $Lf 1 (global.get $RELX) (i32.const 0))
    (struct.set $Lf 1 (global.get $RELY) (i32.const 0))
    (local.set $n (call $ev_count))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $ev (call $ev_at (local.get $k)))
        (if (i32.eq (call $ev_kind (local.get $k)) (i32.const 2))
          (then
            (local.set $down (call $j_truthy (call $j_getk (local.get $ev) @K:k_down@)))
            (if (i32.and (global.get $LAST_DOWN) (i32.eqz (local.get $down)))
              (then
                (call $lf_push (global.get $RELX) (f64.add (call $j_num (call $j_getk (local.get $ev) @K:k_x@)) (f64.const 0)))
                (call $lf_push (global.get $RELY) (f64.add (call $j_num (call $j_getk (local.get $ev) @K:k_y@)) (f64.const 0)))))
            (global.set $LAST_DOWN (local.get $down))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next))))

  (func $ev_count (result i32)
    (if (result i32) (ref.is_null (global.get $EVENTS)) (then (i32.const 0)) (else (struct.get $Lr 1 (global.get $EVENTS)))))

  (func $ev_at (param $k i32) (result (ref null $J))
    (ref.cast (ref null $J) (array.get $lr (struct.get $Lr 0 (global.get $EVENTS)) (local.get $k))))

  ;; 1 key / 2 pointer / 3 text / 4 reply / 0 その他
  (func $ev_kind (param $k i32) (result i32)
    (local $s (ref null $str))
    (local.set $s (call $j_str (call $j_getk (call $ev_at (local.get $k)) @K:k_kind@)))
    (if (call $str_eq_mem (local.get $s) @K:k_key@) (then (return (i32.const 1))))
    (if (call $str_eq_mem (local.get $s) @K:k_pointer@) (then (return (i32.const 2))))
    (if (call $str_eq_mem (local.get $s) @K:k_text@) (then (return (i32.const 3))))
    (if (call $str_eq_mem (local.get $s) @K:k_reply@) (then (return (i32.const 4))))
    (i32.const 0))

  (func $ev_name (param $k i32) (result (ref $str))
    (local $s (ref null $str))
    (local.set $s (call $j_str (call $j_getk (call $ev_at (local.get $k)) @K:k_name@)))
    (if (result (ref $str)) (ref.is_null (local.get $s))
      (then (call $str_empty))
      (else (ref.as_non_null (local.get $s)))))

  (func $ev_down (param $k i32) (result i32)
    (call $j_truthy (call $j_getk (call $ev_at (local.get $k)) @K:k_down@)))

  (func $ev_pointer (param $k i32) (result (ref $F0))
    (local $ev (ref null $J))
    (local.set $ev (call $ev_at (local.get $k)))
    (struct.new $F0
      (f64.add (call $j_num (call $j_getk (local.get $ev) @K:k_x@)) (f64.const 0))
      (f64.add (call $j_num (call $j_getk (local.get $ev) @K:k_y@)) (f64.const 0))
      (call $j_truthy (call $j_getk (local.get $ev) @K:k_down@))))

  (func $h_input_key (param $name (ref null $str)) (result i32)
    (call $j_is_true (call $j_get (global.get $KEYS) (local.get $name))))

  (func $h_input_pressed (param $name (ref null $str)) (result i32)
    (local $k i32) (local $n i32) (local $ev (ref null $J))
    (local.set $n (call $ev_count))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (if (i32.eq (call $ev_kind (local.get $k)) (i32.const 1))
          (then
            (local.set $ev (call $ev_at (local.get $k)))
            (if (i32.and
                  (call $str_eq (call $ev_name (local.get $k)) (local.get $name))
                  (call $j_truthy (call $j_getk (local.get $ev) @K:k_down@)))
              (then (return (i32.const 1))))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $h_input_pointer (result (ref $F0))
    (struct.new $F0 (global.get $PX) (global.get $PY) (global.get $PDOWN)))

  ;; この tick に確定した文字列（text イベントを発生順につなぐ。無ければ ""）
  (func $h_input_text (result (ref $str))
    (local $old (ref null $buf)) (local $k i32) (local $n i32) (local $s (ref null $str))
    (local.set $old (call $fmt_begin))
    (local.set $n (call $ev_count))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (if (i32.eq (call $ev_kind (local.get $k)) (i32.const 3))
          (then
            (local.set $s (call $j_str (call $j_getk (call $ev_at (local.get $k)) @K:k_text@)))
            (if (i32.eqz (ref.is_null (local.get $s))) (then (call $put_str (local.get $s))))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (call $fmt_end (local.get $old)))

  ;; ---------------------------------------------------------------- 表示リストと音（abilities.md §2 / §4 / §5）
  ;; 効果はエラーの後は何もしない（Lua では error で手順ごと抜けるので積まれない）。
  (func $ops_open (result (ref $buf))
    (local $old (ref null $buf))
    (local.set $old (global.get $OUT))
    (global.set $OUT (global.get $OPS))
    (if (global.get $OPS_N) (then (call $putc (i32.const 44))))
    (global.set $OPS_N (i32.add (global.get $OPS_N) (i32.const 1)))
    (ref.as_non_null (local.get $old)))

  (func $audio_open (result (ref $buf))
    (local $old (ref null $buf))
    (local.set $old (global.get $OUT))
    (global.set $OUT (global.get $AUDIO))
    (if (global.get $AUDIO_N) (then (call $putc (i32.const 44))))
    (global.set $AUDIO_N (i32.add (global.get $AUDIO_N) (i32.const 1)))
    (ref.as_non_null (local.get $old)))

  (func $out_close (param $old (ref null $buf))
    (call $putc (i32.const 93))
    (global.set $OUT (ref.as_non_null (local.get $old))))

  ;; 色は "#rgb" か "#rrggbb"（%x = 0-9 a-f A-F）。違えば ERR（code "color"）して 0。
  (func $check_color (param $color (ref null $str)) (result i32)
    (local $n i32) (local $i i32) (local $c i32) (local $old (ref null $buf))
    (local.set $n (array.len (local.get $color)))
    (block $bad
      (br_if $bad (i32.eqz (i32.or (i32.eq (local.get $n) (i32.const 4)) (i32.eq (local.get $n) (i32.const 7)))))
      (br_if $bad (i32.ne (array.get_u $str (local.get $color) (i32.const 0)) (i32.const 35)))
      (local.set $i (i32.const 1))
      (block $done
        (loop $next
          (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
          (local.set $c (array.get_u $str (local.get $color) (local.get $i)))
          (br_if $bad (i32.eqz (i32.or
            (i32.le_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9))
            (i32.le_u (i32.sub (i32.or (local.get $c) (i32.const 32)) (i32.const 97)) (i32.const 5)))))
          (local.set $i (i32.add (local.get $i) (i32.const 1)))
          (br $next)))
      (return (i32.const 1)))
    (local.set $old (call $fmt_begin))
    (call $puts @K:msg_color@)
    (call $put_str (local.get $color))
    (call $puts @K:msg_close@)
    (call $ERR (call $fmt_end (local.get $old)))
    (i32.const 0))

  (func $h_canvas_clear (param $color (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (if (i32.eqz (call $check_color (local.get $color))) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_clear@)
    (call $put_js (local.get $color))
    (call $out_close (local.get $old)))

  (func $h_canvas_ink (param $color (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (if (i32.eqz (call $check_color (local.get $color))) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_ink@)
    (call $put_js (local.get $color))
    (call $out_close (local.get $old)))

  (func $h_canvas_rect (param $x f64) (param $y f64) (param $w f64) (param $h f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_rect@)
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y)) (call $putc (i32.const 44))
    (call $put_jn (local.get $w)) (call $putc (i32.const 44))
    (call $put_jn (local.get $h))
    (call $out_close (local.get $old)))

  (func $h_canvas_circle (param $x f64) (param $y f64) (param $r f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_circle@)
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y)) (call $putc (i32.const 44))
    (call $put_jn (local.get $r))
    (call $out_close (local.get $old)))

  (func $h_canvas_line (param $x1 f64) (param $y1 f64) (param $x2 f64) (param $y2 f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_line@)
    (call $put_jn (local.get $x1)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y1)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x2)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y2))
    (call $out_close (local.get $old)))

  (func $h_canvas_text (param $s (ref null $str)) (param $x f64) (param $y f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_text@)
    (call $put_js (local.get $s)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y))
    (call $out_close (local.get $old)))

  (func $h_canvas_sprite (param $name (ref null $str)) (param $x f64) (param $y f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_sprite@)
    (call $put_js (local.get $name)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y))
    (call $out_close (local.get $old)))

  ;; ui.button: op を積み、この tick に矩形の中（境界を含む）で主ボタンが離されていれば真
  (func $h_ui_button (param $label (ref null $str)) (param $x f64) (param $y f64) (param $w f64) (param $h f64) (result i32)
    (local $old (ref null $buf)) (local $k i32) (local $n i32) (local $rx f64) (local $ry f64)
    (if (global.get $ERRED) (then (return (i32.const 0))))
    (local.set $old (call $ops_open))
    (call $puts @K:op_button@)
    (call $put_js (local.get $label)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y)) (call $putc (i32.const 44))
    (call $put_jn (local.get $w)) (call $putc (i32.const 44))
    (call $put_jn (local.get $h))
    (call $out_close (local.get $old))
    (local.set $n (struct.get $Lf 1 (global.get $RELX)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $rx (array.get $lf (struct.get $Lf 0 (global.get $RELX)) (local.get $k)))
        (local.set $ry (array.get $lf (struct.get $Lf 0 (global.get $RELY)) (local.get $k)))
        (if (i32.and
              (i32.and (f64.ge (local.get $rx) (local.get $x)) (f64.le (local.get $rx) (f64.add (local.get $x) (local.get $w))))
              (i32.and (f64.ge (local.get $ry) (local.get $y)) (f64.le (local.get $ry) (f64.add (local.get $y) (local.get $h)))))
          (then (return (i32.const 1))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $h_ui_label (param $s (ref null $str)) (param $x f64) (param $y f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts @K:op_label@)
    (call $put_js (local.get $s)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y))
    (call $out_close (local.get $old)))

  (func $h_audio_tone (param $hz f64) (param $ms f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $audio_open))
    (call $puts @K:op_tone@)
    (call $put_jn (local.get $hz)) (call $putc (i32.const 44))
    (call $put_jn (local.get $ms))
    (call $out_close (local.get $old)))

  (func $h_audio_play (param $name (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $audio_open))
    (call $puts @K:op_play@)
    (call $put_js (local.get $name))
    (call $out_close (local.get $old)))

  ;; ---------------------------------------------------------------- storage（abilities.md §8）
  ;; get は自分の書き込み（新しい方が勝つ）→ boot の manifest.storage → ""。set は書き込みの一覧へ追記。
  (func $h_storage_get (param $key (ref null $str)) (result (ref $str))
    (local $i i32) (local $s (ref null $str))
    (local.set $i (struct.get $Lr 1 (global.get $STORE_K)))
    (block $done
      (loop $next
        (br_if $done (i32.eqz (local.get $i)))
        (local.set $i (i32.sub (local.get $i) (i32.const 1)))
        (if (call $str_eq (ref.cast (ref null $str) (array.get $lr (struct.get $Lr 0 (global.get $STORE_K)) (local.get $i))) (local.get $key))
          (then (return (ref.cast (ref $str) (array.get $lr (struct.get $Lr 0 (global.get $STORE_V)) (local.get $i))))))
        (br $next)))
    (local.set $s (call $j_str (call $j_get (global.get $STORAGE_BASE) (local.get $key))))
    (if (result (ref $str)) (ref.is_null (local.get $s))
      (then (call $str_empty))
      (else (ref.as_non_null (local.get $s)))))

  (func $h_storage_set (param $key (ref null $str)) (param $val (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (call $lr_push (global.get $STORE_K) (local.get $key))
    (call $lr_push (global.get $STORE_V) (local.get $val))
    (local.set $old (global.get $OUT))
    (global.set $OUT (global.get $STORE_OUT))
    (if (global.get $STORE_N) (then (call $putc (i32.const 44))))
    (global.set $STORE_N (i32.add (global.get $STORE_N) (i32.const 1)))
    (call $putc (i32.const 91))
    (call $put_js (local.get $key))
    (call $putc (i32.const 44))
    (call $put_js (local.get $val))
    (call $out_close (local.get $old)))

  ;; ---------------------------------------------------------------- 結果（runtime.md §1.2 のキーの順）
  ;; 公開 state の断片の前のコンマ（生成部の pub_i が先頭で呼ぶ）。
  (func $pub_comma
    (if (global.get $first)
      (then (global.set $first (i32.const 0)))
      (else (call $putc (i32.const 44)))))

  ;; {"ops":[…],"audio":[…][,"trace":[…]],"done":…,"error":…,"public":{…}[,"storage":[…]][,"asks":[…]][,"snapshot":{…}[,"resume":{…}]]}
  ;; キーの順は runtime.md §1.2（trace / snapshot / resume は DEBUG だけ、storage / asks はあった tick だけ）
  (func $result (result i32 i32)
    (global.set $OUT (call $buf_new (i32.add (i32.const 256)
      (i32.add (struct.get $buf 1 (global.get $OPS)) (struct.get $buf 1 (global.get $AUDIO))))))
    (call $puts @K:res_ops@)
    (call $put_buf (global.get $OPS))
    (call $puts @K:res_audio@)
    (call $put_buf (global.get $AUDIO))
    (call $putc (i32.const 93))
    (if (global.get $DEBUG)
      (then
        (call $puts @K:res_trace@)
        (call $put_trace)
        (call $putc (i32.const 93))))
    (call $puts @K:res_done@)
    (call $put_bool (global.get $DONE))
    (call $puts @K:res_error@)
    (if (ref.is_null (global.get $ERRMSG))
      (then (call $puts @K:null@))
      (else (call $put_js (global.get $ERRMSG))))
    (call $puts @K:res_public@)
    (global.set $first (i32.const 1))
    (call $pub_all)
    (call $putc (i32.const 125))
    (if (global.get $STORE_N)
      (then
        (call $puts @K:res_storage@)
        (call $put_buf (global.get $STORE_OUT))
        (call $putc (i32.const 93))))
    (if (global.get $ASKS_N)
      (then
        (call $puts @K:res_asks@)
        (call $put_buf (global.get $ASKS))
        (call $putc (i32.const 93))))
    (if (global.get $DEBUG)
      (then
        (call $puts @K:res_snapshot@)
        (call $snapshot)
        (if (global.get $RN_MODE)
          (then
            (call $puts @K:res_resume@)
            (call $put_resume_note)))))
    (call $putc (i32.const 125))
    (call $flush))

  ;; 公開 state の JSON 断片を陣の順に（確定済みの陣だけ）
  (func $pub_all
    (local $i i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (global.get $N)))
        (if (i32.and (call $prog_has_outs (local.get $i)) (call $cget (global.get $CPUB) (local.get $i)))
          (then (call $prog_pub (local.get $i))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next))))

  (func $clear_frame
    (call $buf_clear (global.get $OPS))
    (call $buf_clear (global.get $AUDIO))
    (global.set $OPS_N (i32.const 0))
    (global.set $AUDIO_N (i32.const 0)))

  ;; ---------------------------------------------------------------- ホスト境界（runtime.md §1 の wasm 版）
  ;; tick 結果を返した後に空にするもの（TRACE / STORE_OUT / ASKS / RESUME_NOTE）
  (func $after_result
    (call $lr_reset (global.get $TRACE))
    (call $buf_clear (global.get $STORE_OUT))
    (global.set $STORE_N (i32.const 0))
    (call $buf_clear (global.get $ASKS))
    (global.set $ASKS_N (i32.const 0))
    (global.set $RN_MODE (i32.const 0)))

  (func (export "boot") (param $n i32)
    (local $root (ref null $J)) (local $manifest (ref null $J)) (local $resume (ref null $J)) (local $resumed i32) (local $seed (ref null $J))
    (global.set $BUDGET (i32.const 10000000))
    (local.set $root (call $parse_input (local.get $n)))
    (local.set $manifest (call $j_getk (local.get $root) @K:k_manifest@))
    (global.set $STORAGE_BASE (call $j_getk (local.get $manifest) @K:k_storage@))
    ;; 状態を保った差し替え: manifest.resume が table（object / array）なら名前で照合して写す（runtime.md §1.3）
    (local.set $resume (call $j_getk (local.get $manifest) @K:k_resume@))
    (if (i32.eqz (call $rd_rec (local.get $resume))) (then (local.set $resume (ref.null $J))))
    (struct.set $Lr 1 (global.get $STORE_K) (i32.const 0))
    (struct.set $Lr 1 (global.get $STORE_V) (i32.const 0))
    (call $buf_clear (global.get $STORE_OUT))
    (global.set $STORE_N (i32.const 0))
    (call $buf_clear (global.get $ASKS))
    (global.set $ASKS_N (i32.const 0))
    (global.set $ASKED (i32.const 0))
    (call $lr_reset (global.get $ASKMAP))
    (global.set $SEQ (i32.const 0))
    (global.set $TICK (i64.const -1))
    (global.set $DONE (i32.const 0))
    (global.set $ERRED (i32.const 0))
    (global.set $ERRMSG (ref.null $str))
    (call $lr_reset (global.get $Q))
    (call $lr_reset (global.get $TRACE))
    (global.set $LAST_DOWN (i32.const 0))
    (global.set $CUR_CI (i32.const -1))
    (global.set $CUR_PTR (ref.null $str))
    (global.set $RN_MODE (i32.const 0))
    (global.set $EVENTS (ref.null $Lr))
    (global.set $KEYS (ref.null $J))
    (global.set $PX (f64.const 0))
    (global.set $PY (f64.const 0))
    (global.set $PDOWN (i32.const 0))
    (call $clear_frame)
    (call $fresh_state)
    ;; 乱数列は seed と状態の組で決まる。snapshot の seed（整数値）を優先する
    (local.set $seed (call $j_getk (local.get $root) @K:k_seed@))
    (if (i32.eqz (ref.is_null (local.get $resume)))
      (then
        (if (i32.and (i32.eq (call $j_kind (call $j_getk (local.get $resume) @K:k_seed@)) (i32.const 2))
                     (f64.eq (call $j_num (call $j_getk (local.get $resume) @K:k_seed@)) (f64.floor (call $j_num (call $j_getk (local.get $resume) @K:k_seed@)))))
          (then (local.set $seed (call $j_getk (local.get $resume) @K:k_seed@))))))
    (global.set $SEED (i64.trunc_sat_f64_s (call $j_num (local.get $seed))))
    (call $rng_seed (global.get $SEED))
    ;; protected(restore / ENTER(ROOT); ADVANCE()) → エラーなら以降を飛ばして error 行
    (if (i32.eqz (ref.is_null (local.get $resume))) (then (local.set $resumed (call $restore_from (local.get $resume)))))
    (if (i32.eqz (global.get $ERRED))
      (then
        (if (local.get $resumed)
          (then (call $repair_flows))
          (else (call $enter (global.get $ROOT))))))
    (if (i32.eqz (global.get $ERRED)) (then (call $advance)))
    (call $error_row)
    ;; 通常の boot は全陣を確定する。復元では確定値 P を snapshot から写したので触らない
    (if (i32.eqz (local.get $resumed)) (then (call $publish_all)))
    ;; boot の表示リストは捨てる（Lua と同じ）。storage の書き込みと問いは最初の tick の結果に載せる
    (call $clear_frame))

  (func (export "tick") (param $n i32) (result i32 i32)
    (local $root (ref null $J)) (local $ptr i32) (local $len i32) (local $old (ref null $buf))
    (global.set $BUDGET (i32.const 10000000))
    (local.set $root (call $parse_input (local.get $n)))
    (call $clear_frame)
    (if (i32.eqz (global.get $DONE))
      (then
        (global.set $TICK (i64.trunc_sat_f64_s (call $j_num (call $j_getk (local.get $root) @K:k_t@))))
        (call $prepare_inputs (call $j_getk (local.get $root) @K:k_inputs@))
        (call $step)
        (call $error_row)
        (if (global.get $DEBUG)
          (then
            (local.set $old (call $fmt_begin))
            (call $puts @K:fr_ops@)
            (call $put_buf (global.get $OPS))
            (call $puts @K:fr_audio@)
            (call $put_buf (global.get $AUDIO))
            (call $puts @K:fr_end@)
            (drop (call $row (i32.const 12) (i32.const -1) (ref.null $str) (call $mem_str @K:p_stage@) (ref.null $str)
              (call $fmt_end (local.get $old))))))))
    (call $result)
    (local.set $len)
    (local.set $ptr)
    (call $after_result)
    (local.get $ptr)
    (local.get $len))

