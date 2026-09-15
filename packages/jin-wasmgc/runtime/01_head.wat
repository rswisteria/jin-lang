  ;; Jin v2 wasm-GC ランタイム部（docs/spec/v2/jil.md §6.4。プレリュード prelude.lua に相当）。jil: 6
  ;;
  ;; 生成物: `uv run python scripts/generate_runtime_wat.py` が packages/jin-wasmgc/runtime/（部品 *.wat と
  ;; data 区画の文字列表 strings.json）から生成する。**手で編集しない**（正典は部品の側。番地は生成器が振る）。
  ;;
  ;; `jin_wasmgc.assemble` が `(module` の直後にそのまま連結し、その後ろに生成部（<program>）を置く。
  ;; ホストが呼ぶ export は input / boot / tick の 3 つ（jil.md §6.2）。import は無い（module はホストを呼ばない）。
  ;; 引数も戻りも UTF-8 の JSON 1 本を線形メモリで越える: ホストは input(n) が返す番地に JSON を書き、
  ;; boot(n) / tick(n) を呼ぶ。tick は結果の (先頭, 長さ) を多値で返す。boot に結果は無い（核の手順の
  ;; エラーは最初の tick の結果に載る・Lua と同じ）。
  ;;
  ;; 線形メモリの配置（生成部が決める。runtime.wat はグローバル $in_base で受ける）:
  ;;   [0, 2048)                ランタイム部の文字列（下の data。2048 を超えない・codegen.DATA_BASE と 1:1）
  ;;   [2048, $in_base)         生成部の文字列（公開 state の鍵など。式の文字列リテラルは passive の data）
  ;;   [$in_base, +$in_cap)     入力域（input(n) が広げる）
  ;;   [$in_base+$in_cap, …)    出力域（$flush が書く。足りなければ memory.grow）
  ;; 実行時の値は wasm-GC のヒープに置く（jil.md §6.3）: str = (array i8) の UTF-8、list = 要素の表現ごとの
  ;; array を持つ struct、型紙 = struct（$F0 は Pointer）、JSON の読み手の木 = $J。
  ;;
  ;; 生成部が定義するもの（codegen.py と 1:1。ここを変えたら JIL の版を上げる）:
  ;;   (memory (export "memory") <pages>)      data と入力域 + 出力域 64 KiB が入る大きさ
  ;;   (global $in_base i32 (i32.const <N>))   入力域の先頭（生成部の data の直後・16 の倍数）
  ;;   (global $ROOT i32)                       root の陣の添字（0 始まり）
  ;;   (global $N i32)                          陣の数（生存の配列は boot でこの大きさに確保する）
  ;;   (global $FPS f64)                        stage.fps（on tick の dt = 1 / FPS）
  ;;   (global $DEBUG i32)                      トレース行 / snapshot を出すか（デバッグビルド）
  ;;   $prog_flow(i) -> 0 核あり / 1 sequence / 2 parallel / 3 loop、$prog_nchildren(i)、$prog_child(i, k)、$prog_exit(i)
  ;;   $prog_init(i) / $prog_publish(i) / $prog_has_outs(i) / $prog_pub(i)   state の init・確定・公開 state の JSON 断片
  ;;   $prog_core(i)                            核の手順を走らせる（wait を含めば $register_wait まで）
  ;;   $prog_has_on(i, kind) / $prog_on_key(i, k) / $prog_on_pointer(i, k) / $prog_on_tick(i) / $prog_on_exit(i)
  ;;                                            on の配達（kind: 1 key / 2 pointer / 3 tick / 4 exit / 5 message。event 行も生成部が積む）
  ;;   $prog_deliver(site, msg) / $prog_reply(site, id, text)   emit の配達 / v1 の陣の答えの配達（on message へ）
  ;;   $prog_resume(rite, frame) -> 中断したか / $prog_until(uid, frame) -> bool   wait の状態機械の再開と until の評価
  ;;   $prog_name(i) / $prog_find(name) / $prog_guards(i)（assert 行）
  ;;   $prog_dump(i) / $prog_pdump(i) / $prog_restore(i, json) / $prog_prestore(i, json)   snapshot / resume（DEBUG）
  ;; ランタイム部が持つもの: 陣の生存の配列（$CST …）/ $enter / $finish / $transfer / $emit / $ask / $stop / $register_wait /
  ;; $row（トレース行）/ $advance / $deliver / $resume_waits / $dispatch_events / $snapshot / $restore_from
  ;;
  ;; エラー機構（jil.md §6.4）: wasm に例外は使わない。ERR はフラグ $ERRED と $ERRMSG を立て $DONE にする。
  ;; 効果はフラグが立っていたら何もしない・生成部の手順は毎ステップの後と cast の直後にフラグを見て返る・
  ;; tick はフラグが立っていたら publish_all / ADVANCE を飛ばす（プレリュードの pcall の範囲と同じ）。

  ;; ---------------------------------------------------------------- 型（jil.md §6.3）
  (type $str (array (mut i8)))                      ;; UTF-8 のバイト列（作ったら書き換えない）
  (type $lf (array (mut f64)))
  (type $li (array (mut i32)))
  (type $lr (array (mut anyref)))
  (type $Lf (struct (field (mut (ref $lf))) (field (mut i32))))   ;; list<num>: 配列 + 長さ
  (type $Li (struct (field (mut (ref $li))) (field (mut i32))))   ;; list<bool>
  (type $Lr (struct (field (mut (ref $lr))) (field (mut i32))))   ;; list<str> / list<型紙> / list<list>
  (type $buf (struct (field (mut (ref $str))) (field (mut i32))))  ;; 伸びるバイト列（JSON の書き手）
  (type $F0 (struct (field (mut f64)) (field (mut f64)) (field (mut i32))))   ;; 型紙 Pointer {x, y, down}
  ;; JSON の読み手の木: kind（0 null / 1 bool / 2 num / 3 str / 4 array / 5 object）, num, str, keys, vals
  (type $J (struct (field i32) (field f64) (field (ref null $str)) (field (ref null $Lr)) (field (ref null $Lr))))
  (type $bn (array (mut i32)))                      ;; 多倍長（[0] = 桁数、[1..] は 10^9 進の桁・下位から）

  ;; ---------------------------------------------------------------- ランタイム部の文字列（[0, 2048)）
@DATA@

  ;; ---------------------------------------------------------------- 実行時の状態
  (global $in_cap (mut i32) (i32.const 65536))   ;; 入力域の大きさ（input(n) が広げる）
  (global $OUT (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 256)) (i32.const 0)))   ;; 書き手の宛先
  (global $OPS (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 256)) (i32.const 0)))   ;; 表示リスト（JSON 断片）
  (global $AUDIO (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 64)) (i32.const 0)))
  (global $STORE_OUT (mut (ref $buf)) (struct.new $buf (array.new_default $str (i32.const 64)) (i32.const 0)))
  (global $OPS_N (mut i32) (i32.const 0))
  (global $AUDIO_N (mut i32) (i32.const 0))
  (global $STORE_N (mut i32) (i32.const 0))
  (global $DONE (mut i32) (i32.const 0))
  (global $ERRED (mut i32) (i32.const 0))
  (global $ERRMSG (mut (ref null $str)) (ref.null $str))
  (global $BUDGET (mut i32) (i32.const 10000000))   ;; 命令数の上限（jil.md §6.6。boot / tick の先頭で戻す）
  (global $SEED (mut i64) (i64.const 0))
  (global $TICK (mut i64) (i64.const -1))
  (global $first (mut i32) (i32.const 1))        ;; public のコンマ（$pub_comma）
  (global $RS (mut i64) (i64.const 0))           ;; PCG32 の状態
  (global $RI (mut i64) (i64.const 1))
  (global $LAST_DOWN (mut i32) (i32.const 0))    ;; tick を跨いで持つ（prepare_inputs）
  (global $EVENTS (mut (ref null $Lr)) (ref.null $Lr))   ;; この tick の inputs.events（$J の列）
  (global $KEYS (mut (ref null $J)) (ref.null $J))       ;; inputs.keys（object）
  (global $PX (mut f64) (f64.const 0))
  (global $PY (mut f64) (f64.const 0))
  (global $PDOWN (mut i32) (i32.const 0))
  (global $RELX (mut (ref $Lf)) (struct.new $Lf (array.new_default $lf (i32.const 8)) (i32.const 0)))   ;; RELEASES
  (global $RELY (mut (ref $Lf)) (struct.new $Lf (array.new_default $lf (i32.const 8)) (i32.const 0)))
  (global $STORAGE_BASE (mut (ref null $J)) (ref.null $J))   ;; boot の manifest.storage（読むだけ）
  (global $STORE_K (mut (ref $Lr)) (struct.new $Lr (array.new_default $lr (i32.const 8)) (i32.const 0)))   ;; 書き込み（鍵）
  (global $STORE_V (mut (ref $Lr)) (struct.new $Lr (array.new_default $lr (i32.const 8)) (i32.const 0)))   ;; 書き込み（値）
  (global $JP (mut i32) (i32.const 0))           ;; JSON の読み手の位置
  (global $JEND (mut i32) (i32.const 0))
  (global $SD_E (mut i32) (i32.const 0))         ;; $shortest が返す 10 進の指数
  (global $SD_CARRY (mut i32) (i32.const 0))     ;; $round_digits の桁上がり
  (global $DB (mut (ref null $str)) (ref.null $str))   ;; strtod の桁列（10 進の整数）
  (global $DB_E (mut i32) (i32.const 0))         ;; 値 = $DB × 10^$DB_E

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

  ;; 線形メモリの [off, off+len) を str に写す。
  (func $mem_str (param $off i32) (param $len i32) (result (ref $str))
    (local $s (ref null $str)) (local $i i32)
    (local.set $s (array.new_default $str (local.get $len)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $len)))
        (array.set $str (local.get $s) (local.get $i)
          (i32.load8_u (i32.add (local.get $off) (local.get $i))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (ref.as_non_null (local.get $s)))

  ;; ---------------------------------------------------------------- 伸びるバイト列（$buf）と書き手
  (func $buf_new (param $cap i32) (result (ref $buf))
    (struct.new $buf (array.new_default $str (local.get $cap)) (i32.const 0)))

  (func $buf_reserve (param $b (ref null $buf)) (param $extra i32)
    (local $arr (ref null $str)) (local $need i32) (local $cap i32) (local $new (ref null $str))
    (local.set $arr (struct.get $buf 0 (local.get $b)))
    (local.set $need (i32.add (struct.get $buf 1 (local.get $b)) (local.get $extra)))
    (local.set $cap (array.len (local.get $arr)))
    (if (i32.gt_u (local.get $need) (local.get $cap))
      (then
        (local.set $cap (i32.mul (local.get $cap) (i32.const 2)))
        (if (i32.lt_u (local.get $cap) (local.get $need)) (then (local.set $cap (local.get $need))))
        (local.set $new (array.new_default $str (local.get $cap)))
        (array.copy $str $str (local.get $new) (i32.const 0) (local.get $arr) (i32.const 0)
          (struct.get $buf 1 (local.get $b)))
        (struct.set $buf 0 (local.get $b) (ref.as_non_null (local.get $new))))))

  (func $buf_clear (param $b (ref null $buf))
    (struct.set $buf 1 (local.get $b) (i32.const 0)))

  (func $buf_to_str (param $b (ref null $buf)) (result (ref $str))
    (local $s (ref null $str)) (local $n i32)
    (local.set $n (struct.get $buf 1 (local.get $b)))
    (local.set $s (array.new_default $str (local.get $n)))
    (array.copy $str $str (local.get $s) (i32.const 0) (struct.get $buf 0 (local.get $b)) (i32.const 0)
      (local.get $n))
    (ref.as_non_null (local.get $s)))

  ;; 書き手の宛先を新しい buf に切り替え、元の宛先を返す（$fmt_end で戻す）。
  (func $fmt_begin (result (ref $buf))
    (local $old (ref null $buf))
    (local.set $old (global.get $OUT))
    (global.set $OUT (call $buf_new (i32.const 32)))
    (ref.as_non_null (local.get $old)))

  (func $fmt_end (param $old (ref null $buf)) (result (ref $str))
    (local $s (ref null $str))
    (local.set $s (call $buf_to_str (global.get $OUT)))
    (global.set $OUT (ref.as_non_null (local.get $old)))
    (ref.as_non_null (local.get $s)))

  (func $putc (param $c i32)
    (local $b (ref null $buf)) (local $n i32)
    (local.set $b (global.get $OUT))
    (call $buf_reserve (local.get $b) (i32.const 1))
    (local.set $n (struct.get $buf 1 (local.get $b)))
    (array.set $str (struct.get $buf 0 (local.get $b)) (local.get $n) (local.get $c))
    (struct.set $buf 1 (local.get $b) (i32.add (local.get $n) (i32.const 1))))

  ;; data 区画（[0, $in_base)）の文字列を写す。
  (func $puts (param $off i32) (param $len i32)
    (local $b (ref null $buf)) (local $n i32) (local $i i32) (local $arr (ref null $str))
    (local.set $b (global.get $OUT))
    (call $buf_reserve (local.get $b) (local.get $len))
    (local.set $n (struct.get $buf 1 (local.get $b)))
    (local.set $arr (struct.get $buf 0 (local.get $b)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $len)))
        (array.set $str (local.get $arr) (i32.add (local.get $n) (local.get $i))
          (i32.load8_u (i32.add (local.get $off) (local.get $i))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (struct.set $buf 1 (local.get $b) (i32.add (local.get $n) (local.get $len))))

  (func $put_bytes (param $s (ref null $str)) (param $from i32) (param $len i32)
    (local $b (ref null $buf)) (local $n i32)
    (local.set $b (global.get $OUT))
    (call $buf_reserve (local.get $b) (local.get $len))
    (local.set $n (struct.get $buf 1 (local.get $b)))
    (array.copy $str $str (struct.get $buf 0 (local.get $b)) (local.get $n) (local.get $s) (local.get $from)
      (local.get $len))
    (struct.set $buf 1 (local.get $b) (i32.add (local.get $n) (local.get $len))))

  (func $put_str (param $s (ref null $str))
    (call $put_bytes (local.get $s) (i32.const 0) (array.len (local.get $s))))

  (func $put_buf (param $src (ref null $buf))
    (call $put_bytes (struct.get $buf 0 (local.get $src)) (i32.const 0) (struct.get $buf 1 (local.get $src))))

  (func $put_zeros (param $n i32)
    (block $done
      (loop $next
        (br_if $done (i32.le_s (local.get $n) (i32.const 0)))
        (call $putc (i32.const 48))
        (local.set $n (i32.sub (local.get $n) (i32.const 1)))
        (br $next))))

  ;; 宛先の内容を線形メモリの出力域へ写し、(先頭, 長さ) を返す。
  (func $flush (result i32 i32)
    (local $start i32) (local $n i32) (local $i i32) (local $arr (ref null $str))
    (local.set $start (i32.add (global.get $in_base) (global.get $in_cap)))
    (local.set $n (struct.get $buf 1 (global.get $OUT)))
    (local.set $arr (struct.get $buf 0 (global.get $OUT)))
    (call $ensure (i32.add (local.get $start) (local.get $n)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (i32.store8 (i32.add (local.get $start) (local.get $i))
          (array.get_u $str (local.get $arr) (local.get $i)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (local.get $start)
    (local.get $n))

  (func $put_bool (param $b i32)
    (if (local.get $b)
      (then (call $puts @K:true@))
      (else (call $puts @K:false@))))

  (func $put_digits (param $v i64)
    (if (i64.ge_u (local.get $v) (i64.const 10))
      (then (call $put_digits (i64.div_u (local.get $v) (i64.const 10)))))
    (call $putc (i32.add (i32.const 48) (i32.wrap_i64 (i64.rem_u (local.get $v) (i64.const 10))))))

  ;; 10^9 進の 1 桁を 0 詰めの 9 桁で。
  (func $put_digits9 (param $v i32)
    (local $p i32)
    (local.set $p (i32.const 100000000))
    (block $done
      (loop $next
        (br_if $done (i32.eqz (local.get $p)))
        (call $putc (i32.add (i32.const 48) (i32.rem_u (i32.div_u (local.get $v) (local.get $p)) (i32.const 10))))
        (local.set $p (i32.div_u (local.get $p) (i32.const 10)))
        (br $next))))

  (func $hex_digit (param $v i32) (result i32)
    (select (i32.add (i32.const 87) (local.get $v)) (i32.add (i32.const 48) (local.get $v))
      (i32.ge_u (local.get $v) (i32.const 10))))

  ;; JSON の文字列（プレリュードの JS）: " \ と [\0-\31\127] を逃がす（\n \r \t \b \f は名前で、他は \u00xx）。
  (func $put_js (param $s (ref null $str))
    (local $i i32) (local $n i32) (local $c i32)
    (call $putc (i32.const 34))
    (local.set $n (array.len (local.get $s)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (local.set $c (array.get_u $str (local.get $s) (local.get $i)))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (if (i32.or (i32.eq (local.get $c) (i32.const 34)) (i32.eq (local.get $c) (i32.const 92)))
          (then (call $putc (i32.const 92)) (call $putc (local.get $c)) (br $next)))
        (if (i32.or (i32.lt_u (local.get $c) (i32.const 32)) (i32.eq (local.get $c) (i32.const 127)))
          (then
            (if (i32.eq (local.get $c) (i32.const 10)) (then (call $putc (i32.const 92)) (call $putc (i32.const 110)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 13)) (then (call $putc (i32.const 92)) (call $putc (i32.const 114)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 9)) (then (call $putc (i32.const 92)) (call $putc (i32.const 116)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 8)) (then (call $putc (i32.const 92)) (call $putc (i32.const 98)) (br $next)))
            (if (i32.eq (local.get $c) (i32.const 12)) (then (call $putc (i32.const 92)) (call $putc (i32.const 102)) (br $next)))
            (call $puts @K:esc_u@)
            (call $putc (call $hex_digit (i32.shr_u (local.get $c) (i32.const 4))))
            (call $putc (call $hex_digit (i32.and (local.get $c) (i32.const 15))))
            (br $next)))
        (call $putc (local.get $c))
        (br $next)))
    (call $putc (i32.const 34)))

  ;; ---------------------------------------------------------------- 文字列
  (func $str_eq (param $a (ref null $str)) (param $b (ref null $str)) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (array.len (local.get $a)))
    (if (i32.ne (local.get $n) (array.len (local.get $b))) (then (return (i32.const 0))))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (i32.ne (array.get_u $str (local.get $a) (local.get $i))
                    (array.get_u $str (local.get $b) (local.get $i)))
          (then (return (i32.const 0))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 1))

  ;; s（null なら偽）が data 区画の [off, off+len) と同じか。
  (func $str_eq_mem (param $s (ref null $str)) (param $off i32) (param $len i32) (result i32)
    (local $i i32)
    (if (ref.is_null (local.get $s)) (then (return (i32.const 0))))
    (if (i32.ne (array.len (local.get $s)) (local.get $len)) (then (return (i32.const 0))))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $len)))
        (if (i32.ne (array.get_u $str (local.get $s) (local.get $i))
                    (i32.load8_u (i32.add (local.get $off) (local.get $i))))
          (then (return (i32.const 0))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 1))

  (func $str_cat (param $a (ref null $str)) (param $b (ref null $str)) (result (ref $str))
    (local $s (ref null $str)) (local $na i32) (local $nb i32)
    (local.set $na (array.len (local.get $a)))
    (local.set $nb (array.len (local.get $b)))
    (local.set $s (array.new_default $str (i32.add (local.get $na) (local.get $nb))))
    (array.copy $str $str (local.get $s) (i32.const 0) (local.get $a) (i32.const 0) (local.get $na))
    (array.copy $str $str (local.get $s) (local.get $na) (local.get $b) (i32.const 0) (local.get $nb))
    (ref.as_non_null (local.get $s)))

  (func $str_slice (param $s (ref null $str)) (param $from i32) (param $to i32) (result (ref $str))
    (local $r (ref null $str)) (local $n i32)
    (local.set $n (i32.sub (local.get $to) (local.get $from)))
    (local.set $r (array.new_default $str (local.get $n)))
    (array.copy $str $str (local.get $r) (i32.const 0) (local.get $s) (local.get $from) (local.get $n))
    (ref.as_non_null (local.get $r)))

  (func $str_empty (result (ref $str)) (array.new_fixed $str 0))

  ;; コードポイントの数（継続バイト 10xxxxxx を数えない = utf8.len）。
  (func $cp_count (param $s (ref null $str)) (result i32)
    (local $i i32) (local $n i32) (local $k i32)
    (local.set $n (array.len (local.get $s)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (i32.ne (i32.and (array.get_u $str (local.get $s) (local.get $i)) (i32.const 0xC0)) (i32.const 0x80))
          (then (local.set $k (i32.add (local.get $k) (i32.const 1)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (local.get $k))

  ;; k 番目（0 始まり）のコードポイントの先頭バイトの位置（k == 総数なら長さ = utf8.offset(s, k + 1) - 1）。
  (func $cp_offset (param $s (ref null $str)) (param $k i32) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (array.len (local.get $s)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (i32.ne (i32.and (array.get_u $str (local.get $s) (local.get $i)) (i32.const 0xC0)) (i32.const 0x80))
          (then
            (br_if $done (i32.eqz (local.get $k)))
            (local.set $k (i32.sub (local.get $k) (i32.const 1)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (local.get $i))
