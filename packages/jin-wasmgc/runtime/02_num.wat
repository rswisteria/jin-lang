
  ;; ---------------------------------------------------------------- 多倍長（10^9 進・符号なし）
  ;; 数値の書式（最短往復表現）と strtod（10 進 → double の正確な丸め）にだけ使う。
  ;; 配列の [0] が桁数 n、[1..n] が下位からの桁（各 0 ≤ 桁 < 10^9）。n = 0 は 0。
  ;; 容量 200 桁 = 10 進 1800 桁（最大は strtod の 800 桁 × 2^1075 ≈ 1125 桁）。
  (func $bn_new (result (ref $bn)) (array.new_default $bn (i32.const 201)))

  (func $bn_set_u64 (param $b (ref null $bn)) (param $v i64)
    (local $n i32)
    (block $done
      (loop $next
        (br_if $done (i64.eqz (local.get $v)))
        (local.set $n (i32.add (local.get $n) (i32.const 1)))
        (array.set $bn (local.get $b) (local.get $n) (i32.wrap_i64 (i64.rem_u (local.get $v) (i64.const 1000000000))))
        (local.set $v (i64.div_u (local.get $v) (i64.const 1000000000)))
        (br $next)))
    (array.set $bn (local.get $b) (i32.const 0) (local.get $n)))

  (func $bn_copy (param $dst (ref null $bn)) (param $src (ref null $bn))
    (array.copy $bn $bn (local.get $dst) (i32.const 0) (local.get $src) (i32.const 0)
      (i32.add (array.get $bn (local.get $src) (i32.const 0)) (i32.const 1))))

  ;; b *= k（0 < k < 2^32）。
  (func $bn_mul_small (param $b (ref null $bn)) (param $k i64)
    (local $i i32) (local $n i32) (local $t i64) (local $carry i64)
    (local.set $n (array.get $bn (local.get $b) (i32.const 0)))
    (local.set $i (i32.const 1))
    (block $done
      (loop $next
        (br_if $done (i32.gt_u (local.get $i) (local.get $n)))
        (local.set $t
          (i64.add
            (i64.mul (i64.extend_i32_u (array.get $bn (local.get $b) (local.get $i))) (local.get $k))
            (local.get $carry)))
        (array.set $bn (local.get $b) (local.get $i) (i32.wrap_i64 (i64.rem_u (local.get $t) (i64.const 1000000000))))
        (local.set $carry (i64.div_u (local.get $t) (i64.const 1000000000)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (block $done2
      (loop $more
        (br_if $done2 (i64.eqz (local.get $carry)))
        (local.set $n (i32.add (local.get $n) (i32.const 1)))
        (array.set $bn (local.get $b) (local.get $n) (i32.wrap_i64 (i64.rem_u (local.get $carry) (i64.const 1000000000))))
        (local.set $carry (i64.div_u (local.get $carry) (i64.const 1000000000)))
        (br $more)))
    (array.set $bn (local.get $b) (i32.const 0) (local.get $n)))

  (func $bn_mul_pow2 (param $b (ref null $bn)) (param $e i32)
    (block $done
      (loop $next
        (br_if $done (i32.lt_s (local.get $e) (i32.const 29)))
        (call $bn_mul_small (local.get $b) (i64.const 536870912))
        (local.set $e (i32.sub (local.get $e) (i32.const 29)))
        (br $next)))
    (if (i32.gt_s (local.get $e) (i32.const 0))
      (then (call $bn_mul_small (local.get $b) (i64.shl (i64.const 1) (i64.extend_i32_u (local.get $e)))))))

  (func $bn_mul_pow5 (param $b (ref null $bn)) (param $e i32)
    (local $k i64)
    (block $done
      (loop $next
        (br_if $done (i32.lt_s (local.get $e) (i32.const 13)))
        (call $bn_mul_small (local.get $b) (i64.const 1220703125))
        (local.set $e (i32.sub (local.get $e) (i32.const 13)))
        (br $next)))
    (local.set $k (i64.const 1))
    (block $done2
      (loop $next2
        (br_if $done2 (i32.le_s (local.get $e) (i32.const 0)))
        (local.set $k (i64.mul (local.get $k) (i64.const 5)))
        (local.set $e (i32.sub (local.get $e) (i32.const 1)))
        (br $next2)))
    (if (i64.gt_u (local.get $k) (i64.const 1)) (then (call $bn_mul_small (local.get $b) (local.get $k)))))

  (func $bn_mul_pow10 (param $b (ref null $bn)) (param $e i32)
    (local $q i32) (local $i i32) (local $n i32) (local $k i64)
    (local.set $n (array.get $bn (local.get $b) (i32.const 0)))
    (local.set $q (i32.div_u (local.get $e) (i32.const 9)))
    (if (i32.and (i32.gt_u (local.get $q) (i32.const 0)) (i32.gt_u (local.get $n) (i32.const 0)))
      (then
        ;; 桁を q だけ上へずらし、下を 0 で埋める
        (local.set $i (local.get $n))
        (block $done
          (loop $next
            (br_if $done (i32.eqz (local.get $i)))
            (array.set $bn (local.get $b) (i32.add (local.get $i) (local.get $q)) (array.get $bn (local.get $b) (local.get $i)))
            (local.set $i (i32.sub (local.get $i) (i32.const 1)))
            (br $next)))
        (local.set $i (i32.const 1))
        (block $done2
          (loop $next2
            (br_if $done2 (i32.gt_u (local.get $i) (local.get $q)))
            (array.set $bn (local.get $b) (local.get $i) (i32.const 0))
            (local.set $i (i32.add (local.get $i) (i32.const 1)))
            (br $next2)))
        (array.set $bn (local.get $b) (i32.const 0) (i32.add (local.get $n) (local.get $q)))))
    (local.set $e (i32.rem_u (local.get $e) (i32.const 9)))
    (local.set $k (i64.const 1))
    (block $done3
      (loop $next3
        (br_if $done3 (i32.eqz (local.get $e)))
        (local.set $k (i64.mul (local.get $k) (i64.const 10)))
        (local.set $e (i32.sub (local.get $e) (i32.const 1)))
        (br $next3)))
    (if (i64.gt_u (local.get $k) (i64.const 1)) (then (call $bn_mul_small (local.get $b) (local.get $k)))))

  ;; a += b
  (func $bn_add (param $a (ref null $bn)) (param $b (ref null $bn))
    (local $i i32) (local $n i32) (local $na i32) (local $nb i32) (local $s i32) (local $carry i32)
    (local.set $na (array.get $bn (local.get $a) (i32.const 0)))
    (local.set $nb (array.get $bn (local.get $b) (i32.const 0)))
    (local.set $n (select (local.get $na) (local.get $nb) (i32.gt_u (local.get $na) (local.get $nb))))
    (local.set $i (i32.const 1))
    (block $done
      (loop $next
        (br_if $done (i32.gt_u (local.get $i) (local.get $n)))
        (local.set $s (local.get $carry))
        (if (i32.le_u (local.get $i) (local.get $na))
          (then (local.set $s (i32.add (local.get $s) (array.get $bn (local.get $a) (local.get $i))))))
        (if (i32.le_u (local.get $i) (local.get $nb))
          (then (local.set $s (i32.add (local.get $s) (array.get $bn (local.get $b) (local.get $i))))))
        (local.set $carry (i32.ge_u (local.get $s) (i32.const 1000000000)))
        (if (local.get $carry) (then (local.set $s (i32.sub (local.get $s) (i32.const 1000000000)))))
        (array.set $bn (local.get $a) (local.get $i) (local.get $s))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (if (local.get $carry)
      (then
        (local.set $n (i32.add (local.get $n) (i32.const 1)))
        (array.set $bn (local.get $a) (local.get $n) (i32.const 1))))
    (array.set $bn (local.get $a) (i32.const 0) (local.get $n)))

  ;; a -= b（a ≥ b が前提）
  (func $bn_sub (param $a (ref null $bn)) (param $b (ref null $bn))
    (local $i i32) (local $na i32) (local $nb i32) (local $s i32) (local $borrow i32)
    (local.set $na (array.get $bn (local.get $a) (i32.const 0)))
    (local.set $nb (array.get $bn (local.get $b) (i32.const 0)))
    (local.set $i (i32.const 1))
    (block $done
      (loop $next
        (br_if $done (i32.gt_u (local.get $i) (local.get $na)))
        (local.set $s (i32.sub (array.get $bn (local.get $a) (local.get $i)) (local.get $borrow)))
        (if (i32.le_u (local.get $i) (local.get $nb))
          (then (local.set $s (i32.sub (local.get $s) (array.get $bn (local.get $b) (local.get $i))))))
        (local.set $borrow (i32.lt_s (local.get $s) (i32.const 0)))
        (if (local.get $borrow) (then (local.set $s (i32.add (local.get $s) (i32.const 1000000000)))))
        (array.set $bn (local.get $a) (local.get $i) (local.get $s))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (block $trim
      (loop $again
        (br_if $trim (i32.eqz (local.get $na)))
        (br_if $trim (i32.ne (array.get $bn (local.get $a) (local.get $na)) (i32.const 0)))
        (local.set $na (i32.sub (local.get $na) (i32.const 1)))
        (br $again)))
    (array.set $bn (local.get $a) (i32.const 0) (local.get $na)))

  (func $bn_cmp (param $a (ref null $bn)) (param $b (ref null $bn)) (result i32)
    (local $i i32) (local $x i32) (local $y i32)
    (local.set $x (array.get $bn (local.get $a) (i32.const 0)))
    (local.set $y (array.get $bn (local.get $b) (i32.const 0)))
    (if (i32.ne (local.get $x) (local.get $y))
      (then (return (select (i32.const 1) (i32.const -1) (i32.gt_u (local.get $x) (local.get $y))))))
    (local.set $i (local.get $x))
    (block $done
      (loop $next
        (br_if $done (i32.eqz (local.get $i)))
        (local.set $x (array.get $bn (local.get $a) (local.get $i)))
        (local.set $y (array.get $bn (local.get $b) (local.get $i)))
        (if (i32.ne (local.get $x) (local.get $y))
          (then (return (select (i32.const 1) (i32.const -1) (i32.gt_u (local.get $x) (local.get $y))))))
        (local.set $i (i32.sub (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  ;; 10 進の桁列（先頭の 0 なし。0 は "0"）。
  (func $bn_digits (param $b (ref null $bn)) (result (ref $str))
    (local $old (ref null $buf)) (local $i i32)
    (local.set $old (call $fmt_begin))
    (local.set $i (array.get $bn (local.get $b) (i32.const 0)))
    (if (i32.eqz (local.get $i))
      (then (call $putc (i32.const 48)))
      (else
        (call $put_digits (i64.extend_i32_u (array.get $bn (local.get $b) (local.get $i))))
        (local.set $i (i32.sub (local.get $i) (i32.const 1)))
        (block $done
          (loop $next
            (br_if $done (i32.eqz (local.get $i)))
            (call $put_digits9 (array.get $bn (local.get $b) (local.get $i)))
            (local.set $i (i32.sub (local.get $i) (i32.const 1)))
            (br $next)))))
    (call $fmt_end (local.get $old)))

  ;; 10 進の桁列（ASCII）を読む。
  (func $bn_set_digits (param $b (ref null $bn)) (param $s (ref null $str))
    (local $len i32) (local $end i32) (local $start i32) (local $i i32) (local $v i32) (local $n i32)
    (local.set $len (array.len (local.get $s)))
    (local.set $end (local.get $len))
    (block $done
      (loop $next
        (br_if $done (i32.le_s (local.get $end) (i32.const 0)))
        (local.set $start (i32.sub (local.get $end) (i32.const 9)))
        (if (i32.lt_s (local.get $start) (i32.const 0)) (then (local.set $start (i32.const 0))))
        (local.set $v (i32.const 0))
        (local.set $i (local.get $start))
        (block $chunk
          (loop $digit
            (br_if $chunk (i32.ge_s (local.get $i) (local.get $end)))
            (local.set $v (i32.add (i32.mul (local.get $v) (i32.const 10))
              (i32.sub (array.get_u $str (local.get $s) (local.get $i)) (i32.const 48))))
            (local.set $i (i32.add (local.get $i) (i32.const 1)))
            (br $digit)))
        (local.set $n (i32.add (local.get $n) (i32.const 1)))
        (array.set $bn (local.get $b) (local.get $n) (local.get $v))
        (local.set $end (local.get $start))
        (br $next)))
    (block $trim
      (loop $again
        (br_if $trim (i32.eqz (local.get $n)))
        (br_if $trim (i32.ne (array.get $bn (local.get $b) (local.get $n)) (i32.const 0)))
        (local.set $n (i32.sub (local.get $n) (i32.const 1)))
        (br $again)))
    (array.set $bn (local.get $b) (i32.const 0) (local.get $n)))

  ;; ---------------------------------------------------------------- 数値の書式（runtime.md §6）
  ;; プレリュードの shortest_digits と同じ探索: p = 0..16 について x を p + 1 桁に最近接（偶数丸め）で丸めた
  ;; 候補が x に往復するかを見て、最初の p を採る。`%.{p}e` の代わりに x の正確な 10 進展開（多倍長）から
  ;; 候補を作り、往復は「隣の double との中点」と正確に比べる（2 の冪では下側の幅が半分・仮数が偶数なら端を含む）。
  ;; 探索は Lua の写しなので、非対称な区間で Python の repr と割れる稀な値（2 の冪の一部）も Lua に付く。

  ;; D の先頭 n 桁を最近接・偶数丸めで丸めた n 桁（桁上がりで 10^n になったら "100…0" にし $SD_CARRY = 1）。
  (func $round_digits (param $d (ref null $str)) (param $dlen i32) (param $n i32) (result (ref $str))
    (local $out (ref null $str)) (local $c i32) (local $up i32) (local $i i32)
    (local.set $out (array.new_default $str (local.get $n)))
    (array.copy $str $str (local.get $out) (i32.const 0) (local.get $d) (i32.const 0) (local.get $n))
    (global.set $SD_CARRY (i32.const 0))
    (local.set $c (array.get_u $str (local.get $d) (local.get $n)))
    (if (i32.gt_u (local.get $c) (i32.const 53))
      (then (local.set $up (i32.const 1)))
      (else
        (if (i32.eq (local.get $c) (i32.const 53))
          (then
            ;; 残りに 0 以外があれば上へ、なければ最後の桁が奇数なら上へ（偶数丸め）
            (local.set $i (i32.add (local.get $n) (i32.const 1)))
            (local.set $up (i32.and (i32.sub (array.get_u $str (local.get $d) (i32.sub (local.get $n) (i32.const 1))) (i32.const 48)) (i32.const 1)))
            (block $done
              (loop $next
                (br_if $done (i32.ge_u (local.get $i) (local.get $dlen)))
                (if (i32.ne (array.get_u $str (local.get $d) (local.get $i)) (i32.const 48))
                  (then (local.set $up (i32.const 1)) (br $done)))
                (local.set $i (i32.add (local.get $i) (i32.const 1)))
                (br $next)))))))
    (if (local.get $up)
      (then
        (local.set $i (i32.sub (local.get $n) (i32.const 1)))
        (block $done2
          (loop $carry
            (if (i32.lt_s (local.get $i) (i32.const 0))
              (then
                (array.set $str (local.get $out) (i32.const 0) (i32.const 49))
                (global.set $SD_CARRY (i32.const 1))
                (br $done2)))
            (if (i32.eq (array.get_u $str (local.get $out) (local.get $i)) (i32.const 57))
              (then
                (array.set $str (local.get $out) (local.get $i) (i32.const 48))
                (local.set $i (i32.sub (local.get $i) (i32.const 1)))
                (br $carry)))
            (array.set $str (local.get $out) (local.get $i)
              (i32.add (array.get_u $str (local.get $out) (local.get $i)) (i32.const 1)))))))
    (ref.as_non_null (local.get $out)))

  ;; 候補 d × 10^k（d は n 桁の整数）が x = m·2^e に往復するか。
  (func $roundtrips (param $cand (ref null $str)) (param $n i32) (param $k i32) (param $m i64) (param $e i32) (result i32)
    (local $d i64) (local $i i32) (local $X (ref null $bn)) (local $LO (ref null $bn)) (local $HI (ref null $bn))
    (local $C (ref null $bn)) (local $DEL (ref null $bn)) (local $t i32) (local $u i32) (local $clo i32) (local $chi i32)
    (local $half i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (local.set $d (i64.add (i64.mul (local.get $d) (i64.const 10))
          (i64.extend_i32_u (i32.sub (array.get_u $str (local.get $cand) (local.get $i)) (i32.const 48)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (local.set $X (call $bn_new))
    (local.set $LO (call $bn_new))
    (local.set $HI (call $bn_new))
    (local.set $C (call $bn_new))
    (local.set $DEL (call $bn_new))
    ;; 2 の冪（仮数の下位が 0）で下側の隣が半分の距離にあるか
    (local.set $half (i32.and (i64.eq (local.get $m) (i64.const 4503599627370496)) (i32.gt_s (local.get $e) (i32.const -1074))))
    (if (i32.ge_s (local.get $e) (i32.const 2))
      (then
        ;; X = m·2^e, HI = X + 2^(e-1), LO = X - 2^(e-1 | e-2), C = d·10^k（k ≥ 0）
        (call $bn_set_u64 (local.get $X) (local.get $m))
        (call $bn_mul_pow2 (local.get $X) (local.get $e))
        (call $bn_set_u64 (local.get $DEL) (i64.const 1))
        (call $bn_mul_pow2 (local.get $DEL) (i32.sub (local.get $e) (i32.const 1)))
        (call $bn_copy (local.get $HI) (local.get $X))
        (call $bn_add (local.get $HI) (local.get $DEL))
        (call $bn_set_u64 (local.get $DEL) (i64.const 1))
        (call $bn_mul_pow2 (local.get $DEL) (i32.sub (local.get $e) (i32.add (i32.const 1) (local.get $half))))
        (call $bn_copy (local.get $LO) (local.get $X))
        (call $bn_sub (local.get $LO) (local.get $DEL))
        (call $bn_set_u64 (local.get $C) (local.get $d))
        (if (i32.gt_s (local.get $k) (i32.const 0)) (then (call $bn_mul_pow10 (local.get $C) (local.get $k)))))
      (else
        ;; 全体を 2^(2-e)·10^max(-k,0) 倍: X = 4m·10^t, HI = X + 2·10^t, LO = X - (1|2)·10^t, C = d·2^(2-e)·10^u
        (local.set $t (select (i32.sub (i32.const 0) (local.get $k)) (i32.const 0) (i32.lt_s (local.get $k) (i32.const 0))))
        (local.set $u (select (local.get $k) (i32.const 0) (i32.gt_s (local.get $k) (i32.const 0))))
        (call $bn_set_u64 (local.get $X) (i64.mul (local.get $m) (i64.const 4)))
        (call $bn_mul_pow10 (local.get $X) (local.get $t))
        (call $bn_set_u64 (local.get $DEL) (i64.const 2))
        (call $bn_mul_pow10 (local.get $DEL) (local.get $t))
        (call $bn_copy (local.get $HI) (local.get $X))
        (call $bn_add (local.get $HI) (local.get $DEL))
        (call $bn_set_u64 (local.get $DEL) (select (i64.const 1) (i64.const 2) (local.get $half)))
        (call $bn_mul_pow10 (local.get $DEL) (local.get $t))
        (call $bn_copy (local.get $LO) (local.get $X))
        (call $bn_sub (local.get $LO) (local.get $DEL))
        (call $bn_set_u64 (local.get $C) (local.get $d))
        (call $bn_mul_pow2 (local.get $C) (i32.sub (i32.const 2) (local.get $e)))
        (call $bn_mul_pow10 (local.get $C) (local.get $u))))
    (local.set $clo (call $bn_cmp (local.get $C) (local.get $LO)))
    (local.set $chi (call $bn_cmp (local.get $C) (local.get $HI)))
    (if (i32.and (i32.gt_s (local.get $clo) (i32.const 0)) (i32.lt_s (local.get $chi) (i32.const 0)))
      (then (return (i32.const 1))))
    (if (i32.and
          (i32.or (i32.eqz (local.get $clo)) (i32.eqz (local.get $chi)))
          (i64.eqz (i64.and (local.get $m) (i64.const 1))))
      (then (return (i32.const 1))))
    (i32.const 0))

  ;; |x|（有限・0 でない）の最短の桁列（末尾の 0 なし）。10 進の指数は $SD_E に。
  (func $shortest (param $x f64) (result (ref $str))
    (local $bits i64) (local $m i64) (local $e i32) (local $N (ref null $bn)) (local $D (ref null $str))
    (local $E i32) (local $dlen i32) (local $n i32) (local $cand (ref null $str)) (local $Ec i32) (local $clen i32)
    (local.set $bits (i64.reinterpret_f64 (f64.abs (local.get $x))))
    (local.set $e (i32.wrap_i64 (i64.shr_u (local.get $bits) (i64.const 52))))
    (local.set $m (i64.and (local.get $bits) (i64.const 0xFFFFFFFFFFFFF)))
    (if (i32.eqz (local.get $e))
      (then (local.set $e (i32.const -1074)))
      (else
        (local.set $m (i64.or (local.get $m) (i64.const 4503599627370496)))
        (local.set $e (i32.sub (local.get $e) (i32.const 1075)))))
    (local.set $N (call $bn_new))
    (call $bn_set_u64 (local.get $N) (local.get $m))
    (if (i32.ge_s (local.get $e) (i32.const 0))
      (then (call $bn_mul_pow2 (local.get $N) (local.get $e)))
      (else (call $bn_mul_pow5 (local.get $N) (i32.sub (i32.const 0) (local.get $e)))))
    (local.set $D (call $bn_digits (local.get $N)))
    (local.set $dlen (array.len (local.get $D)))
    (local.set $E (i32.sub (local.get $dlen) (i32.const 1)))
    (if (i32.lt_s (local.get $e) (i32.const 0)) (then (local.set $E (i32.add (local.get $E) (local.get $e)))))
    (block $strip
      (loop $again
        (br_if $strip (i32.le_u (local.get $dlen) (i32.const 1)))
        (br_if $strip (i32.ne (array.get_u $str (local.get $D) (i32.sub (local.get $dlen) (i32.const 1))) (i32.const 48)))
        (local.set $dlen (i32.sub (local.get $dlen) (i32.const 1)))
        (br $again)))
    (local.set $n (i32.const 1))
    (block $found
      (loop $try
        (if (i32.ge_u (local.get $n) (local.get $dlen))
          (then
            (global.set $SD_E (local.get $E))
            (return (call $str_slice (local.get $D) (i32.const 0) (local.get $dlen)))))
        (local.set $cand (call $round_digits (local.get $D) (local.get $dlen) (local.get $n)))
        (local.set $Ec (i32.add (local.get $E) (global.get $SD_CARRY)))
        (if (call $roundtrips (local.get $cand) (local.get $n)
              (i32.add (i32.sub (local.get $Ec) (local.get $n)) (i32.const 1)) (local.get $m) (local.get $e))
          (then (br $found)))
        (local.set $n (i32.add (local.get $n) (i32.const 1)))
        (br_if $try (i32.le_u (local.get $n) (i32.const 17)))
        ;; ここには来ない（17 桁は必ず往復する）。保険として正確な桁列を返す
        (global.set $SD_E (local.get $E))
        (return (call $str_slice (local.get $D) (i32.const 0) (local.get $dlen)))))
    (global.set $SD_E (local.get $Ec))
    (local.set $clen (local.get $n))
    (block $strip2
      (loop $again2
        (br_if $strip2 (i32.le_u (local.get $clen) (i32.const 1)))
        (br_if $strip2 (i32.ne (array.get_u $str (local.get $cand) (i32.sub (local.get $clen) (i32.const 1))) (i32.const 48)))
        (local.set $clen (i32.sub (local.get $clen) (i32.const 1)))
        (br $again2)))
    (call $str_slice (local.get $cand) (i32.const 0) (local.get $clen)))

  ;; 数値の書式（runtime.md §6 = Python の repr(float) の配置。プレリュードの NUMSTR と同じ）。
  ;; 整数値（|x| < 2^53。-0.0 は "0"）は整数として、それ以外は最短の桁列を e ∈ [-4, 16) なら固定小数、
  ;; それ以外は指数形（指数は符号付き 2 桁以上）で書く。
  (func $put_num (param $x f64)
    (local $i i64) (local $D (ref null $str)) (local $E i32) (local $n i32) (local $ea i32)
    (if (f64.ne (local.get $x) (local.get $x))
      (then (call $puts @K:nan@) (return)))
    (if (f64.eq (local.get $x) (f64.const inf))
      (then (call $puts @K:inf@) (return)))
    (if (f64.eq (local.get $x) (f64.const -inf))
      (then (call $putc (i32.const 45)) (call $puts @K:inf@) (return)))
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
    (local.set $D (call $shortest (local.get $x)))
    (local.set $E (global.get $SD_E))
    (local.set $n (array.len (local.get $D)))
    (if (f64.lt (local.get $x) (f64.const 0)) (then (call $putc (i32.const 45))))
    (if (i32.and (i32.ge_s (local.get $E) (i32.const -4)) (i32.lt_s (local.get $E) (i32.const 16)))
      (then
        (if (i32.ge_s (local.get $E) (i32.const 0))
          (then
            (if (i32.gt_s (local.get $n) (i32.add (local.get $E) (i32.const 1)))
              (then
                (call $put_bytes (local.get $D) (i32.const 0) (i32.add (local.get $E) (i32.const 1)))
                (call $putc (i32.const 46))
                (call $put_bytes (local.get $D) (i32.add (local.get $E) (i32.const 1))
                  (i32.sub (local.get $n) (i32.add (local.get $E) (i32.const 1)))))
              (else
                (call $put_str (local.get $D))
                (call $put_zeros (i32.sub (i32.add (local.get $E) (i32.const 1)) (local.get $n)))
                (call $putc (i32.const 46))
                (call $putc (i32.const 48)))))
          (else
            (call $putc (i32.const 48))
            (call $putc (i32.const 46))
            (call $put_zeros (i32.sub (i32.const -1) (local.get $E)))
            (call $put_str (local.get $D)))))
      (else
        (call $putc (array.get_u $str (local.get $D) (i32.const 0)))
        (if (i32.gt_u (local.get $n) (i32.const 1))
          (then
            (call $putc (i32.const 46))
            (call $put_bytes (local.get $D) (i32.const 1) (i32.sub (local.get $n) (i32.const 1)))))
        (call $putc (i32.const 101))
        (call $putc (select (i32.const 45) (i32.const 43) (i32.lt_s (local.get $E) (i32.const 0))))
        (local.set $ea (select (i32.sub (i32.const 0) (local.get $E)) (local.get $E) (i32.lt_s (local.get $E) (i32.const 0))))
        (if (i32.lt_u (local.get $ea) (i32.const 10)) (then (call $putc (i32.const 48))))
        (call $put_digits (i64.extend_i32_u (local.get $ea))))))

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

  ;; str(x)（F.str の num）
  (func $f_str (param $x f64) (result (ref $str))
    (local $old (ref null $buf))
    (local.set $old (call $fmt_begin))
    (call $put_num (local.get $x))
    (call $fmt_end (local.get $old)))

  (func $f_str_b (param $b i32) (result (ref $str))
    (if (result (ref $str)) (local.get $b)
      (then (call $mem_str @K:true@))
      (else (call $mem_str @K:false@))))

  ;; ---------------------------------------------------------------- strtod（10 進 → double・正確な丸め）
  ;; 受ける形は `-?digits[.digits][(e|E)[+-]digits]`（JSON の数値と str() の出す形）。
  ;; 有効 15 桁以下で |10 の指数| ≤ 22 は f64 の乗除 1 回で正確（Clinger の速い経路）。それ以外は近似値から
  ;; 始め、正確な値（桁列 × 10^E・多倍長）を隣の double との中点と比べて 1 ulp ずつ直す（AlgorithmR）。
  ;; 800 桁を超える桁列は切り詰め、0 でない桁が続いていれば末尾に 1 を足す（中点との比較を正しく保つ）。

  ;; 正確な値 $DB × 10^$DB_E と M·2^Ex を比べる（-1 / 0 / 1）。
  (func $cmp_exact (param $M i64) (param $Ex i32) (result i32)
    (local $L (ref null $bn)) (local $R (ref null $bn))
    (local.set $L (call $bn_new))
    (local.set $R (call $bn_new))
    (call $bn_set_digits (local.get $L) (global.get $DB))
    (call $bn_set_u64 (local.get $R) (local.get $M))
    (if (i32.ge_s (global.get $DB_E) (i32.const 0))
      (then (call $bn_mul_pow10 (local.get $L) (global.get $DB_E)))
      (else (call $bn_mul_pow10 (local.get $R) (i32.sub (i32.const 0) (global.get $DB_E)))))
    (if (i32.ge_s (local.get $Ex) (i32.const 0))
      (then (call $bn_mul_pow2 (local.get $R) (local.get $Ex)))
      (else (call $bn_mul_pow2 (local.get $L) (i32.sub (i32.const 0) (local.get $Ex)))))
    (call $bn_cmp (local.get $L) (local.get $R)))

  ;; (m, e) → f64（m < 2^53。m < 2^52 なら非正規化数で e = -1074）
  (func $compose (param $m i64) (param $e i32) (result f64)
    (if (result f64) (i64.ge_u (local.get $m) (i64.const 4503599627370496))
      (then
        (f64.reinterpret_i64
          (i64.or
            (i64.shl (i64.extend_i32_s (i32.add (local.get $e) (i32.const 1075))) (i64.const 52))
            (i64.sub (local.get $m) (i64.const 4503599627370496)))))
      (else (f64.reinterpret_i64 (local.get $m)))))

  (func $pow10_f64 (param $e i32) (result f64)
    (local $p f64)
    (local.set $p (f64.const 1))
    (block $done
      (loop $next
        (br_if $done (i32.le_s (local.get $e) (i32.const 0)))
        (local.set $p (f64.mul (local.get $p) (f64.const 10)))
        (local.set $e (i32.sub (local.get $e) (i32.const 1)))
        (br $next)))
    (local.get $p))


  ;; s[i]（範囲外なら -1。条件式の中で使う: wasm の i32.and は両辺を評価する）
  (func $byte_at (param $s (ref null $str)) (param $i i32) (result i32)
    (if (result i32) (i32.lt_u (local.get $i) (array.len (local.get $s)))
      (then (array.get_u $str (local.get $s) (local.get $i)))
      (else (i32.const -1))))

  (func $strtod (param $s (ref null $str)) (result f64)
    (local $i i32) (local $len i32) (local $c i32) (local $neg i32) (local $nd i32) (local $nd19 i32) (local $d19 i64)
    (local $dp i32) (local $db (ref null $buf)) (local $exp i64) (local $expneg i32)
    (local $E i32) (local $v f64) (local $m i64) (local $e i32) (local $expo2 i32) (local $cmp i32) (local $M i64)
    (local $Ex i32) (local $iter i32) (local $kept i32)
    (local.set $len (array.len (local.get $s)))
    (local.set $db (call $buf_new (i32.const 32)))
    (if (i32.eq (call $byte_at (local.get $s) (i32.const 0)) (i32.const 45))
      (then (local.set $neg (i32.const 1)) (local.set $i (i32.const 1))))
    ;; 整数部
    (block $int_done
      (loop $int
        (br_if $int_done (i32.ge_u (local.get $i) (local.get $len)))
        (local.set $c (array.get_u $str (local.get $s) (local.get $i)))
        (br_if $int_done (i32.gt_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (if (i32.or (local.get $nd) (i32.ne (local.get $c) (i32.const 48)))
          (then
            (local.set $dp (i32.add (local.get $dp) (i32.const 1)))
            (call $strtod_digit (local.get $db) (local.get $c))
            (local.set $nd (i32.add (local.get $nd) (i32.const 1)))
            (if (i32.lt_u (local.get $nd19) (i32.const 19))
              (then
                (local.set $d19 (i64.add (i64.mul (local.get $d19) (i64.const 10)) (i64.extend_i32_u (i32.sub (local.get $c) (i32.const 48)))))
                (local.set $nd19 (i32.add (local.get $nd19) (i32.const 1)))))))
        (br $int)))
    ;; 小数部
    (if (i32.eq (call $byte_at (local.get $s) (local.get $i)) (i32.const 46))
      (then
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (block $frac_done
          (loop $frac
            (br_if $frac_done (i32.ge_u (local.get $i) (local.get $len)))
            (local.set $c (array.get_u $str (local.get $s) (local.get $i)))
            (br_if $frac_done (i32.gt_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9)))
            (local.set $i (i32.add (local.get $i) (i32.const 1)))
            (if (i32.or (local.get $nd) (i32.ne (local.get $c) (i32.const 48)))
              (then
                (call $strtod_digit (local.get $db) (local.get $c))
                (local.set $nd (i32.add (local.get $nd) (i32.const 1)))
                (if (i32.lt_u (local.get $nd19) (i32.const 19))
                  (then
                    (local.set $d19 (i64.add (i64.mul (local.get $d19) (i64.const 10)) (i64.extend_i32_u (i32.sub (local.get $c) (i32.const 48)))))
                    (local.set $nd19 (i32.add (local.get $nd19) (i32.const 1))))))
              (else (local.set $dp (i32.sub (local.get $dp) (i32.const 1)))))
            (br $frac)))))
    ;; 指数部
    (if (i32.eq (i32.or (call $byte_at (local.get $s) (local.get $i)) (i32.const 32)) (i32.const 101))
      (then
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (local.set $c (call $byte_at (local.get $s) (local.get $i)))
        (if (i32.eq (local.get $c) (i32.const 45))
          (then (local.set $expneg (i32.const 1)) (local.set $i (i32.add (local.get $i) (i32.const 1)))))
        (if (i32.eq (local.get $c) (i32.const 43))
          (then (local.set $i (i32.add (local.get $i) (i32.const 1)))))
        (block $exp_done
          (loop $expl
            (br_if $exp_done (i32.ge_u (local.get $i) (local.get $len)))
            (local.set $c (array.get_u $str (local.get $s) (local.get $i)))
            (br_if $exp_done (i32.gt_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9)))
            (local.set $i (i32.add (local.get $i) (i32.const 1)))
            (if (i64.lt_s (local.get $exp) (i64.const 100000))
              (then (local.set $exp (i64.add (i64.mul (local.get $exp) (i64.const 10)) (i64.extend_i32_u (i32.sub (local.get $c) (i32.const 48)))))))
            (br $expl)))
        (if (local.get $expneg) (then (local.set $exp (i64.sub (i64.const 0) (local.get $exp)))))))
    (if (i32.eqz (local.get $nd))
      (then (return (select (f64.const -0) (f64.const 0) (local.get $neg)))))
    ;; 値 = (nd 桁の整数) × 10^E
    (local.set $E (i32.add (i32.wrap_i64 (local.get $exp)) (i32.sub (local.get $dp) (local.get $nd))))
    ;; 速い経路（正確）
    (if (i32.and (i32.le_u (local.get $nd) (i32.const 15))
          (i32.and (i32.ge_s (local.get $E) (i32.const -22)) (i32.le_s (local.get $E) (i32.const 22))))
      (then
        (local.set $v (f64.convert_i64_u (local.get $d19)))
        (if (i32.lt_s (local.get $E) (i32.const 0))
          (then (local.set $v (f64.div (local.get $v) (call $pow10_f64 (i32.sub (i32.const 0) (local.get $E))))))
          (else (local.set $v (f64.mul (local.get $v) (call $pow10_f64 (local.get $E))))))
        (return (select (f64.neg (local.get $v)) (local.get $v) (local.get $neg)))))
    (if (i32.and (i32.le_u (local.get $nd) (i32.const 15))
          (i32.and (i32.gt_s (local.get $E) (i32.const 22)) (i32.le_s (local.get $E) (i32.add (i32.const 22) (i32.sub (i32.const 15) (local.get $nd))))))
      (then
        (local.set $v (f64.mul (f64.convert_i64_u (local.get $d19)) (call $pow10_f64 (i32.sub (local.get $E) (i32.const 22)))))
        (local.set $v (f64.mul (local.get $v) (f64.const 1e22)))
        (return (select (f64.neg (local.get $v)) (local.get $v) (local.get $neg)))))
    ;; 桁数から明らかな溢れ / 0
    (if (i32.gt_s (i32.add (local.get $E) (local.get $nd)) (i32.const 310))
      (then (return (select (f64.const -inf) (f64.const inf) (local.get $neg)))))
    (if (i32.lt_s (i32.add (local.get $E) (local.get $nd)) (i32.const -343))
      (then (return (select (f64.const -0) (f64.const 0) (local.get $neg)))))
    ;; 正確な桁列（$strtod_digit が 800 桁で切り詰め、0 でない桁が続けば 801 桁目に 1 を置いてある）
    (local.set $kept (struct.get $buf 1 (local.get $db)))
    (global.set $DB (call $str_slice (struct.get $buf 0 (local.get $db)) (i32.const 0) (local.get $kept)))
    (global.set $DB_E (i32.add (local.get $E) (i32.sub (local.get $nd) (local.get $kept))))
    ;; 近似値: 先頭 19 桁 × 10^expo2
    (local.set $expo2 (i32.add (local.get $E) (i32.sub (local.get $nd) (local.get $nd19))))
    (local.set $v (f64.convert_i64_u (local.get $d19)))
    (block $scaled
      (loop $up
        (br_if $scaled (i32.lt_s (local.get $expo2) (i32.const 100)))
        (local.set $v (f64.mul (local.get $v) (f64.const 1e100)))
        (local.set $expo2 (i32.sub (local.get $expo2) (i32.const 100)))
        (br $up)))
    (block $scaled2
      (loop $down
        (br_if $scaled2 (i32.gt_s (local.get $expo2) (i32.const -100)))
        (local.set $v (f64.mul (local.get $v) (f64.const 1e-100)))
        (local.set $expo2 (i32.add (local.get $expo2) (i32.const 100)))
        (br $down)))
    (if (i32.lt_s (local.get $expo2) (i32.const 0))
      (then (local.set $v (f64.div (local.get $v) (call $pow10_f64 (i32.sub (i32.const 0) (local.get $expo2))))))
      (else (local.set $v (f64.mul (local.get $v) (call $pow10_f64 (local.get $expo2))))))
    ;; (m, e) に分解
    (if (f64.eq (local.get $v) (f64.const inf))
      (then (local.set $m (i64.const 9007199254740991)) (local.set $e (i32.const 971)))
      (else
        (local.set $M (i64.reinterpret_f64 (local.get $v)))
        (local.set $e (i32.wrap_i64 (i64.shr_u (local.get $M) (i64.const 52))))
        (local.set $m (i64.and (local.get $M) (i64.const 0xFFFFFFFFFFFFF)))
        (if (i32.eqz (local.get $e))
          (then (local.set $e (i32.const -1074)))
          (else
            (local.set $m (i64.or (local.get $m) (i64.const 4503599627370496)))
            (local.set $e (i32.sub (local.get $e) (i32.const 1075)))))))
    ;; 1 ulp ずつ直す
    (block $settled
      (loop $adjust
        (local.set $iter (i32.add (local.get $iter) (i32.const 1)))
        (br_if $settled (i32.gt_u (local.get $iter) (i32.const 20000)))
        ;; 上の中点 (2m+1)·2^(e-1)
        (local.set $cmp (call $cmp_exact (i64.add (i64.mul (local.get $m) (i64.const 2)) (i64.const 1)) (i32.sub (local.get $e) (i32.const 1))))
        (if (i32.or (i32.gt_s (local.get $cmp) (i32.const 0))
              (i32.and (i32.eqz (local.get $cmp)) (i32.wrap_i64 (i64.and (local.get $m) (i64.const 1)))))
          (then
            (if (i64.eq (local.get $m) (i64.const 9007199254740991))
              (then
                (if (i32.ge_s (local.get $e) (i32.const 971))
                  (then (return (select (f64.const -inf) (f64.const inf) (local.get $neg)))))
                (local.set $m (i64.const 4503599627370496))
                (local.set $e (i32.add (local.get $e) (i32.const 1))))
              (else (local.set $m (i64.add (local.get $m) (i64.const 1)))))
            (br $adjust)))
        (br_if $settled (i64.eqz (local.get $m)))
        ;; 下の中点
        (if (i32.and (i64.eq (local.get $m) (i64.const 4503599627370496)) (i32.gt_s (local.get $e) (i32.const -1074)))
          (then
            (local.set $M (i64.add (i64.mul (local.get $m) (i64.const 2)) (i64.const 9007199254740991)))
            (local.set $Ex (i32.sub (local.get $e) (i32.const 2))))
          (else
            (local.set $M (i64.sub (i64.mul (local.get $m) (i64.const 2)) (i64.const 1)))
            (local.set $Ex (i32.sub (local.get $e) (i32.const 1)))))
        (local.set $cmp (call $cmp_exact (local.get $M) (local.get $Ex)))
        (if (i32.or (i32.lt_s (local.get $cmp) (i32.const 0))
              (i32.and (i32.eqz (local.get $cmp)) (i32.wrap_i64 (i64.and (local.get $m) (i64.const 1)))))
          (then
            (if (i32.and (i64.eq (local.get $m) (i64.const 4503599627370496)) (i32.gt_s (local.get $e) (i32.const -1074)))
              (then
                (local.set $m (i64.const 9007199254740991))
                (local.set $e (i32.sub (local.get $e) (i32.const 1))))
              (else (local.set $m (i64.sub (local.get $m) (i64.const 1)))))
            (br $adjust)))))
    (local.set $v (call $compose (local.get $m) (local.get $e)))
    (select (f64.neg (local.get $v)) (local.get $v) (local.get $neg)))

  ;; strtod の桁の積み上げ: 800 桁まで積み、それ以降は 0 以外の桁が来たら 801 桁目に 1 を置く（粘着）。
  (func $strtod_digit (param $db (ref null $buf)) (param $c i32)
    (local $n i32)
    (local.set $n (struct.get $buf 1 (local.get $db)))
    (if (i32.lt_u (local.get $n) (i32.const 800))
      (then
        (call $buf_reserve (local.get $db) (i32.const 1))
        (array.set $str (struct.get $buf 0 (local.get $db)) (local.get $n) (local.get $c))
        (struct.set $buf 1 (local.get $db) (i32.add (local.get $n) (i32.const 1))))
      (else
        (if (i32.and (i32.eq (local.get $n) (i32.const 800)) (i32.ne (local.get $c) (i32.const 48)))
          (then
            (call $buf_reserve (local.get $db) (i32.const 1))
            (array.set $str (struct.get $buf 0 (local.get $db)) (i32.const 800) (i32.const 49))
            (struct.set $buf 1 (local.get $db) (i32.const 801)))))))

  ;; num(str)（expr.md §4.1・F.num）: 受ける形は `-?d+`, `-?d+.d+`, `-?d+[eE][-+]?d+`, `-?d+.d+[eE][-+]?d+` だけ。
  ;; 合わなければ 0。NaN / ±Infinity になる値も 0。結果は + 0.0（-0.0 は 0.0 に）。
  (func $f_num (param $s (ref null $str)) (result f64)
    (local $i i32) (local $len i32) (local $c i32) (local $k i32) (local $v f64)
    (local.set $len (array.len (local.get $s)))
    (if (i32.eq (call $byte_at (local.get $s) (i32.const 0)) (i32.const 45))
      (then (local.set $i (i32.const 1))))
    (local.set $k (call $scan_digits (local.get $s) (local.get $i)))
    (if (i32.eq (local.get $k) (local.get $i)) (then (return (f64.const 0))))
    (local.set $i (local.get $k))
    (if (i32.eq (call $byte_at (local.get $s) (local.get $i)) (i32.const 46))
      (then
        (local.set $k (call $scan_digits (local.get $s) (i32.add (local.get $i) (i32.const 1))))
        (if (i32.eq (local.get $k) (i32.add (local.get $i) (i32.const 1))) (then (return (f64.const 0))))
        (local.set $i (local.get $k))))
    (if (i32.eq (i32.or (call $byte_at (local.get $s) (local.get $i)) (i32.const 32)) (i32.const 101))
      (then
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (local.set $c (call $byte_at (local.get $s) (local.get $i)))
        (if (i32.or (i32.eq (local.get $c) (i32.const 45)) (i32.eq (local.get $c) (i32.const 43)))
          (then (local.set $i (i32.add (local.get $i) (i32.const 1)))))
        (local.set $k (call $scan_digits (local.get $s) (local.get $i)))
        (if (i32.eq (local.get $k) (local.get $i)) (then (return (f64.const 0))))
        (local.set $i (local.get $k))))
    (if (i32.ne (local.get $i) (local.get $len)) (then (return (f64.const 0))))
    (local.set $v (call $strtod (local.get $s)))
    (if (i32.or (f64.ne (local.get $v) (local.get $v)) (f64.eq (f64.abs (local.get $v)) (f64.const inf)))
      (then (return (f64.const 0))))
    (f64.add (local.get $v) (f64.const 0)))

  ;; s[i..] の数字の並びの終わり。
  (func $scan_digits (param $s (ref null $str)) (param $i i32) (result i32)
    (local $len i32)
    (local.set $len (array.len (local.get $s)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $len)))
        (br_if $done (i32.gt_u (i32.sub (array.get_u $str (local.get $s) (local.get $i)) (i32.const 48)) (i32.const 9)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (local.get $i))
