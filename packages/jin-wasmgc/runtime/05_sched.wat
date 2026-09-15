
  ;; ---------------------------------------------------------------- スケジューラ（runtime.md §2 / §3・プレリュードの写し・Issue #75）
  ;; 陣は添字（0 始まり）で持ち、陣ごとの関数（init / publish / core / on … ）は生成部の $prog_* が添字で振り分ける。
  ;; 生存は配列（boot で $N の大きさに確保する。ランタイム部の global は後ろに来る生成部の $N を定数式で参照できない）。
  (type $Row (struct (field i32) (field i32) (field i32) (field i32)   ;; seq / tick / 陣（-1 なら null）/ kind（$kind_str）
    (field (ref null $str)) (field (ref null $str)) (field (ref null $str)) (field (mut (ref null $str)))))   ;; name / pointer / input / output（JSON の断片）
  (type $Wait (struct (field i32) (field i32) (field (mut f64)) (field i32)   ;; 陣 / 種（1 ticks・2 until）/ 残り tick / until の式の番号
    (field (ref null $str)) (field anyref) (field anyref) (field i32)))       ;; pointer / 根のフレーム / 最も内側のフレーム / 手順の番号
  (type $Msg (struct (field i32) (field i32) (field (ref null $str)) (field anyref)   ;; emit の場所 / 宛先 / メッセージ名 / 引数（生成部の struct）
    (field i32) (field (ref null $str)) (field (ref null $str))))                  ;; 発信元 / emit ステップの pointer / 引数の JSON（DEBUG）
  (type $Ask (struct (field i32) (field i32) (field (ref null $str)) (field (ref null $str)) (field i32)))   ;; id / 陣 / sigil 名 / sigil の pointer / 場所

  (global $CST (mut (ref null $li)) (ref.null $li))       ;; 0 idle / 1 active / 2 done
  (global $CPAUSED (mut (ref null $li)) (ref.null $li))
  (global $CPENDING (mut (ref null $li)) (ref.null $li))
  (global $CCURSOR (mut (ref null $li)) (ref.null $li))
  (global $CPUB (mut (ref null $li)) (ref.null $li))      ;; published
  (global $CDELEG (mut (ref null $li)) (ref.null $li))    ;; 委譲先（-1 なら無し）
  (global $WAITS (mut (ref $Lr)) (struct.new $Lr (array.new_default $lr (i32.const 8)) (i32.const 0)))   ;; wait 中の手順（全陣・登録順）
  (global $Q (mut (ref $Lr)) (struct.new $Lr (array.new_default $lr (i32.const 8)) (i32.const 0)))       ;; 次 tick に配達するメッセージ
  (global $TRACE (mut (ref $Lr)) (struct.new $Lr (array.new_default $lr (i32.const 64)) (i32.const 0)))  ;; トレース行（DEBUG）
  (global $ASKMAP (mut (ref $Lr)) (struct.new $Lr (array.new_default $lr (i32.const 4)) (i32.const 0)))  ;; 未回答の問い
  (global $ORD (mut (ref $Li)) (struct.new $Li (array.new_default $li (i32.const 8)) (i32.const 0)))     ;; 陣の順
  (global $ASKS (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 64)) (i32.const 0)))  ;; この tick の問い（JSON 断片）
  (global $ASKS_N (mut i32) (i32.const 0))
  (global $ASKED (mut i32) (i32.const 0))
  (global $SEQ (mut i32) (i32.const 0))
  (global $CUR_CI (mut i32) (i32.const -1))
  (global $CUR_PTR (mut (ref null $str)) (ref.null $str))
  (global $WREQ_KIND (mut i32) (i32.const 0))          ;; wait の要求（生成部の wait ステップが置き、$register_wait が読む）
  (global $WREQ_TICKS (mut f64) (f64.const 0))
  (global $WREQ_UID (mut i32) (i32.const 0))
  (global $WREQ_PTR (mut (ref null $str)) (ref.null $str))
  (global $WREQ_TOP (mut anyref) (ref.null any))
  (global $RN_MODE (mut i32) (i32.const 0))            ;; 復元の知らせ（0 無し / 1 resumed / 2 fresh）
  (global $RN_TICK (mut i32) (i32.const -1))
  (global $RN_KEPT (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 32)) (i32.const 0)))
  (global $RN_DROPPED (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 32)) (i32.const 0)))
  (global $RD_OK (mut i32) (i32.const 0))              ;; resume の読み手の成否

  (func $cget (param $a (ref null $li)) (param $i i32) (result i32) (array.get $li (local.get $a) (local.get $i)))
  (func $cset (param $a (ref null $li)) (param $i i32) (param $v i32) (array.set $li (local.get $a) (local.get $i) (local.get $v)))
  (func $cst (param $i i32) (result i32) (call $cget (global.get $CST) (local.get $i)))
  (func $is_active (param $i i32) (result i32)
    (i32.and (i32.eq (call $cst (local.get $i)) (i32.const 1)) (i32.eqz (call $cget (global.get $CPAUSED) (local.get $i)))))
  ;; STOP(i): done か休止中（生成部が cast の直後に見る）
  (func $stop (param $i i32) (result i32) (i32.eqz (call $is_active (local.get $i))))

  (func $lr_reset (param $l (ref null $Lr)) (struct.set $Lr 1 (local.get $l) (i32.const 0)))

  ;; ---------------------------------------------------------------- トレース行（runtime.md §5・DEBUG のとき）
  ;; kind: 0 enter / 1 exit / 2 event / 3 rite / 4 cast / 5 set / 6 emit / 7 transfer / 8 wait / 9 finish / 10 assert / 11 error / 12 frame
  (func $kind_str (param $k i32)
    (if (i32.eq (local.get $k) (i32.const 0)) (then (call $puts @K:kd_enter@) (return)))
    (if (i32.eq (local.get $k) (i32.const 1)) (then (call $puts @K:kd_exit@) (return)))
    (if (i32.eq (local.get $k) (i32.const 2)) (then (call $puts @K:kd_event@) (return)))
    (if (i32.eq (local.get $k) (i32.const 3)) (then (call $puts @K:kd_rite@) (return)))
    (if (i32.eq (local.get $k) (i32.const 4)) (then (call $puts @K:kd_cast@) (return)))
    (if (i32.eq (local.get $k) (i32.const 5)) (then (call $puts @K:kd_set@) (return)))
    (if (i32.eq (local.get $k) (i32.const 6)) (then (call $puts @K:kd_emit@) (return)))
    (if (i32.eq (local.get $k) (i32.const 7)) (then (call $puts @K:kd_transfer@) (return)))
    (if (i32.eq (local.get $k) (i32.const 8)) (then (call $puts @K:kd_wait@) (return)))
    (if (i32.eq (local.get $k) (i32.const 9)) (then (call $puts @K:kd_finish@) (return)))
    (if (i32.eq (local.get $k) (i32.const 10)) (then (call $puts @K:kd_assert@) (return)))
    (if (i32.eq (local.get $k) (i32.const 11)) (then (call $puts @K:kd_error@) (return)))
    (call $puts @K:kd_frame@))

  ;; ROW: 行を積み、pointer があれば CUR_PTR を、陣があれば CUR_CI を更新する（error 行のため）。
  (func $row (param $kind i32) (param $ci i32) (param $name (ref null $str)) (param $ptr (ref null $str))
             (param $input (ref null $str)) (param $output (ref null $str)) (result (ref $Row))
    (local $r (ref null $Row))
    (local.set $r (struct.new $Row (global.get $SEQ) (i32.wrap_i64 (global.get $TICK)) (local.get $ci) (local.get $kind)
      (local.get $name) (local.get $ptr) (local.get $input) (local.get $output)))
    (global.set $SEQ (i32.add (global.get $SEQ) (i32.const 1)))
    (call $lr_push (global.get $TRACE) (local.get $r))
    (if (i32.eqz (ref.is_null (local.get $ptr))) (then (global.set $CUR_PTR (local.get $ptr))))
    (if (i32.ge_s (local.get $ci) (i32.const 0)) (then (global.set $CUR_CI (local.get $ci))))
    (ref.as_non_null (local.get $r)))

  (func $row_out (param $r (ref null $Row)) (param $out (ref null $str))
    (struct.set $Row 7 (local.get $r) (local.get $out)))

  ;; 文字列（JSON の断片）か null
  (func $put_opt (param $s (ref null $str))
    (if (ref.is_null (local.get $s))
      (then (call $puts @K:null@))
      (else (call $put_str (local.get $s)))))

  (func $put_opt_js (param $s (ref null $str))
    (if (ref.is_null (local.get $s))
      (then (call $puts @K:null@))
      (else (call $put_js (local.get $s)))))

  ;; "/circles/<i>"
  (func $circle_ptr (param $i i32) (result (ref $str))
    (local $old (ref null $buf))
    (local.set $old (call $fmt_begin))
    (call $puts @K:p_circles@)
    (call $put_jn (f64.convert_i32_s (local.get $i)))
    (call $fmt_end (local.get $old)))

  ;; JSON 配列の中身（先頭の [ と末尾の ] を除く）を、空でなければコンマを付けて書く
  (func $put_inner (param $s (ref null $str))
    (local $n i32)
    (if (ref.is_null (local.get $s)) (then (return)))
    (local.set $n (array.len (local.get $s)))
    (if (i32.gt_u (local.get $n) (i32.const 2))
      (then
        (call $putc (i32.const 44))
        (call $put_bytes (local.get $s) (i32.const 1) (i32.sub (local.get $n) (i32.const 2))))))

  (func $put_row (param $r (ref null $Row))
    (call $puts @K:r_seq@)
    (call $put_jn (f64.convert_i32_s (struct.get $Row 0 (local.get $r))))
    (call $puts @K:r_tick@)
    (call $put_jn (f64.convert_i32_s (struct.get $Row 1 (local.get $r))))
    (call $puts @K:r_circle@)
    (if (i32.lt_s (struct.get $Row 2 (local.get $r)) (i32.const 0))
      (then (call $puts @K:null@))
      (else (call $put_js (call $prog_name (struct.get $Row 2 (local.get $r))))))
    (call $puts @K:r_kind@)
    (call $putc (i32.const 34))
    (call $kind_str (struct.get $Row 3 (local.get $r)))
    (call $putc (i32.const 34))
    (call $puts @K:r_name@)
    (call $put_opt_js (struct.get $Row 4 (local.get $r)))
    (call $puts @K:r_pointer@)
    (call $put_opt_js (struct.get $Row 5 (local.get $r)))
    (call $puts @K:r_input@)
    (call $put_opt (struct.get $Row 6 (local.get $r)))
    (call $puts @K:r_output@)
    (call $put_opt (struct.get $Row 7 (local.get $r)))
    (call $putc (i32.const 125)))

  (func $put_trace
    (local $i i32) (local $n i32)
    (local.set $n (struct.get $Lr 1 (global.get $TRACE)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (local.get $i) (then (call $putc (i32.const 44))))
        (call $put_row (ref.cast (ref null $Row) (array.get $lr (struct.get $Lr 0 (global.get $TRACE)) (local.get $i))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next))))

  ;; protected の受け: エラーなら error 行（CUR_CI / CUR_PTR・output はメッセージ）
  (func $error_row
    (local $old (ref null $buf))
    (if (i32.eqz (i32.and (global.get $DEBUG) (global.get $ERRED))) (then (return)))
    (local.set $old (call $fmt_begin))
    (call $put_js (global.get $ERRMSG))
    (drop (call $row (i32.const 11) (global.get $CUR_CI) (ref.null $str) (global.get $CUR_PTR) (ref.null $str)
      (call $fmt_end (local.get $old)))))

  ;; 陣の state の JSON（enter / exit 行と snapshot）
  (func $dump_str (param $i i32) (result (ref null $str))
    (local $old (ref null $buf))
    (if (call $prog_flow (local.get $i)) (then (return (ref.null $str))))
    (local.set $old (call $fmt_begin))
    (call $prog_dump (local.get $i))
    (call $fmt_end (local.get $old)))

  ;; ---------------------------------------------------------------- 陣の順（runtime.md §2「陣の順」）
  (func $ord_has (param $i i32) (result i32)
    (local $k i32) (local $n i32)
    (local.set $n (struct.get $Li 1 (global.get $ORD)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (if (i32.eq (array.get $li (struct.get $Li 0 (global.get $ORD)) (local.get $k)) (local.get $i))
          (then (return (i32.const 1))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $order_into (param $i i32)
    (local $k i32) (local $n i32)
    (if (call $prog_flow (local.get $i))
      (then
        (local.set $n (call $prog_nchildren (local.get $i)))
        (block $done
          (loop $next
            (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
            (call $order_into (call $prog_child (local.get $i) (local.get $k)))
            (local.set $k (i32.add (local.get $k) (i32.const 1)))
            (br $next)))
        (return)))
    (if (i32.and (call $cget (global.get $CPAUSED) (local.get $i))
                 (i32.ge_s (call $cget (global.get $CDELEG) (local.get $i)) (i32.const 0)))
      (then (call $order_into (call $cget (global.get $CDELEG) (local.get $i))) (return)))
    (if (i32.eqz (call $ord_has (local.get $i)))
      (then (call $li_push (global.get $ORD) (local.get $i)))))

  (func $order
    (struct.set $Li 1 (global.get $ORD) (i32.const 0))
    (call $order_into (global.get $ROOT)))

  (func $ord_at (param $k i32) (result i32) (array.get $li (struct.get $Li 0 (global.get $ORD)) (local.get $k)))
  (func $ord_len (result i32) (struct.get $Li 1 (global.get $ORD)))

  ;; ---------------------------------------------------------------- wait 中の手順（runtime.md §2 の 2）
  (func $wait_at (param $k i32) (result (ref null $Wait))
    (ref.cast (ref null $Wait) (array.get $lr (struct.get $Lr 0 (global.get $WAITS)) (local.get $k))))

  ;; 陣 i の待ちを全部捨てる（FINISH / reset / ENTER）
  (func $drop_waits (param $i i32)
    (local $k i32) (local $n i32) (local $m i32) (local $w (ref null $Wait))
    (local.set $n (struct.get $Lr 1 (global.get $WAITS)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $w (call $wait_at (local.get $k)))
        (if (i32.ne (struct.get $Wait 0 (local.get $w)) (local.get $i))
          (then
            (array.set $lr (struct.get $Lr 0 (global.get $WAITS)) (local.get $m) (local.get $w))
            (local.set $m (i32.add (local.get $m) (i32.const 1)))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (struct.set $Lr 1 (global.get $WAITS) (local.get $m)))

  ;; register_wait: 生成部の手順が wait で返った直後に、要求（$WREQ_*）を待ち列へ。陣が active でなければ捨てる
  (func $register_wait (param $i i32) (param $rite i32) (param $root anyref)
    (local $old (ref null $buf))
    (if (i32.ne (call $cst (local.get $i)) (i32.const 1)) (then (return)))
    (if (global.get $DEBUG)
      (then
        (local.set $old (call $fmt_begin))
        (if (i32.eq (global.get $WREQ_KIND) (i32.const 1))
          (then (call $puts @K:w_ticks@) (call $put_jn (global.get $WREQ_TICKS)) (call $putc (i32.const 125)))
          (else (call $puts @K:w_until@)))
        (drop (call $row (i32.const 8) (local.get $i) (ref.null $str) (global.get $WREQ_PTR)
          (call $fmt_end (local.get $old)) (call $mem_str @K:w_suspend@)))))
    (call $lr_push (global.get $WAITS)
      (struct.new $Wait (local.get $i) (global.get $WREQ_KIND) (global.get $WREQ_TICKS) (global.get $WREQ_UID)
        (global.get $WREQ_PTR) (local.get $root) (global.get $WREQ_TOP) (local.get $rite))))

  ;; WAIT_TICKS の残り: ceil、1 未満と NaN は 1（inf はそのまま）
  (func $wait_ticks_of (param $n f64) (result f64)
    (local $t f64)
    (local.set $t (f64.ceil (local.get $n)))
    (if (i32.or (f64.lt (local.get $t) (f64.const 1)) (f64.ne (local.get $t) (local.get $t)))
      (then (local.set $t (f64.const 1))))
    (local.get $t))

  (func $resume_waits
    (local $oi i32) (local $on i32) (local $i i32) (local $k i32) (local $n i32) (local $m i32) (local $go i32)
    (local $w (ref null $Wait)) (local $pending (ref null $Lr)) (local $old (ref null $buf))
    (call $order)
    (local.set $on (call $ord_len))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $oi) (local.get $on)))
        (br_if $done (global.get $ERRED))
        (local.set $i (call $ord_at (local.get $oi)))
        (if (call $is_active (local.get $i))
          (then
            ;; その時点の待ち列を丸ごと取り出す（再開中に登録された待ちは今 tick では見ない）
            (local.set $pending (call $lr_new (i32.const 4)))
            (local.set $k (i32.const 0))
            (local.set $m (i32.const 0))
            (local.set $n (struct.get $Lr 1 (global.get $WAITS)))
            (block $d2
              (loop $n2
                (br_if $d2 (i32.ge_u (local.get $k) (local.get $n)))
                (local.set $w (call $wait_at (local.get $k)))
                (if (i32.eq (struct.get $Wait 0 (local.get $w)) (local.get $i))
                  (then (call $lr_push (local.get $pending) (local.get $w)))
                  (else
                    (array.set $lr (struct.get $Lr 0 (global.get $WAITS)) (local.get $m) (local.get $w))
                    (local.set $m (i32.add (local.get $m) (i32.const 1)))))
                (local.set $k (i32.add (local.get $k) (i32.const 1)))
                (br $n2)))
            (struct.set $Lr 1 (global.get $WAITS) (local.get $m))
            (local.set $k (i32.const 0))
            (local.set $n (struct.get $Lr 1 (local.get $pending)))
            (block $d3
              (loop $n3
                (br_if $d3 (i32.ge_u (local.get $k) (local.get $n)))
                (local.set $w (ref.cast (ref null $Wait) (array.get $lr (struct.get $Lr 0 (local.get $pending)) (local.get $k))))
                (if (i32.eq (struct.get $Wait 1 (local.get $w)) (i32.const 1))
                  (then
                    (struct.set $Wait 2 (local.get $w) (f64.sub (struct.get $Wait 2 (local.get $w)) (f64.const 1)))
                    (local.set $go (f64.le (struct.get $Wait 2 (local.get $w)) (f64.const 0))))
                  (else
                    (local.set $go (call $prog_until (struct.get $Wait 3 (local.get $w)) (struct.get $Wait 6 (local.get $w))))
                    (br_if $done (global.get $ERRED))))
                (if (i32.and (local.get $go) (i32.eq (call $cst (local.get $i)) (i32.const 1)))
                  (then
                    (if (global.get $DEBUG)
                      (then
                        (drop (call $row (i32.const 8) (local.get $i) (ref.null $str) (struct.get $Wait 4 (local.get $w))
                          (call $mem_str (select (i32.const @OFF:w_ticks0@) (i32.const @OFF:w_until@) (i32.eq (struct.get $Wait 1 (local.get $w)) (i32.const 1)))
                                         (select (i32.const @LEN:w_ticks0@) (i32.const @LEN:w_until@) (i32.eq (struct.get $Wait 1 (local.get $w)) (i32.const 1))))
                          (call $mem_str @K:w_resume@)))))
                    (if (call $prog_resume (struct.get $Wait 7 (local.get $w)) (struct.get $Wait 5 (local.get $w)))
                      (then (call $register_wait (local.get $i) (struct.get $Wait 7 (local.get $w)) (struct.get $Wait 5 (local.get $w)))))
                    (br_if $done (global.get $ERRED)))
                  (else
                    (if (i32.eq (call $cst (local.get $i)) (i32.const 1))
                      (then (call $lr_push (global.get $WAITS) (local.get $w))))))
                (local.set $k (i32.add (local.get $k) (i32.const 1)))
                (br $n3)))))
        (local.set $oi (i32.add (local.get $oi) (i32.const 1)))
        (br $next))))

  ;; ---------------------------------------------------------------- 生存（runtime.md §3）
  (func $publish (param $i i32)
    (if (call $prog_has_outs (local.get $i))
      (then
        (call $prog_publish (local.get $i))
        (call $cset (global.get $CPUB) (local.get $i) (i32.const 1)))))

  (func $publish_all
    (local $i i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (global.get $N)))
        (call $publish (local.get $i))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next))))

  (func $reset (param $i i32)
    (local $k i32) (local $n i32)
    (call $cset (global.get $CST) (local.get $i) (i32.const 0))
    (call $cset (global.get $CPAUSED) (local.get $i) (i32.const 0))
    (call $cset (global.get $CPENDING) (local.get $i) (i32.const 0))
    (call $cset (global.get $CCURSOR) (local.get $i) (i32.const 0))
    (call $drop_waits (local.get $i))
    (if (i32.ge_s (call $cget (global.get $CDELEG) (local.get $i)) (i32.const 0))
      (then
        (call $reset (call $cget (global.get $CDELEG) (local.get $i)))
        (call $cset (global.get $CDELEG) (local.get $i) (i32.const -1))))
    (if (call $prog_flow (local.get $i))
      (then
        (local.set $n (call $prog_nchildren (local.get $i)))
        (block $done
          (loop $next
            (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
            (call $reset (call $prog_child (local.get $i) (local.get $k)))
            (local.set $k (i32.add (local.get $k) (i32.const 1)))
            (br $next))))))

  (func $enter (param $i i32)
    (local $k i32) (local $n i32)
    (call $cset (global.get $CST) (local.get $i) (i32.const 1))
    (call $cset (global.get $CPAUSED) (local.get $i) (i32.const 0))
    (call $cset (global.get $CPENDING) (local.get $i) (i32.const 0))
    (call $cset (global.get $CCURSOR) (local.get $i) (i32.const 1))
    (call $drop_waits (local.get $i))
    (if (call $prog_flow (local.get $i))
      (then
        (if (i32.eq (call $prog_flow (local.get $i)) (i32.const 2))
          (then
            (local.set $n (call $prog_nchildren (local.get $i)))
            (block $done
              (loop $next
                (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
                (call $enter (call $prog_child (local.get $i) (local.get $k)))
                (local.set $k (i32.add (local.get $k) (i32.const 1)))
                (br $next))))
          (else (call $enter (call $prog_child (local.get $i) (i32.const 0)))))
        (return)))
    (call $prog_init (local.get $i))
    (call $publish (local.get $i))
    (if (global.get $DEBUG)
      (then (drop (call $row (i32.const 0) (local.get $i) (call $prog_name (local.get $i)) (call $circle_ptr (local.get $i))
        (ref.null $str) (call $dump_str (local.get $i))))))
    (call $prog_core (local.get $i)))

  (func $finish (param $i i32)
    (if (i32.ne (call $cst (local.get $i)) (i32.const 1)) (then (return)))
    (call $cset (global.get $CST) (local.get $i) (i32.const 2))
    (call $publish (local.get $i))
    (call $drop_waits (local.get $i))
    (if (global.get $DEBUG)
      (then (drop (call $row (i32.const 1) (local.get $i) (call $prog_name (local.get $i)) (call $circle_ptr (local.get $i))
        (ref.null $str) (call $dump_str (local.get $i))))))
    (if (call $prog_has_on (local.get $i) (i32.const 4))
      (then (call $prog_on_exit (local.get $i)))))

  (func $transfer (param $i i32) (param $j i32)
    (local $old (ref null $buf))
    (if (i32.ne (call $cst (local.get $i)) (i32.const 1)) (then (return)))
    (if (i32.ne (call $cst (local.get $j)) (i32.const 0))
      (then
        (local.set $old (call $fmt_begin))
        (call $puts @K:msg_transfer1@)
        (call $put_str (call $prog_name (local.get $j)))
        (call $puts @K:msg_transfer2@)
        (call $ERR (call $fmt_end (local.get $old)))
        (return)))
    (call $cset (global.get $CPAUSED) (local.get $i) (i32.const 1))
    (call $cset (global.get $CDELEG) (local.get $i) (local.get $j))
    (call $cset (global.get $CPENDING) (local.get $i) (i32.const 1)))

  ;; EMIT: 次 tick の 1 で配達する。args は生成部の struct（emit の場所ごと）。args_json / ptr は DEBUG だけ
  (func $emit (param $site i32) (param $to i32) (param $name (ref $str)) (param $args anyref)
              (param $ci i32) (param $ptr (ref null $str)) (param $args_json (ref null $str))
    (call $lr_push (global.get $Q)
      (struct.new $Msg (local.get $site) (local.get $to) (local.get $name) (local.get $args) (local.get $ci) (local.get $ptr) (local.get $args_json))))

  ;; ASK: v1 の陣への問い（runtime.md §11）。同期で返るのは要求 id だけ
  (func $ask (param $ci i32) (param $name (ref $str)) (param $ptr (ref $str)) (param $site i32) (param $prompt (ref null $str)) (result f64)
    (local $old (ref null $buf))
    (global.set $ASKED (i32.add (global.get $ASKED) (i32.const 1)))
    (call $lr_push (global.get $ASKMAP)
      (struct.new $Ask (global.get $ASKED) (local.get $ci) (local.get $name) (local.get $ptr) (local.get $site)))
    (local.set $old (global.get $OUT))
    (global.set $OUT (global.get $ASKS))
    (if (global.get $ASKS_N) (then (call $putc (i32.const 44))))
    (global.set $ASKS_N (i32.add (global.get $ASKS_N) (i32.const 1)))
    (call $puts @K:a_id@)
    (call $put_jn (f64.convert_i32_s (global.get $ASKED)))
    (call $puts @K:a_circle@)
    (call $put_js (call $prog_name (local.get $ci)))
    (call $puts @K:a_name@)
    (call $put_js (local.get $name))
    (call $puts @K:a_prompt@)
    (call $put_js (local.get $prompt))
    (call $putc (i32.const 125))
    (global.set $OUT (ref.as_non_null (local.get $old)))
    (f64.convert_i32_s (global.get $ASKED)))

  ;; 未回答の問いを id で引く（-1 なら無し）
  (func $ask_find (param $id i32) (result i32)
    (local $k i32) (local $n i32)
    (local.set $n (struct.get $Lr 1 (global.get $ASKMAP)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (if (i32.eq (struct.get $Ask 0 (ref.cast (ref null $Ask) (array.get $lr (struct.get $Lr 0 (global.get $ASKMAP)) (local.get $k)))) (local.get $id))
          (then (return (local.get $k))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (i32.const -1))

  (func $advance_flow (param $i i32) (result i32)
    (local $k i32) (local $n i32) (local $changed i32) (local $child i32) (local $cur i32)
    (if (i32.ne (call $cst (local.get $i)) (i32.const 1)) (then (return (i32.const 0))))
    (local.set $n (call $prog_nchildren (local.get $i)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $child (call $prog_child (local.get $i) (local.get $k)))
        (if (i32.and (i32.ne (call $prog_flow (local.get $child)) (i32.const 0)) (i32.eq (call $cst (local.get $child)) (i32.const 1)))
          (then (if (call $advance_flow (local.get $child)) (then (local.set $changed (i32.const 1))))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (if (i32.eq (call $prog_flow (local.get $i)) (i32.const 2))
      (then
        (local.set $k (i32.const 0))
        (block $done
          (loop $next
            (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
            (if (i32.ne (call $cst (call $prog_child (local.get $i) (local.get $k))) (i32.const 2))
              (then (return (local.get $changed))))
            (local.set $k (i32.add (local.get $k) (i32.const 1)))
            (br $next)))
        (call $cset (global.get $CST) (local.get $i) (i32.const 2))
        (return (i32.const 1))))
    (local.set $cur (call $prog_child (local.get $i) (i32.sub (call $cget (global.get $CCURSOR) (local.get $i)) (i32.const 1))))
    (if (i32.ne (call $cst (local.get $cur)) (i32.const 2)) (then (return (local.get $changed))))
    (if (i32.lt_s (call $cget (global.get $CCURSOR) (local.get $i)) (local.get $n))
      (then
        (call $cset (global.get $CCURSOR) (local.get $i) (i32.add (call $cget (global.get $CCURSOR) (local.get $i)) (i32.const 1)))
        (call $enter (call $prog_child (local.get $i) (i32.sub (call $cget (global.get $CCURSOR) (local.get $i)) (i32.const 1))))
        (return (i32.const 1))))
    (if (i32.or (i32.eq (call $prog_flow (local.get $i)) (i32.const 1)) (call $prog_exit (local.get $i)))
      (then
        (call $cset (global.get $CST) (local.get $i) (i32.const 2))
        (return (i32.const 1))))
    (local.set $k (i32.const 0))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (call $reset (call $prog_child (local.get $i) (local.get $k)))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (call $cset (global.get $CCURSOR) (local.get $i) (i32.const 1))
    (call $enter (call $prog_child (local.get $i) (i32.const 0)))
    (i32.const 1))

  (func $advance
    (local $round i32) (local $i i32) (local $changed i32) (local $d i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $round) (i32.const 1000)))
        (br_if $done (global.get $ERRED))
        (local.set $changed (i32.const 0))
        (local.set $i (i32.const 0))
        (block $d2
          (loop $n2
            (br_if $d2 (i32.ge_u (local.get $i) (global.get $N)))
            (local.set $d (call $cget (global.get $CDELEG) (local.get $i)))
            (if (i32.ge_s (local.get $d) (i32.const 0))
              (then
                (if (i32.and (call $cget (global.get $CPENDING) (local.get $i)) (i32.eqz (call $cst (local.get $d))))
                  (then
                    (call $cset (global.get $CPENDING) (local.get $i) (i32.const 0))
                    (call $enter (local.get $d))
                    (local.set $changed (i32.const 1)))
                  (else
                    (if (i32.eq (call $cst (local.get $d)) (i32.const 2))
                      (then
                        (call $reset (local.get $d))
                        (call $cset (global.get $CDELEG) (local.get $i) (i32.const -1))
                        (call $cset (global.get $CPAUSED) (local.get $i) (i32.const 0))
                        (local.set $changed (i32.const 1))))))))
            (local.set $i (i32.add (local.get $i) (i32.const 1)))
            (br $n2)))
        (if (call $prog_flow (global.get $ROOT))
          (then (if (call $advance_flow (global.get $ROOT)) (then (local.set $changed (i32.const 1))))))
        (if (i32.eq (call $cst (global.get $ROOT)) (i32.const 2)) (then (global.set $DONE (i32.const 1))))
        (br_if $done (i32.eqz (local.get $changed)))
        (local.set $round (i32.add (local.get $round) (i32.const 1)))
        (br $next)))
    (if (i32.and (i32.ge_u (local.get $round) (i32.const 1000)) (i32.eqz (global.get $ERRED)))
      (then (call $ERR (call $mem_str @K:msg_advance@)))))

  ;; boot の初期状態（idle・init の値）
  (func $fresh_state
    (local $i i32)
    (global.set $CST (array.new_default $li (global.get $N)))
    (global.set $CPAUSED (array.new_default $li (global.get $N)))
    (global.set $CPENDING (array.new_default $li (global.get $N)))
    (global.set $CCURSOR (array.new_default $li (global.get $N)))
    (global.set $CPUB (array.new_default $li (global.get $N)))
    (global.set $CDELEG (array.new $li (i32.const -1) (global.get $N)))
    (call $lr_reset (global.get $WAITS))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (global.get $N)))
        (if (i32.eqz (call $prog_flow (local.get $i)))
          (then
            (call $prog_init (local.get $i))
            (call $publish (local.get $i))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next))))

  ;; ---------------------------------------------------------------- tick の手順（runtime.md §2）
  (func $deliver
    (local $q (ref null $Lr)) (local $k i32) (local $n i32) (local $m (ref null $Msg)) (local $to i32) (local $delivered i32)
    (local $ev (ref null $J)) (local $idf f64) (local $id i32) (local $a i32) (local $ask (ref null $Ask)) (local $text (ref null $str))
    (local $old (ref null $buf))
    (local.set $q (global.get $Q))
    (global.set $Q (call $lr_new (i32.const 4)))
    (local.set $n (struct.get $Lr 1 (local.get $q)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (br_if $done (global.get $ERRED))
        (local.set $m (ref.cast (ref null $Msg) (array.get $lr (struct.get $Lr 0 (local.get $q)) (local.get $k))))
        (local.set $to (struct.get $Msg 1 (local.get $m)))
        (local.set $delivered (i32.and (call $is_active (local.get $to)) (call $prog_has_on (local.get $to) (i32.const 5))))
        (if (global.get $DEBUG)
          (then (drop (call $row (i32.const 6) (struct.get $Msg 4 (local.get $m)) (struct.get $Msg 2 (local.get $m))
            (struct.get $Msg 5 (local.get $m)) (struct.get $Msg 6 (local.get $m))
            (call $mem_str (select (i32.const @OFF:true@) (i32.const @OFF:false@) (local.get $delivered))
                           (select (i32.const @LEN:true@) (i32.const @LEN:false@) (local.get $delivered)))))))
        (if (local.get $delivered) (then (call $prog_deliver (struct.get $Msg 0 (local.get $m)) (local.get $m))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    ;; v1 の陣の答え（入力イベント reply）。id を知らない / 宛先が active でない / on message が無いときは捨てる
    (local.set $k (i32.const 0))
    (local.set $n (call $ev_count))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (br_if $done (global.get $ERRED))
        (if (i32.eq (call $ev_kind (local.get $k)) (i32.const 4))
          (then
            (local.set $ev (call $ev_at (local.get $k)))
            (local.set $idf (call $j_num (call $j_getk (local.get $ev) @K:k_id@)))
            ;; math.tointeger: 整数値のときだけ（0 は「id 無し」の印に使う）
            (local.set $id (i32.const 0))
            (if (i32.and (i32.eq (call $j_kind (call $j_getk (local.get $ev) @K:k_id@)) (i32.const 2))
                         (i32.and (f64.eq (local.get $idf) (f64.floor (local.get $idf))) (f64.lt (f64.abs (local.get $idf)) (f64.const 2147483648))))
              (then (local.set $id (i32.trunc_f64_s (local.get $idf)))))
            (local.set $a (if (result i32) (local.get $id) (then (call $ask_find (local.get $id))) (else (i32.const -1))))
            (local.set $text (call $j_str (call $j_getk (local.get $ev) @K:k_text@)))
            (if (ref.is_null (local.get $text)) (then (local.set $text (call $str_empty))))
            (local.set $delivered (i32.const 0))
            (local.set $ask (ref.null $Ask))
            (if (i32.ge_s (local.get $a) (i32.const 0))
              (then
                (local.set $ask (ref.cast (ref null $Ask) (array.get $lr (struct.get $Lr 0 (global.get $ASKMAP)) (local.get $a))))
                (local.set $delivered (i32.and (call $is_active (struct.get $Ask 1 (local.get $ask)))
                                               (call $prog_has_on (struct.get $Ask 1 (local.get $ask)) (i32.const 5))))))
            (if (global.get $DEBUG)
              (then
                (local.set $old (call $fmt_begin))
                (call $putc (i32.const 91))
                (call $put_jn (f64.convert_i32_s (local.get $id)))
                (call $putc (i32.const 44))
                (call $put_js (local.get $text))
                (call $putc (i32.const 93))
                (drop (call $row (i32.const 6)
                  (if (result i32) (ref.is_null (local.get $ask)) (then (i32.const -1)) (else (struct.get $Ask 1 (local.get $ask))))
                  (if (result (ref null $str)) (ref.is_null (local.get $ask)) (then (ref.null $str)) (else (struct.get $Ask 2 (local.get $ask))))
                  (if (result (ref null $str)) (ref.is_null (local.get $ask)) (then (ref.null $str)) (else (struct.get $Ask 3 (local.get $ask))))
                  (call $fmt_end (local.get $old))
                  (call $mem_str (select (i32.const @OFF:true@) (i32.const @OFF:false@) (local.get $delivered))
                                 (select (i32.const @LEN:true@) (i32.const @LEN:false@) (local.get $delivered)))))))
            ;; 一度届いた id は二度目を捨てる（配達の有無に関わらず消費する）
            (if (i32.ge_s (local.get $a) (i32.const 0)) (then (call $e_remove_r (global.get $ASKMAP) (f64.convert_i32_s (local.get $a)))))
            (if (local.get $delivered)
              (then (call $prog_reply (struct.get $Ask 4 (local.get $ask)) (f64.convert_i32_s (local.get $id)) (ref.as_non_null (local.get $text)))))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next))))

  (func $dispatch_events
    (local $oi i32) (local $on i32) (local $i i32) (local $k i32) (local $n i32) (local $kind i32)
    (call $order)
    (local.set $on (call $ord_len))
    (local.set $n (call $ev_count))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $oi) (local.get $on)))
        (br_if $done (global.get $ERRED))
        (local.set $i (call $ord_at (local.get $oi)))
        (if (call $is_active (local.get $i))
          (then
            (local.set $k (i32.const 0))
            (block $d2
              (loop $n2
                (br_if $d2 (i32.ge_u (local.get $k) (local.get $n)))
                (br_if $d2 (call $stop (local.get $i)))
                (br_if $d2 (global.get $ERRED))
                (local.set $kind (call $ev_kind (local.get $k)))
                (if (i32.and (i32.eq (local.get $kind) (i32.const 1)) (call $prog_has_on (local.get $i) (i32.const 1)))
                  (then (call $prog_on_key (local.get $i) (local.get $k))))
                (if (i32.and (i32.eq (local.get $kind) (i32.const 2)) (call $prog_has_on (local.get $i) (i32.const 2)))
                  (then (call $prog_on_pointer (local.get $i) (local.get $k))))
                (local.set $k (i32.add (local.get $k) (i32.const 1)))
                (br $n2)))
            (if (i32.and (i32.eqz (call $stop (local.get $i))) (i32.and (i32.eqz (global.get $ERRED)) (call $prog_has_on (local.get $i) (i32.const 3))))
              (then (call $prog_on_tick (local.get $i))))))
        (local.set $oi (i32.add (local.get $oi) (i32.const 1)))
        (br $next))))

  (func $check_guards
    (local $oi i32) (local $on i32) (local $i i32)
    (call $order)
    (local.set $on (call $ord_len))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $oi) (local.get $on)))
        (br_if $done (global.get $ERRED))
        (local.set $i (call $ord_at (local.get $oi)))
        (if (call $is_active (local.get $i)) (then (call $prog_guards (local.get $i))))
        (local.set $oi (i32.add (local.get $oi) (i32.const 1)))
        (br $next))))

  ;; step(t): 1 配達 → 2 再開 → 3 イベント → 4 確定 → 5 検査（DEBUG）→ 6 進行。エラーなら以降を飛ばす（pcall の写し）
  (func $step
    (call $deliver)
    (if (global.get $ERRED) (then (return)))
    (call $resume_waits)
    (if (global.get $ERRED) (then (return)))
    (call $dispatch_events)
    (if (global.get $ERRED) (then (return)))
    (call $publish_all)
    (if (global.get $DEBUG) (then (call $check_guards)))
    (if (global.get $ERRED) (then (return)))
    (call $advance))

  ;; ---------------------------------------------------------------- 状態を保った差し替え（runtime.md §1.3）
  (func $put_status (param $s i32)
    (if (i32.eq (local.get $s) (i32.const 1)) (then (call $puts @K:s_active@) (return)))
    (if (i32.eq (local.get $s) (i32.const 2)) (then (call $puts @K:s_done@) (return)))
    (call $puts @K:s_idle@))

  (func $put_hex64 (param $v i64)
    (local $shift i32) (local $d i32) (local $started i32)
    (call $puts @K:hex0x@)
    (if (i64.eqz (local.get $v)) (then (call $putc (i32.const 48)) (return)))
    (local.set $shift (i32.const 60))
    (block $done
      (loop $next
        (br_if $done (i32.lt_s (local.get $shift) (i32.const 0)))
        (local.set $d (i32.and (i32.wrap_i64 (i64.shr_u (local.get $v) (i64.extend_i32_u (local.get $shift)))) (i32.const 15)))
        (if (i32.or (local.get $started) (local.get $d))
          (then
            (local.set $started (i32.const 1))
            (call $putc (select (i32.add (local.get $d) (i32.const 48)) (i32.add (local.get $d) (i32.const 87)) (i32.lt_u (local.get $d) (i32.const 10))))))
        (local.set $shift (i32.sub (local.get $shift) (i32.const 4)))
        (br $next))))

  ;; "0x…" の 16 進を i64 に（2^64 で巻く・Lua の tonumber と同じ）。読めなければ $RD_OK = 0
  (func $parse_hex64 (param $s (ref null $str)) (result i64)
    (local $i i32) (local $n i32) (local $c i32) (local $v i64)
    (global.set $RD_OK (i32.const 0))
    (if (ref.is_null (local.get $s)) (then (return (i64.const 0))))
    (local.set $n (array.len (local.get $s)))
    (if (i32.lt_u (local.get $n) (i32.const 3)) (then (return (i64.const 0))))
    (if (i32.ne (array.get_u $str (local.get $s) (i32.const 0)) (i32.const 48)) (then (return (i64.const 0))))
    (if (i32.ne (i32.or (array.get_u $str (local.get $s) (i32.const 1)) (i32.const 32)) (i32.const 120)) (then (return (i64.const 0))))
    (local.set $i (i32.const 2))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (local.set $c (array.get_u $str (local.get $s) (local.get $i)))
        (if (i32.le_u (i32.sub (local.get $c) (i32.const 48)) (i32.const 9))
          (then (local.set $c (i32.sub (local.get $c) (i32.const 48))))
          (else
            (local.set $c (i32.sub (i32.or (local.get $c) (i32.const 32)) (i32.const 87)))
            (if (i32.gt_u (local.get $c) (i32.const 15)) (then (return (i64.const 0))))))
        (local.set $v (i64.or (i64.shl (local.get $v) (i64.const 4)) (i64.extend_i32_u (local.get $c))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (global.set $RD_OK (i32.const 1))
    (local.get $v))

  ;; resume の読み手（RN / RB / RSTR）。合わなければ $RD_OK = 0（呼び出し側は init の値のまま）
  (func $rd_n (param $v (ref null $J)) (result f64)
    (global.set $RD_OK (i32.eq (call $j_kind (local.get $v)) (i32.const 2)))
    (call $j_num (local.get $v)))
  (func $rd_b (param $v (ref null $J)) (result i32)
    (global.set $RD_OK (i32.eq (call $j_kind (local.get $v)) (i32.const 1)))
    (call $j_is_true (local.get $v)))
  (func $rd_s (param $v (ref null $J)) (result (ref null $str))
    (global.set $RD_OK (i32.eq (call $j_kind (local.get $v)) (i32.const 3)))
    (call $j_str (local.get $v)))
  ;; RREC: table（object か array）か
  (func $rd_rec (param $v (ref null $J)) (result i32)
    (i32.ge_u (call $j_kind (local.get $v)) (i32.const 4)))
  ;; math.tointeger(v) or dflt
  (func $rd_int (param $v (ref null $J)) (param $dflt i32) (result i32)
    (local $f f64)
    (if (i32.ne (call $j_kind (local.get $v)) (i32.const 2)) (then (return (local.get $dflt))))
    (local.set $f (call $j_num (local.get $v)))
    (if (i32.and (f64.eq (local.get $f) (f64.floor (local.get $f))) (f64.lt (f64.abs (local.get $f)) (f64.const 2147483648)))
      (then (return (i32.trunc_f64_s (local.get $f)))))
    (local.get $dflt))

  (func $snapshot
    (local $i i32) (local $d i32)
    (call $puts @K:sn_seed@)
    (call $put_jn (f64.convert_i64_s (global.get $SEED)))
    (call $puts @K:sn_tick@)
    (call $put_jn (f64.convert_i64_s (global.get $TICK)))
    (call $puts @K:sn_seq@)
    (call $put_jn (f64.convert_i32_s (global.get $SEQ)))
    (call $puts @K:sn_rng@)
    (call $putc (i32.const 34))
    (call $put_hex64 (global.get $RS))
    (call $putc (i32.const 34))
    (call $puts @K:sn_done@)
    (call $put_bool (global.get $DONE))
    (call $puts @K:sn_asked@)
    (call $put_jn (f64.convert_i32_s (global.get $ASKED)))
    (call $puts @K:sn_circles@)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (global.get $N)))
        (if (local.get $i) (then (call $putc (i32.const 44))))
        (call $puts @K:sn_name@)
        (call $put_js (call $prog_name (local.get $i)))
        (call $puts @K:sn_status@)
        (call $putc (i32.const 34))
        (call $put_status (call $cst (local.get $i)))
        (call $putc (i32.const 34))
        (call $puts @K:sn_paused@)
        (call $put_bool (call $cget (global.get $CPAUSED) (local.get $i)))
        (call $puts @K:sn_pending@)
        (call $put_bool (call $cget (global.get $CPENDING) (local.get $i)))
        (call $puts @K:sn_cursor@)
        (call $put_jn (f64.convert_i32_s (call $cget (global.get $CCURSOR) (local.get $i))))
        (call $puts @K:sn_published@)
        (call $put_bool (call $cget (global.get $CPUB) (local.get $i)))
        (call $puts @K:sn_delegate@)
        (local.set $d (call $cget (global.get $CDELEG) (local.get $i)))
        (if (i32.lt_s (local.get $d) (i32.const 0))
          (then (call $puts @K:null@))
          (else (call $put_js (call $prog_name (local.get $d)))))
        (call $puts @K:sn_state@)
        (if (call $prog_flow (local.get $i))
          (then (call $puts @K:null@))
          (else (call $prog_dump (local.get $i))))
        (call $puts @K:sn_public@)
        (if (call $prog_flow (local.get $i))
          (then (call $puts @K:null@))
          (else (call $prog_pdump (local.get $i))))
        (call $putc (i32.const 125))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (call $puts @K:sn_end@))

  (func $note_push (param $b (ref null $buf)) (param $name (ref null $str))
    (local $old (ref null $buf))
    (local.set $old (global.get $OUT))
    (global.set $OUT (ref.as_non_null (local.get $b)))
    (if (struct.get $buf 1 (local.get $b)) (then (call $putc (i32.const 44))))
    (call $put_js (local.get $name))
    (global.set $OUT (ref.as_non_null (local.get $old))))

  (func $put_resume_note
    (call $puts @K:rn_mode@)
    (if (i32.eq (global.get $RN_MODE) (i32.const 1))
      (then (call $puts @K:rn_resumed@))
      (else (call $puts @K:rn_fresh@)))
    (call $puts @K:rn_tick@)
    (call $put_jn (f64.convert_i32_s (global.get $RN_TICK)))
    (call $puts @K:rn_kept@)
    (call $put_buf (global.get $RN_KEPT))
    (call $puts @K:rn_dropped@)
    (call $put_buf (global.get $RN_DROPPED))
    (call $puts @K:rn_end@))

  ;; 陣を名前で照合して状態を写す（restore_from）。root が照合できなければ通常の boot に落として 0
  (func $restore_from (param $resume (ref null $J)) (result i32)
    (local $snaps (ref null $J)) (local $k i32) (local $n i32) (local $sc (ref null $J)) (local $name (ref null $str)) (local $i i32)
    (local $status (ref null $str)) (local $d (ref null $str)) (local $di i32) (local $rs i64)
    (call $buf_clear (global.get $RN_KEPT))
    (call $buf_clear (global.get $RN_DROPPED))
    (local.set $snaps (call $j_getk (local.get $resume) @K:k_circles@))
    (local.set $n (call $j_len (local.get $snaps)))   ;; object なら ipairs は空
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $sc (call $j_at (local.get $snaps) (local.get $k)))
        (local.set $name (call $j_str (call $j_getk (local.get $sc) @K:k_name@)))
        (local.set $i (i32.const -1))
        (if (i32.eqz (ref.is_null (local.get $name))) (then (local.set $i (call $prog_find (local.get $name)))))
        ;; 核あり陣の snapshot は state を持ち（空でも {}）、核なし陣は null
        (if (i32.and (i32.ge_s (local.get $i) (i32.const 0))
                     (i32.eq (i32.ne (call $prog_flow (local.get $i)) (i32.const 0))
                             (i32.eqz (call $rd_rec (call $j_getk (local.get $sc) @K:k_state@)))))
          (then
            (local.set $status (call $j_str (call $j_getk (local.get $sc) @K:k_status@)))
            (if (i32.eqz (ref.is_null (local.get $status)))
              (then
                (if (call $str_eq_mem (local.get $status) @K:s_active@) (then (call $cset (global.get $CST) (local.get $i) (i32.const 1))))
                (if (call $str_eq_mem (local.get $status) @K:s_done@) (then (call $cset (global.get $CST) (local.get $i) (i32.const 2))))
                (if (call $str_eq_mem (local.get $status) @K:s_idle@) (then (call $cset (global.get $CST) (local.get $i) (i32.const 0))))))
            (call $cset (global.get $CPAUSED) (local.get $i) (call $j_is_true (call $j_getk (local.get $sc) @K:k_paused@)))
            (call $cset (global.get $CPENDING) (local.get $i) (call $j_is_true (call $j_getk (local.get $sc) @K:k_pending@)))
            (call $cset (global.get $CCURSOR) (local.get $i) (call $rd_int (call $j_getk (local.get $sc) @K:k_cursor@) (i32.const 0)))
            (call $cset (global.get $CPUB) (local.get $i) (call $j_is_true (call $j_getk (local.get $sc) @K:k_published@)))
            (local.set $d (call $j_str (call $j_getk (local.get $sc) @K:k_delegate@)))
            (local.set $di (i32.const -1))
            (if (i32.eqz (ref.is_null (local.get $d))) (then (local.set $di (call $prog_find (local.get $d)))))
            (call $cset (global.get $CDELEG) (local.get $i) (local.get $di))
            (if (i32.lt_s (local.get $di) (i32.const 0))
              (then (call $cset (global.get $CPAUSED) (local.get $i) (i32.const 0)))
              (else
                (if (i32.eqz (call $cst (local.get $di))) (then (call $cset (global.get $CPENDING) (local.get $i) (i32.const 1))))))
            (if (i32.eqz (call $prog_flow (local.get $i)))
              (then
                (call $prog_restore (local.get $i) (call $j_getk (local.get $sc) @K:k_state@))
                (if (call $rd_rec (call $j_getk (local.get $sc) @K:k_public@))
                  (then (call $prog_prestore (local.get $i) (call $j_getk (local.get $sc) @K:k_public@))))))
            (call $note_push (global.get $RN_KEPT) (local.get $name)))
          (else
            (if (i32.eqz (ref.is_null (local.get $name)))
              (then (call $note_push (global.get $RN_DROPPED) (local.get $name))))))
        (local.set $k (i32.add (local.get $k) (i32.const 1)))
        (br $next)))
    (if (i32.eqz (call $cst (global.get $ROOT)))
      (then
        (call $fresh_state)
        (global.set $RN_MODE (i32.const 2))
        (global.set $RN_TICK (i32.const -1))
        (call $buf_clear (global.get $RN_KEPT))
        (return (i32.const 0))))
    (global.set $TICK (i64.extend_i32_s (call $rd_int (call $j_getk (local.get $resume) @K:k_tick@) (i32.const -1))))
    (global.set $SEQ (call $rd_int (call $j_getk (local.get $resume) @K:k_seq@) (i32.const 0)))
    (global.set $ASKED (call $rd_int (call $j_getk (local.get $resume) @K:k_asked@) (i32.const 0)))
    (local.set $rs (call $parse_hex64 (call $j_str (call $j_getk (local.get $resume) @K:k_rng@))))
    (if (global.get $RD_OK) (then (global.set $RS (local.get $rs))))
    (global.set $DONE (call $j_is_true (call $j_getk (local.get $resume) @K:k_done@)))
    (global.set $RN_MODE (i32.const 1))
    (global.set $RN_TICK (i32.wrap_i64 (global.get $TICK)))
    (i32.const 1))

  ;; 復元後の修復: active な flow の idle な子を entered にする
  (func $repair_flows
    (local $i i32) (local $k i32) (local $n i32) (local $cur i32)
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (global.get $N)))
        (if (i32.and (i32.ne (call $prog_flow (local.get $i)) (i32.const 0)) (i32.eq (call $cst (local.get $i)) (i32.const 1)))
          (then
            (local.set $n (call $prog_nchildren (local.get $i)))
            (if (i32.eq (call $prog_flow (local.get $i)) (i32.const 2))
              (then
                (local.set $k (i32.const 0))
                (block $d2
                  (loop $n2
                    (br_if $d2 (i32.ge_u (local.get $k) (local.get $n)))
                    (if (i32.eqz (call $cst (call $prog_child (local.get $i) (local.get $k))))
                      (then (call $enter (call $prog_child (local.get $i) (local.get $k)))))
                    (local.set $k (i32.add (local.get $k) (i32.const 1)))
                    (br $n2))))
              (else
                (if (i32.or (i32.lt_s (call $cget (global.get $CCURSOR) (local.get $i)) (i32.const 1))
                            (i32.gt_s (call $cget (global.get $CCURSOR) (local.get $i)) (local.get $n)))
                  (then (call $cset (global.get $CCURSOR) (local.get $i) (i32.const 1))))
                (local.set $cur (call $prog_child (local.get $i) (i32.sub (call $cget (global.get $CCURSOR) (local.get $i)) (i32.const 1))))
                (if (i32.eqz (call $cst (local.get $cur))) (then (call $enter (local.get $cur))))))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next))))
