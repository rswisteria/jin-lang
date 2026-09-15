  ;; Jin v2 wasm-GC ランタイム部（docs/spec/v2/jil.md §6.4。プレリュード prelude.lua に相当）。jil: 7
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
  (data (i32.const 0) "NaN")  ;; nan 0..3
  (data (i32.const 3) "Infinity")  ;; inf 3..11
  (data (i32.const 11) "true")  ;; true 11..15
  (data (i32.const 15) "false")  ;; false 15..20
  (data (i32.const 20) "null")  ;; null 20..24
  (data (i32.const 24) "{\22ops\22:[")  ;; res_ops 24..32
  (data (i32.const 32) "],\22audio\22:[")  ;; res_audio 32..43
  (data (i32.const 43) ",\22trace\22:[")  ;; res_trace 43..53
  (data (i32.const 53) ",\22done\22:")  ;; res_done 53..61
  (data (i32.const 61) ",\22error\22:")  ;; res_error 61..70
  (data (i32.const 70) ",\22public\22:{")  ;; res_public 70..81
  (data (i32.const 81) ",\22storage\22:[")  ;; res_storage 81..93
  (data (i32.const 93) ",\22asks\22:[")  ;; res_asks 93..102
  (data (i32.const 102) ",\22snapshot\22:")  ;; res_snapshot 102..114
  (data (i32.const 114) ",\22resume\22:")  ;; res_resume 114..124
  (data (i32.const 124) "[\22clear\22,")  ;; op_clear 124..133
  (data (i32.const 133) "[\22ink\22,")  ;; op_ink 133..140
  (data (i32.const 140) "[\22rect\22,")  ;; op_rect 140..148
  (data (i32.const 148) "[\22circle\22,")  ;; op_circle 148..158
  (data (i32.const 158) "[\22line\22,")  ;; op_line 158..166
  (data (i32.const 166) "[\22text\22,")  ;; op_text 166..174
  (data (i32.const 174) "[\22sprite\22,")  ;; op_sprite 174..184
  (data (i32.const 184) "[\22button\22,")  ;; op_button 184..194
  (data (i32.const 194) "[\22label\22,")  ;; op_label 194..203
  (data (i32.const 203) "[\22tone\22,")  ;; op_tone 203..211
  (data (i32.const 211) "[\22play\22,")  ;; op_play 211..219
  (data (i32.const 219) "\5cu00")  ;; esc_u 219..223
  (data (i32.const 223) "\e8\89\b2\e3\81\af \22#rgb\22 \e3\81\8b \22#rrggbb\22 \e3\81\a7\e6\9b\b8\e3\81\8d\e3\81\be\e3\81\99\ef\bc\88")  ;; msg_color 223..269
  (data (i32.const 269) "\ef\bc\89")  ;; msg_close 269..272
  (data (i32.const 272) "\e6\b7\bb\e5\ad\97 ")  ;; msg_index1 272..279
  (data (i32.const 279) " \e3\81\af\e7\af\84\e5\9b\b2\e5\a4\96\e3\81\a7\e3\81\99\ef\bc\88\e9\95\b7\e3\81\95 ")  ;; msg_index2 279..308
  (data (i32.const 308) "\e5\91\bd\e4\bb\a4\e6\95\b0\e3\81\ae\e4\b8\8a\e9\99\90 10000000 \e3\82\92\e8\b6\85\e3\81\88\e3\81\be\e3\81\97\e3\81\9f\ef\bc\88\e7\84\a1\e9\99\90\e3\83\ab\e3\83\bc\e3\83\97\ef\bc\9f\ef\bc\89")  ;; msg_budget 308..378
  (data (i32.const 378) "seed")  ;; k_seed 378..382
  (data (i32.const 382) "manifest")  ;; k_manifest 382..390
  (data (i32.const 390) "storage")  ;; k_storage 390..397
  (data (i32.const 397) "t")  ;; k_t 397..398
  (data (i32.const 398) "inputs")  ;; k_inputs 398..404
  (data (i32.const 404) "events")  ;; k_events 404..410
  (data (i32.const 410) "keys")  ;; k_keys 410..414
  (data (i32.const 414) "pointer")  ;; k_pointer 414..421
  (data (i32.const 421) "x")  ;; k_x 421..422
  (data (i32.const 422) "y")  ;; k_y 422..423
  (data (i32.const 423) "down")  ;; k_down 423..427
  (data (i32.const 427) "kind")  ;; k_kind 427..431
  (data (i32.const 431) "key")  ;; k_key 431..434
  (data (i32.const 434) "text")  ;; k_text 434..438
  (data (i32.const 438) "name")  ;; k_name 438..442
  (data (i32.const 442) "reply")  ;; k_reply 442..447
  (data (i32.const 447) "id")  ;; k_id 447..449
  (data (i32.const 449) "resume")  ;; k_resume 449..455
  (data (i32.const 455) "circles")  ;; k_circles 455..462
  (data (i32.const 462) "state")  ;; k_state 462..467
  (data (i32.const 467) "status")  ;; k_status 467..473
  (data (i32.const 473) "paused")  ;; k_paused 473..479
  (data (i32.const 479) "pending")  ;; k_pending 479..486
  (data (i32.const 486) "cursor")  ;; k_cursor 486..492
  (data (i32.const 492) "published")  ;; k_published 492..501
  (data (i32.const 501) "delegate")  ;; k_delegate 501..509
  (data (i32.const 509) "public")  ;; k_public 509..515
  (data (i32.const 515) "tick")  ;; k_tick 515..519
  (data (i32.const 519) "seq")  ;; k_seq 519..522
  (data (i32.const 522) "asked")  ;; k_asked 522..527
  (data (i32.const 527) "rng")  ;; k_rng 527..530
  (data (i32.const 530) "done")  ;; k_done 530..534
  (data (i32.const 534) "enter")  ;; kd_enter 534..539
  (data (i32.const 539) "exit")  ;; kd_exit 539..543
  (data (i32.const 543) "event")  ;; kd_event 543..548
  (data (i32.const 548) "rite")  ;; kd_rite 548..552
  (data (i32.const 552) "cast")  ;; kd_cast 552..556
  (data (i32.const 556) "set")  ;; kd_set 556..559
  (data (i32.const 559) "emit")  ;; kd_emit 559..563
  (data (i32.const 563) "transfer")  ;; kd_transfer 563..571
  (data (i32.const 571) "wait")  ;; kd_wait 571..575
  (data (i32.const 575) "finish")  ;; kd_finish 575..581
  (data (i32.const 581) "assert")  ;; kd_assert 581..587
  (data (i32.const 587) "error")  ;; kd_error 587..592
  (data (i32.const 592) "frame")  ;; kd_frame 592..597
  (data (i32.const 597) "{\22seq\22:")  ;; r_seq 597..604
  (data (i32.const 604) ",\22tick\22:")  ;; r_tick 604..612
  (data (i32.const 612) ",\22circle\22:")  ;; r_circle 612..622
  (data (i32.const 622) ",\22kind\22:")  ;; r_kind 622..630
  (data (i32.const 630) ",\22name\22:")  ;; r_name 630..638
  (data (i32.const 638) ",\22pointer\22:")  ;; r_pointer 638..649
  (data (i32.const 649) ",\22input\22:")  ;; r_input 649..658
  (data (i32.const 658) ",\22output\22:")  ;; r_output 658..668
  (data (i32.const 668) "/circles/")  ;; p_circles 668..677
  (data (i32.const 677) "/stage")  ;; p_stage 677..683
  (data (i32.const 683) "{\22ops\22:[")  ;; fr_ops 683..691
  (data (i32.const 691) "],\22audio\22:[")  ;; fr_audio 691..702
  (data (i32.const 702) "]}")  ;; fr_end 702..704
  (data (i32.const 704) "{\22ticks\22:")  ;; w_ticks 704..713
  (data (i32.const 713) "{\22ticks\22:0}")  ;; w_ticks0 713..724
  (data (i32.const 724) "{\22until\22:true}")  ;; w_until 724..738
  (data (i32.const 738) "\22suspend\22")  ;; w_suspend 738..747
  (data (i32.const 747) "\22resume\22")  ;; w_resume 747..755
  (data (i32.const 755) "{\22id\22:")  ;; a_id 755..761
  (data (i32.const 761) ",\22circle\22:")  ;; a_circle 761..771
  (data (i32.const 771) ",\22name\22:")  ;; a_name 771..779
  (data (i32.const 779) ",\22prompt\22:")  ;; a_prompt 779..789
  (data (i32.const 789) "idle")  ;; s_idle 789..793
  (data (i32.const 793) "active")  ;; s_active 793..799
  (data (i32.const 799) "done")  ;; s_done 799..803
  (data (i32.const 803) "0x")  ;; hex0x 803..805
  (data (i32.const 805) "{\22seed\22:")  ;; sn_seed 805..813
  (data (i32.const 813) ",\22tick\22:")  ;; sn_tick 813..821
  (data (i32.const 821) ",\22seq\22:")  ;; sn_seq 821..828
  (data (i32.const 828) ",\22rng\22:")  ;; sn_rng 828..835
  (data (i32.const 835) ",\22done\22:")  ;; sn_done 835..843
  (data (i32.const 843) ",\22asked\22:")  ;; sn_asked 843..852
  (data (i32.const 852) ",\22circles\22:[")  ;; sn_circles 852..864
  (data (i32.const 864) "{\22name\22:")  ;; sn_name 864..872
  (data (i32.const 872) ",\22status\22:")  ;; sn_status 872..882
  (data (i32.const 882) ",\22paused\22:")  ;; sn_paused 882..892
  (data (i32.const 892) ",\22pending\22:")  ;; sn_pending 892..903
  (data (i32.const 903) ",\22cursor\22:")  ;; sn_cursor 903..913
  (data (i32.const 913) ",\22published\22:")  ;; sn_published 913..926
  (data (i32.const 926) ",\22delegate\22:")  ;; sn_delegate 926..938
  (data (i32.const 938) ",\22state\22:")  ;; sn_state 938..947
  (data (i32.const 947) ",\22public\22:")  ;; sn_public 947..957
  (data (i32.const 957) "]}")  ;; sn_end 957..959
  (data (i32.const 959) "{\22mode\22:")  ;; rn_mode 959..967
  (data (i32.const 967) "\22resumed\22")  ;; rn_resumed 967..976
  (data (i32.const 976) "\22fresh\22")  ;; rn_fresh 976..983
  (data (i32.const 983) ",\22tick\22:")  ;; rn_tick 983..991
  (data (i32.const 991) ",\22kept\22:[")  ;; rn_kept 991..1000
  (data (i32.const 1000) "],\22dropped\22:[")  ;; rn_dropped 1000..1013
  (data (i32.const 1013) "]}")  ;; rn_end 1013..1015
  (data (i32.const 1015) "transfer \e5\85\88 '")  ;; msg_transfer1 1015..1029
  (data (i32.const 1029) "' \e3\81\af idle \e3\81\a7\e3\81\af\e3\81\82\e3\82\8a\e3\81\be\e3\81\9b\e3\82\93")  ;; msg_transfer2 1029..1061
  (data (i32.const 1061) "1 tick \e3\81\ae\e4\b8\ad\e3\81\a7\e9\99\a3\e3\81\ae\e9\80\b2\e8\a1\8c\e3\81\8c 1000 \e5\9b\9e\e3\82\92\e8\b6\85\e3\81\88\e3\81\be\e3\81\97\e3\81\9f\ef\bc\88exit \e3\81\8c\e5\b8\b8\e3\81\ab\e5\81\bd\e3\81\ae loop \e3\81\aa\e3\81\a9\ef\bc\89")  ;; msg_advance 1061..1157

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
      (then (call $puts (i32.const 11) (i32.const 4)))
      (else (call $puts (i32.const 15) (i32.const 5)))))

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
            (call $puts (i32.const 219) (i32.const 4))
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
      (then (call $mem_str (i32.const 11) (i32.const 4)))
      (else (call $mem_str (i32.const 15) (i32.const 5)))))

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
      (then (call $ERR (call $mem_str (i32.const 308) (i32.const 70))))))

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
    (call $puts (i32.const 272) (i32.const 7))
    (call $put_num (local.get $i))
    (call $puts (i32.const 279) (i32.const 29))
    (call $put_digits (i64.extend_i32_u (local.get $n)))
    (call $puts (i32.const 269) (i32.const 3))
    (call $ERR (call $fmt_end (local.get $old)))
    (i32.const -1))


  ;; list<num>（$Lf）
  (func $lf_new (param $cap i32) (result (ref $Lf))
    (struct.new $Lf (array.new_default $lf (select (local.get $cap) (i32.const 4) (i32.gt_u (local.get $cap) (i32.const 4)))) (i32.const 0)))

  (func $lf_push (param $l (ref null $Lf)) (param $v f64)
    (local $n i32) (local $arr (ref null $lf)) (local $new (ref null $lf))
    (local.set $n (struct.get $Lf 1 (local.get $l)))
    (local.set $arr (struct.get $Lf 0 (local.get $l)))
    (if (i32.eq (local.get $n) (array.len (local.get $arr)))
      (then
        (local.set $new (array.new_default $lf (i32.mul (i32.add (local.get $n) (i32.const 1)) (i32.const 2))))
        (array.copy $lf $lf (local.get $new) (i32.const 0) (local.get $arr) (i32.const 0) (local.get $n))
        (struct.set $Lf 0 (local.get $l) (ref.as_non_null (local.get $new)))
        (local.set $arr (local.get $new))))
    (array.set $lf (local.get $arr) (local.get $n) (local.get $v))
    (struct.set $Lf 1 (local.get $l) (i32.add (local.get $n) (i32.const 1))))

  (func $lf_pushr (param $l (ref null $Lf)) (param $v f64) (result (ref $Lf))
    (call $lf_push (local.get $l) (local.get $v))
    (ref.as_non_null (local.get $l)))

  (func $lf_len (param $l (ref null $Lf)) (result i32) (struct.get $Lf 1 (local.get $l)))

  (func $lf_get (param $l (ref null $Lf)) (param $k i32) (result f64)
    (array.get $lf (struct.get $Lf 0 (local.get $l)) (local.get $k)))

  ;; 範囲外なら ERR して $dflt を返す（$Lr の要素は非 null へ ref.cast されるので null は返せない。生成部が型の既定値を渡す）
  (func $lf_at (param $l (ref null $Lf)) (param $i f64) (param $dflt f64) (result f64)
    (local $k i32)
    (local.set $k (call $index_of (struct.get $Lf 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return (local.get $dflt))))
    (array.get $lf (struct.get $Lf 0 (local.get $l)) (local.get $k)))

  (func $lf_set (param $l (ref null $Lf)) (param $i f64) (param $v f64)
    (local $k i32)
    (local.set $k (call $index_of (struct.get $Lf 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (array.set $lf (struct.get $Lf 0 (local.get $l)) (local.get $k) (local.get $v)))

  (func $e_push_f (param $l (ref null $Lf)) (param $v f64)
    (if (global.get $ERRED) (then (return)))
    (call $lf_push (local.get $l) (local.get $v)))

  (func $e_remove_f (param $l (ref null $Lf)) (param $i f64)
    (local $k i32) (local $n i32) (local $arr (ref null $lf))
    (if (global.get $ERRED) (then (return)))
    (local.set $n (struct.get $Lf 1 (local.get $l)))
    (local.set $k (call $index_of (local.get $n) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (local.set $arr (struct.get $Lf 0 (local.get $l)))
    (array.copy $lf $lf (local.get $arr) (local.get $k) (local.get $arr) (i32.add (local.get $k) (i32.const 1))
      (i32.sub (i32.sub (local.get $n) (local.get $k)) (i32.const 1)))
    (struct.set $Lf 1 (local.get $l) (i32.sub (local.get $n) (i32.const 1))))

  (func $e_clear_f (param $l (ref null $Lf))
    (if (global.get $ERRED) (then (return)))
    (struct.set $Lf 1 (local.get $l) (i32.const 0)))

  (func $f_contains_f (param $l (ref null $Lf)) (param $v f64) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (struct.get $Lf 1 (local.get $l)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (f64.eq (array.get $lf (struct.get $Lf 0 (local.get $l)) (local.get $i)) (local.get $v))
          (then (return (i32.const 1))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $f_len_f (param $l (ref null $Lf)) (result f64)
    (f64.convert_i32_u (struct.get $Lf 1 (local.get $l))))

  ;; list<bool>（$Li）
  (func $li_new (param $cap i32) (result (ref $Li))
    (struct.new $Li (array.new_default $li (select (local.get $cap) (i32.const 4) (i32.gt_u (local.get $cap) (i32.const 4)))) (i32.const 0)))

  (func $li_push (param $l (ref null $Li)) (param $v i32)
    (local $n i32) (local $arr (ref null $li)) (local $new (ref null $li))
    (local.set $n (struct.get $Li 1 (local.get $l)))
    (local.set $arr (struct.get $Li 0 (local.get $l)))
    (if (i32.eq (local.get $n) (array.len (local.get $arr)))
      (then
        (local.set $new (array.new_default $li (i32.mul (i32.add (local.get $n) (i32.const 1)) (i32.const 2))))
        (array.copy $li $li (local.get $new) (i32.const 0) (local.get $arr) (i32.const 0) (local.get $n))
        (struct.set $Li 0 (local.get $l) (ref.as_non_null (local.get $new)))
        (local.set $arr (local.get $new))))
    (array.set $li (local.get $arr) (local.get $n) (local.get $v))
    (struct.set $Li 1 (local.get $l) (i32.add (local.get $n) (i32.const 1))))

  (func $li_pushr (param $l (ref null $Li)) (param $v i32) (result (ref $Li))
    (call $li_push (local.get $l) (local.get $v))
    (ref.as_non_null (local.get $l)))

  (func $li_len (param $l (ref null $Li)) (result i32) (struct.get $Li 1 (local.get $l)))

  (func $li_get (param $l (ref null $Li)) (param $k i32) (result i32)
    (array.get $li (struct.get $Li 0 (local.get $l)) (local.get $k)))

  ;; 範囲外なら ERR して $dflt を返す（$Lr の要素は非 null へ ref.cast されるので null は返せない。生成部が型の既定値を渡す）
  (func $li_at (param $l (ref null $Li)) (param $i f64) (param $dflt i32) (result i32)
    (local $k i32)
    (local.set $k (call $index_of (struct.get $Li 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return (local.get $dflt))))
    (array.get $li (struct.get $Li 0 (local.get $l)) (local.get $k)))

  (func $li_set (param $l (ref null $Li)) (param $i f64) (param $v i32)
    (local $k i32)
    (local.set $k (call $index_of (struct.get $Li 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (array.set $li (struct.get $Li 0 (local.get $l)) (local.get $k) (local.get $v)))

  (func $e_push_i (param $l (ref null $Li)) (param $v i32)
    (if (global.get $ERRED) (then (return)))
    (call $li_push (local.get $l) (local.get $v)))

  (func $e_remove_i (param $l (ref null $Li)) (param $i f64)
    (local $k i32) (local $n i32) (local $arr (ref null $li))
    (if (global.get $ERRED) (then (return)))
    (local.set $n (struct.get $Li 1 (local.get $l)))
    (local.set $k (call $index_of (local.get $n) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (local.set $arr (struct.get $Li 0 (local.get $l)))
    (array.copy $li $li (local.get $arr) (local.get $k) (local.get $arr) (i32.add (local.get $k) (i32.const 1))
      (i32.sub (i32.sub (local.get $n) (local.get $k)) (i32.const 1)))
    (struct.set $Li 1 (local.get $l) (i32.sub (local.get $n) (i32.const 1))))

  (func $e_clear_i (param $l (ref null $Li))
    (if (global.get $ERRED) (then (return)))
    (struct.set $Li 1 (local.get $l) (i32.const 0)))

  (func $f_contains_i (param $l (ref null $Li)) (param $v i32) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (struct.get $Li 1 (local.get $l)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (i32.eq (array.get $li (struct.get $Li 0 (local.get $l)) (local.get $i)) (local.get $v))
          (then (return (i32.const 1))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $f_len_i (param $l (ref null $Li)) (result f64)
    (f64.convert_i32_u (struct.get $Li 1 (local.get $l))))

  ;; list<str / 型紙 / list>（$Lr）
  (func $lr_new (param $cap i32) (result (ref $Lr))
    (struct.new $Lr (array.new_default $lr (select (local.get $cap) (i32.const 4) (i32.gt_u (local.get $cap) (i32.const 4)))) (i32.const 0)))

  (func $lr_push (param $l (ref null $Lr)) (param $v anyref)
    (local $n i32) (local $arr (ref null $lr)) (local $new (ref null $lr))
    (local.set $n (struct.get $Lr 1 (local.get $l)))
    (local.set $arr (struct.get $Lr 0 (local.get $l)))
    (if (i32.eq (local.get $n) (array.len (local.get $arr)))
      (then
        (local.set $new (array.new_default $lr (i32.mul (i32.add (local.get $n) (i32.const 1)) (i32.const 2))))
        (array.copy $lr $lr (local.get $new) (i32.const 0) (local.get $arr) (i32.const 0) (local.get $n))
        (struct.set $Lr 0 (local.get $l) (ref.as_non_null (local.get $new)))
        (local.set $arr (local.get $new))))
    (array.set $lr (local.get $arr) (local.get $n) (local.get $v))
    (struct.set $Lr 1 (local.get $l) (i32.add (local.get $n) (i32.const 1))))

  (func $lr_pushr (param $l (ref null $Lr)) (param $v anyref) (result (ref $Lr))
    (call $lr_push (local.get $l) (local.get $v))
    (ref.as_non_null (local.get $l)))

  (func $lr_len (param $l (ref null $Lr)) (result i32) (struct.get $Lr 1 (local.get $l)))

  (func $lr_get (param $l (ref null $Lr)) (param $k i32) (result anyref)
    (array.get $lr (struct.get $Lr 0 (local.get $l)) (local.get $k)))

  ;; 範囲外なら ERR して $dflt を返す（$Lr の要素は非 null へ ref.cast されるので null は返せない。生成部が型の既定値を渡す）
  (func $lr_at (param $l (ref null $Lr)) (param $i f64) (param $dflt anyref) (result anyref)
    (local $k i32)
    (local.set $k (call $index_of (struct.get $Lr 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return (local.get $dflt))))
    (array.get $lr (struct.get $Lr 0 (local.get $l)) (local.get $k)))

  (func $lr_set (param $l (ref null $Lr)) (param $i f64) (param $v anyref)
    (local $k i32)
    (local.set $k (call $index_of (struct.get $Lr 1 (local.get $l)) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (array.set $lr (struct.get $Lr 0 (local.get $l)) (local.get $k) (local.get $v)))

  (func $e_push_r (param $l (ref null $Lr)) (param $v anyref)
    (if (global.get $ERRED) (then (return)))
    (call $lr_push (local.get $l) (local.get $v)))

  (func $e_remove_r (param $l (ref null $Lr)) (param $i f64)
    (local $k i32) (local $n i32) (local $arr (ref null $lr))
    (if (global.get $ERRED) (then (return)))
    (local.set $n (struct.get $Lr 1 (local.get $l)))
    (local.set $k (call $index_of (local.get $n) (local.get $i)))
    (if (i32.lt_s (local.get $k) (i32.const 0)) (then (return)))
    (local.set $arr (struct.get $Lr 0 (local.get $l)))
    (array.copy $lr $lr (local.get $arr) (local.get $k) (local.get $arr) (i32.add (local.get $k) (i32.const 1))
      (i32.sub (i32.sub (local.get $n) (local.get $k)) (i32.const 1)))
    (struct.set $Lr 1 (local.get $l) (i32.sub (local.get $n) (i32.const 1))))

  (func $e_clear_r (param $l (ref null $Lr))
    (if (global.get $ERRED) (then (return)))
    (struct.set $Lr 1 (local.get $l) (i32.const 0)))

  (func $f_contains_r (param $l (ref null $Lr)) (param $v anyref) (result i32)
    (local $i i32) (local $n i32)
    (local.set $n (struct.get $Lr 1 (local.get $l)))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (if (ref.eq (ref.cast (ref null eq) (array.get $lr (struct.get $Lr 0 (local.get $l)) (local.get $i))) (ref.cast (ref null eq) (local.get $v)))
          (then (return (i32.const 1))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.const 0))

  (func $f_len_r (param $l (ref null $Lr)) (result f64)
    (f64.convert_i32_u (struct.get $Lr 1 (local.get $l))))


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
    (local.set $ev (call $j_getk (local.get $inputs) (i32.const 404) (i32.const 6)))
    (if (i32.eq (call $j_kind (local.get $ev)) (i32.const 4))
      (then (global.set $EVENTS (struct.get $J 4 (local.get $ev))))
      (else (global.set $EVENTS (ref.null $Lr))))
    (global.set $KEYS (call $j_getk (local.get $inputs) (i32.const 410) (i32.const 4)))
    (local.set $p (call $j_getk (local.get $inputs) (i32.const 414) (i32.const 7)))
    (global.set $PX (f64.add (call $j_num (call $j_getk (local.get $p) (i32.const 421) (i32.const 1))) (f64.const 0)))
    (global.set $PY (f64.add (call $j_num (call $j_getk (local.get $p) (i32.const 422) (i32.const 1))) (f64.const 0)))
    (global.set $PDOWN (call $j_truthy (call $j_getk (local.get $p) (i32.const 423) (i32.const 4))))
    (struct.set $Lf 1 (global.get $RELX) (i32.const 0))
    (struct.set $Lf 1 (global.get $RELY) (i32.const 0))
    (local.set $n (call $ev_count))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $ev (call $ev_at (local.get $k)))
        (if (i32.eq (call $ev_kind (local.get $k)) (i32.const 2))
          (then
            (local.set $down (call $j_truthy (call $j_getk (local.get $ev) (i32.const 423) (i32.const 4))))
            (if (i32.and (global.get $LAST_DOWN) (i32.eqz (local.get $down)))
              (then
                (call $lf_push (global.get $RELX) (f64.add (call $j_num (call $j_getk (local.get $ev) (i32.const 421) (i32.const 1))) (f64.const 0)))
                (call $lf_push (global.get $RELY) (f64.add (call $j_num (call $j_getk (local.get $ev) (i32.const 422) (i32.const 1))) (f64.const 0)))))
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
    (local.set $s (call $j_str (call $j_getk (call $ev_at (local.get $k)) (i32.const 427) (i32.const 4))))
    (if (call $str_eq_mem (local.get $s) (i32.const 431) (i32.const 3)) (then (return (i32.const 1))))
    (if (call $str_eq_mem (local.get $s) (i32.const 414) (i32.const 7)) (then (return (i32.const 2))))
    (if (call $str_eq_mem (local.get $s) (i32.const 434) (i32.const 4)) (then (return (i32.const 3))))
    (if (call $str_eq_mem (local.get $s) (i32.const 442) (i32.const 5)) (then (return (i32.const 4))))
    (i32.const 0))

  (func $ev_name (param $k i32) (result (ref $str))
    (local $s (ref null $str))
    (local.set $s (call $j_str (call $j_getk (call $ev_at (local.get $k)) (i32.const 438) (i32.const 4))))
    (if (result (ref $str)) (ref.is_null (local.get $s))
      (then (call $str_empty))
      (else (ref.as_non_null (local.get $s)))))

  (func $ev_down (param $k i32) (result i32)
    (call $j_truthy (call $j_getk (call $ev_at (local.get $k)) (i32.const 423) (i32.const 4))))

  (func $ev_pointer (param $k i32) (result (ref $F0))
    (local $ev (ref null $J))
    (local.set $ev (call $ev_at (local.get $k)))
    (struct.new $F0
      (f64.add (call $j_num (call $j_getk (local.get $ev) (i32.const 421) (i32.const 1))) (f64.const 0))
      (f64.add (call $j_num (call $j_getk (local.get $ev) (i32.const 422) (i32.const 1))) (f64.const 0))
      (call $j_truthy (call $j_getk (local.get $ev) (i32.const 423) (i32.const 4)))))

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
                  (call $j_truthy (call $j_getk (local.get $ev) (i32.const 423) (i32.const 4))))
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
            (local.set $s (call $j_str (call $j_getk (call $ev_at (local.get $k)) (i32.const 434) (i32.const 4))))
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
    (call $puts (i32.const 223) (i32.const 46))
    (call $put_str (local.get $color))
    (call $puts (i32.const 269) (i32.const 3))
    (call $ERR (call $fmt_end (local.get $old)))
    (i32.const 0))

  (func $h_canvas_clear (param $color (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (if (i32.eqz (call $check_color (local.get $color))) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 124) (i32.const 9))
    (call $put_js (local.get $color))
    (call $out_close (local.get $old)))

  (func $h_canvas_ink (param $color (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (if (i32.eqz (call $check_color (local.get $color))) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 133) (i32.const 7))
    (call $put_js (local.get $color))
    (call $out_close (local.get $old)))

  (func $h_canvas_rect (param $x f64) (param $y f64) (param $w f64) (param $h f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 140) (i32.const 8))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y)) (call $putc (i32.const 44))
    (call $put_jn (local.get $w)) (call $putc (i32.const 44))
    (call $put_jn (local.get $h))
    (call $out_close (local.get $old)))

  (func $h_canvas_circle (param $x f64) (param $y f64) (param $r f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 148) (i32.const 10))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y)) (call $putc (i32.const 44))
    (call $put_jn (local.get $r))
    (call $out_close (local.get $old)))

  (func $h_canvas_line (param $x1 f64) (param $y1 f64) (param $x2 f64) (param $y2 f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 158) (i32.const 8))
    (call $put_jn (local.get $x1)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y1)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x2)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y2))
    (call $out_close (local.get $old)))

  (func $h_canvas_text (param $s (ref null $str)) (param $x f64) (param $y f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 166) (i32.const 8))
    (call $put_js (local.get $s)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y))
    (call $out_close (local.get $old)))

  (func $h_canvas_sprite (param $name (ref null $str)) (param $x f64) (param $y f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 174) (i32.const 10))
    (call $put_js (local.get $name)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y))
    (call $out_close (local.get $old)))

  ;; ui.button: op を積み、この tick に矩形の中（境界を含む）で主ボタンが離されていれば真
  (func $h_ui_button (param $label (ref null $str)) (param $x f64) (param $y f64) (param $w f64) (param $h f64) (result i32)
    (local $old (ref null $buf)) (local $k i32) (local $n i32) (local $rx f64) (local $ry f64)
    (if (global.get $ERRED) (then (return (i32.const 0))))
    (local.set $old (call $ops_open))
    (call $puts (i32.const 184) (i32.const 10))
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
    (call $puts (i32.const 194) (i32.const 9))
    (call $put_js (local.get $s)) (call $putc (i32.const 44))
    (call $put_jn (local.get $x)) (call $putc (i32.const 44))
    (call $put_jn (local.get $y))
    (call $out_close (local.get $old)))

  (func $h_audio_tone (param $hz f64) (param $ms f64)
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $audio_open))
    (call $puts (i32.const 203) (i32.const 8))
    (call $put_jn (local.get $hz)) (call $putc (i32.const 44))
    (call $put_jn (local.get $ms))
    (call $out_close (local.get $old)))

  (func $h_audio_play (param $name (ref null $str))
    (local $old (ref null $buf))
    (if (global.get $ERRED) (then (return)))
    (local.set $old (call $audio_open))
    (call $puts (i32.const 211) (i32.const 8))
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
    (call $puts (i32.const 24) (i32.const 8))
    (call $put_buf (global.get $OPS))
    (call $puts (i32.const 32) (i32.const 11))
    (call $put_buf (global.get $AUDIO))
    (call $putc (i32.const 93))
    (if (global.get $DEBUG)
      (then
        (call $puts (i32.const 43) (i32.const 10))
        (call $put_trace)
        (call $putc (i32.const 93))))
    (call $puts (i32.const 53) (i32.const 8))
    (call $put_bool (global.get $DONE))
    (call $puts (i32.const 61) (i32.const 9))
    (if (ref.is_null (global.get $ERRMSG))
      (then (call $puts (i32.const 20) (i32.const 4)))
      (else (call $put_js (global.get $ERRMSG))))
    (call $puts (i32.const 70) (i32.const 11))
    (global.set $first (i32.const 1))
    (call $pub_all)
    (call $putc (i32.const 125))
    (if (global.get $STORE_N)
      (then
        (call $puts (i32.const 81) (i32.const 12))
        (call $put_buf (global.get $STORE_OUT))
        (call $putc (i32.const 93))))
    (if (global.get $ASKS_N)
      (then
        (call $puts (i32.const 93) (i32.const 9))
        (call $put_buf (global.get $ASKS))
        (call $putc (i32.const 93))))
    (if (global.get $DEBUG)
      (then
        (call $puts (i32.const 102) (i32.const 12))
        (call $snapshot)
        (if (global.get $RN_MODE)
          (then
            (call $puts (i32.const 114) (i32.const 10))
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
    (local.set $manifest (call $j_getk (local.get $root) (i32.const 382) (i32.const 8)))
    (global.set $STORAGE_BASE (call $j_getk (local.get $manifest) (i32.const 390) (i32.const 7)))
    ;; 状態を保った差し替え: manifest.resume が table（object / array）なら名前で照合して写す（runtime.md §1.3）
    (local.set $resume (call $j_getk (local.get $manifest) (i32.const 449) (i32.const 6)))
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
    (local.set $seed (call $j_getk (local.get $root) (i32.const 378) (i32.const 4)))
    (if (i32.eqz (ref.is_null (local.get $resume)))
      (then
        (if (i32.and (i32.eq (call $j_kind (call $j_getk (local.get $resume) (i32.const 378) (i32.const 4))) (i32.const 2))
                     (f64.eq (call $j_num (call $j_getk (local.get $resume) (i32.const 378) (i32.const 4))) (f64.floor (call $j_num (call $j_getk (local.get $resume) (i32.const 378) (i32.const 4))))))
          (then (local.set $seed (call $j_getk (local.get $resume) (i32.const 378) (i32.const 4)))))))
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
        (global.set $TICK (i64.trunc_sat_f64_s (call $j_num (call $j_getk (local.get $root) (i32.const 397) (i32.const 1)))))
        (call $prepare_inputs (call $j_getk (local.get $root) (i32.const 398) (i32.const 6)))
        (call $step)
        (call $error_row)
        (if (global.get $DEBUG)
          (then
            (local.set $old (call $fmt_begin))
            (call $puts (i32.const 683) (i32.const 8))
            (call $put_buf (global.get $OPS))
            (call $puts (i32.const 691) (i32.const 11))
            (call $put_buf (global.get $AUDIO))
            (call $puts (i32.const 702) (i32.const 2))
            (drop (call $row (i32.const 12) (i32.const -1) (ref.null $str) (call $mem_str (i32.const 677) (i32.const 6)) (ref.null $str)
              (call $fmt_end (local.get $old))))))))
    (call $result)
    (local.set $len)
    (local.set $ptr)
    (call $after_result)
    (local.get $ptr)
    (local.get $len))



  ;; ---------------------------------------------------------------- sin / cos / atan2（fdlibm の移植）
  ;; wasm に三角関数は無い。fdlibm（Sun の e_rem_pio2 / k_sin / k_cos / s_atan / e_atan2）を写す。
  ;; Lua 経路は C ライブラリ（glibc は正しい丸め）なので最後の bit は保証しない（1 ulp 以内・jil.md §6.4）。
  ;; 引数の還元は |x| < 2^19·π/2 まで fdlibm と同じ 3 段の Cody-Waite。それより大きい |x| は同じ式を
  ;; そのまま使うので精度が落ちる（Payne-Hanek は移植していない・既知の差）。
  (global $RP_Y0 (mut f64) (f64.const 0))
  (global $RP_Y1 (mut f64) (f64.const 0))

  (func $hi (param $x f64) (result i32)
    (i32.wrap_i64 (i64.shr_u (i64.reinterpret_f64 (local.get $x)) (i64.const 32))))
  (func $lo (param $x f64) (result i32)
    (i32.wrap_i64 (i64.reinterpret_f64 (local.get $x))))
  (func $from_hi (param $hi i32) (result f64)
    (f64.reinterpret_i64 (i64.shl (i64.extend_i32_u (local.get $hi)) (i64.const 32))))

  ;; __kernel_sin(x, y, iy): |x| ≤ π/4、x + y が引数（y は下位）
  (func $k_sin (param $x f64) (param $y f64) (param $iy i32) (result f64)
    (local $z f64) (local $v f64) (local $r f64)
    (if (i32.lt_u (i32.and (call $hi (local.get $x)) (i32.const 0x7fffffff)) (i32.const 0x3e400000))
      (then (return (local.get $x))))
    (local.set $z (f64.mul (local.get $x) (local.get $x)))
    (local.set $v (f64.mul (local.get $z) (local.get $x)))
    (local.set $r
      (f64.add (f64.const 8.33333333332248946124e-03)
        (f64.mul (local.get $z)
          (f64.add (f64.const -1.98412698298579493134e-04)
            (f64.mul (local.get $z)
              (f64.add (f64.const 2.75573137070700676789e-06)
                (f64.mul (local.get $z)
                  (f64.add (f64.const -2.50507602534068634195e-08)
                    (f64.mul (local.get $z) (f64.const 1.58969099521155010221e-10))))))))))
    (if (i32.eqz (local.get $iy))
      (then
        (return (f64.add (local.get $x)
          (f64.mul (local.get $v) (f64.add (f64.const -1.66666666666666324348e-01) (f64.mul (local.get $z) (local.get $r))))))))
    (f64.sub (local.get $x)
      (f64.sub
        (f64.sub
          (f64.mul (local.get $z)
            (f64.sub (f64.mul (f64.const 0.5) (local.get $y)) (f64.mul (local.get $v) (local.get $r))))
          (local.get $y))
        (f64.mul (local.get $v) (f64.const -1.66666666666666324348e-01)))))

  ;; __kernel_cos(x, y)
  (func $k_cos (param $x f64) (param $y f64) (result f64)
    (local $ix i32) (local $z f64) (local $r f64) (local $qx f64) (local $hz f64) (local $a f64)
    (local.set $ix (i32.and (call $hi (local.get $x)) (i32.const 0x7fffffff)))
    (if (i32.lt_u (local.get $ix) (i32.const 0x3e400000)) (then (return (f64.const 1))))
    (local.set $z (f64.mul (local.get $x) (local.get $x)))
    (local.set $r
      (f64.mul (local.get $z)
        (f64.add (f64.const 4.16666666666666019037e-02)
          (f64.mul (local.get $z)
            (f64.add (f64.const -1.38888888888741095749e-03)
              (f64.mul (local.get $z)
                (f64.add (f64.const 2.48015872894767294178e-05)
                  (f64.mul (local.get $z)
                    (f64.add (f64.const -2.75573143513906633035e-07)
                      (f64.mul (local.get $z)
                        (f64.add (f64.const 2.08757232129817482790e-09)
                          (f64.mul (local.get $z) (f64.const -1.13596475577881948265e-11)))))))))))))
    (if (i32.lt_u (local.get $ix) (i32.const 0x3FD33333))
      (then
        (return (f64.sub (f64.const 1)
          (f64.sub (f64.mul (f64.const 0.5) (local.get $z))
            (f64.sub (f64.mul (local.get $z) (local.get $r)) (f64.mul (local.get $x) (local.get $y))))))))
    (if (i32.gt_u (local.get $ix) (i32.const 0x3fe90000))
      (then (local.set $qx (f64.const 0.28125)))
      (else (local.set $qx (call $from_hi (i32.sub (local.get $ix) (i32.const 0x00200000))))))
    (local.set $hz (f64.sub (f64.mul (f64.const 0.5) (local.get $z)) (local.get $qx)))
    (local.set $a (f64.sub (f64.const 1) (local.get $qx)))
    (f64.sub (local.get $a)
      (f64.sub (local.get $hz)
        (f64.sub (f64.mul (local.get $z) (local.get $r)) (f64.mul (local.get $x) (local.get $y))))))

  ;; __ieee754_rem_pio2(x): x = n·π/2 + (y0 + y1)。n を返し y0 / y1 は $RP_Y0 / $RP_Y1 に置く。
  (func $rem_pio2 (param $x f64) (result i32)
    (local $hx i32) (local $ix i32) (local $z f64) (local $t f64) (local $n i64) (local $fn f64)
    (local $r f64) (local $w f64) (local $y0 f64) (local $j i32) (local $i i32)
    (local.set $hx (call $hi (local.get $x)))
    (local.set $ix (i32.and (local.get $hx) (i32.const 0x7fffffff)))
    (if (i32.le_u (local.get $ix) (i32.const 0x3fe921fb))
      (then (global.set $RP_Y0 (local.get $x)) (global.set $RP_Y1 (f64.const 0)) (return (i32.const 0))))
    (if (i32.lt_u (local.get $ix) (i32.const 0x4002d97c))
      (then
        (if (i32.gt_s (local.get $hx) (i32.const 0))
          (then
            (local.set $z (f64.sub (local.get $x) (f64.const 1.57079632673412561417e+00)))
            (if (i32.ne (local.get $ix) (i32.const 0x3ff921fb))
              (then
                (global.set $RP_Y0 (f64.sub (local.get $z) (f64.const 6.07710050650619224932e-11)))
                (global.set $RP_Y1 (f64.sub (f64.sub (local.get $z) (global.get $RP_Y0)) (f64.const 6.07710050650619224932e-11))))
              (else
                (local.set $z (f64.sub (local.get $z) (f64.const 6.07710050630396597660e-11)))
                (global.set $RP_Y0 (f64.sub (local.get $z) (f64.const 2.02226624879595063154e-21)))
                (global.set $RP_Y1 (f64.sub (f64.sub (local.get $z) (global.get $RP_Y0)) (f64.const 2.02226624879595063154e-21)))))
            (return (i32.const 1)))
          (else
            (local.set $z (f64.add (local.get $x) (f64.const 1.57079632673412561417e+00)))
            (if (i32.ne (local.get $ix) (i32.const 0x3ff921fb))
              (then
                (global.set $RP_Y0 (f64.add (local.get $z) (f64.const 6.07710050650619224932e-11)))
                (global.set $RP_Y1 (f64.add (f64.sub (local.get $z) (global.get $RP_Y0)) (f64.const 6.07710050650619224932e-11))))
              (else
                (local.set $z (f64.add (local.get $z) (f64.const 6.07710050630396597660e-11)))
                (global.set $RP_Y0 (f64.add (local.get $z) (f64.const 2.02226624879595063154e-21)))
                (global.set $RP_Y1 (f64.add (f64.sub (local.get $z) (global.get $RP_Y0)) (f64.const 2.02226624879595063154e-21)))))
            (return (i32.const -1))))))
    (if (i32.ge_u (local.get $ix) (i32.const 0x7ff00000))
      (then
        (global.set $RP_Y0 (f64.sub (local.get $x) (local.get $x)))
        (global.set $RP_Y1 (global.get $RP_Y0))
        (return (i32.const 0))))
    ;; 中くらいの引数（|x| < 2^19·π/2 では fdlibm と同じ。それ以上は同じ式を流用・精度は落ちる）
    (local.set $t (f64.abs (local.get $x)))
    (local.set $n (i64.trunc_sat_f64_s (f64.add (f64.mul (local.get $t) (f64.const 6.36619772367581382433e-01)) (f64.const 0.5))))
    (local.set $fn (f64.convert_i64_s (local.get $n)))
    (local.set $r (f64.sub (local.get $t) (f64.mul (local.get $fn) (f64.const 1.57079632673412561417e+00))))
    (local.set $w (f64.mul (local.get $fn) (f64.const 6.07710050650619224932e-11)))
    (local.set $j (i32.shr_u (local.get $ix) (i32.const 20)))
    (local.set $y0 (f64.sub (local.get $r) (local.get $w)))
    (local.set $i (i32.sub (local.get $j) (i32.and (i32.shr_u (call $hi (local.get $y0)) (i32.const 20)) (i32.const 0x7ff))))
    (if (i32.gt_s (local.get $i) (i32.const 16))
      (then
        (local.set $t (local.get $r))
        (local.set $w (f64.mul (local.get $fn) (f64.const 6.07710050630396597660e-11)))
        (local.set $r (f64.sub (local.get $t) (local.get $w)))
        (local.set $w (f64.sub (f64.mul (local.get $fn) (f64.const 2.02226624879595063154e-21))
          (f64.sub (f64.sub (local.get $t) (local.get $r)) (local.get $w))))
        (local.set $y0 (f64.sub (local.get $r) (local.get $w)))
        (local.set $i (i32.sub (local.get $j) (i32.and (i32.shr_u (call $hi (local.get $y0)) (i32.const 20)) (i32.const 0x7ff))))
        (if (i32.gt_s (local.get $i) (i32.const 49))
          (then
            (local.set $t (local.get $r))
            (local.set $w (f64.mul (local.get $fn) (f64.const 2.02226624871116645580e-21)))
            (local.set $r (f64.sub (local.get $t) (local.get $w)))
            (local.set $w (f64.sub (f64.mul (local.get $fn) (f64.const 8.47842766036889956997e-32))
              (f64.sub (f64.sub (local.get $t) (local.get $r)) (local.get $w))))
            (local.set $y0 (f64.sub (local.get $r) (local.get $w)))))))
    (global.set $RP_Y0 (local.get $y0))
    (global.set $RP_Y1 (f64.sub (f64.sub (local.get $r) (local.get $y0)) (local.get $w)))
    (if (i32.lt_s (local.get $hx) (i32.const 0))
      (then
        (global.set $RP_Y0 (f64.neg (global.get $RP_Y0)))
        (global.set $RP_Y1 (f64.neg (global.get $RP_Y1)))
        (return (i32.wrap_i64 (i64.sub (i64.const 0) (local.get $n))))))
    (i32.wrap_i64 (local.get $n)))

  (func $f_sin (param $x f64) (result f64)
    (local $ix i32) (local $n i32)
    (local.set $ix (i32.and (call $hi (local.get $x)) (i32.const 0x7fffffff)))
    (if (i32.le_u (local.get $ix) (i32.const 0x3fe921fb))
      (then (return (call $k_sin (local.get $x) (f64.const 0) (i32.const 0)))))
    (if (i32.ge_u (local.get $ix) (i32.const 0x7ff00000))
      (then (return (f64.sub (local.get $x) (local.get $x)))))
    (local.set $n (i32.and (call $rem_pio2 (local.get $x)) (i32.const 3)))
    (if (i32.eq (local.get $n) (i32.const 0)) (then (return (call $k_sin (global.get $RP_Y0) (global.get $RP_Y1) (i32.const 1)))))
    (if (i32.eq (local.get $n) (i32.const 1)) (then (return (call $k_cos (global.get $RP_Y0) (global.get $RP_Y1)))))
    (if (i32.eq (local.get $n) (i32.const 2)) (then (return (f64.neg (call $k_sin (global.get $RP_Y0) (global.get $RP_Y1) (i32.const 1))))))
    (f64.neg (call $k_cos (global.get $RP_Y0) (global.get $RP_Y1))))

  (func $f_cos (param $x f64) (result f64)
    (local $ix i32) (local $n i32)
    (local.set $ix (i32.and (call $hi (local.get $x)) (i32.const 0x7fffffff)))
    (if (i32.le_u (local.get $ix) (i32.const 0x3fe921fb))
      (then (return (call $k_cos (local.get $x) (f64.const 0)))))
    (if (i32.ge_u (local.get $ix) (i32.const 0x7ff00000))
      (then (return (f64.sub (local.get $x) (local.get $x)))))
    (local.set $n (i32.and (call $rem_pio2 (local.get $x)) (i32.const 3)))
    (if (i32.eq (local.get $n) (i32.const 0)) (then (return (call $k_cos (global.get $RP_Y0) (global.get $RP_Y1)))))
    (if (i32.eq (local.get $n) (i32.const 1)) (then (return (f64.neg (call $k_sin (global.get $RP_Y0) (global.get $RP_Y1) (i32.const 1))))))
    (if (i32.eq (local.get $n) (i32.const 2)) (then (return (f64.neg (call $k_cos (global.get $RP_Y0) (global.get $RP_Y1))))))
    (call $k_sin (global.get $RP_Y0) (global.get $RP_Y1) (i32.const 1)))

  ;; s_atan.c
  (func $atan_hi (param $id i32) (result f64)
    (if (i32.eq (local.get $id) (i32.const 0)) (then (return (f64.const 4.63647609000806093515e-01))))
    (if (i32.eq (local.get $id) (i32.const 1)) (then (return (f64.const 7.85398163397448278999e-01))))
    (if (i32.eq (local.get $id) (i32.const 2)) (then (return (f64.const 9.82793723247329054082e-01))))
    (f64.const 1.57079632679489655800e+00))
  (func $atan_lo (param $id i32) (result f64)
    (if (i32.eq (local.get $id) (i32.const 0)) (then (return (f64.const 2.26987774529616870924e-17))))
    (if (i32.eq (local.get $id) (i32.const 1)) (then (return (f64.const 3.06161699786838301793e-17))))
    (if (i32.eq (local.get $id) (i32.const 2)) (then (return (f64.const 1.39033110312309984516e-17))))
    (f64.const 6.12323399573676603587e-17))

  (func $atan (param $x f64) (result f64)
    (local $hx i32) (local $ix i32) (local $id i32) (local $z f64) (local $w f64) (local $s1 f64) (local $s2 f64)
    (local.set $hx (call $hi (local.get $x)))
    (local.set $ix (i32.and (local.get $hx) (i32.const 0x7fffffff)))
    (if (i32.ge_u (local.get $ix) (i32.const 0x44100000))
      (then
        (if (i32.or (i32.gt_u (local.get $ix) (i32.const 0x7ff00000))
                    (i32.and (i32.eq (local.get $ix) (i32.const 0x7ff00000)) (i32.ne (call $lo (local.get $x)) (i32.const 0))))
          (then (return (f64.add (local.get $x) (local.get $x)))))
        (if (i32.gt_s (local.get $hx) (i32.const 0))
          (then (return (f64.add (f64.const 1.57079632679489655800e+00) (f64.const 6.12323399573676603587e-17)))))
        (return (f64.sub (f64.const -1.57079632679489655800e+00) (f64.const 6.12323399573676603587e-17)))))
    (local.set $id (i32.const -1))
    (if (i32.lt_u (local.get $ix) (i32.const 0x3fdc0000))
      (then
        (if (i32.lt_u (local.get $ix) (i32.const 0x3e200000)) (then (return (local.get $x)))))
      (else
        (local.set $x (f64.abs (local.get $x)))
        (if (i32.lt_u (local.get $ix) (i32.const 0x3ff30000))
          (then
            (if (i32.lt_u (local.get $ix) (i32.const 0x3fe60000))
              (then
                (local.set $id (i32.const 0))
                (local.set $x (f64.div (f64.sub (f64.mul (f64.const 2) (local.get $x)) (f64.const 1)) (f64.add (f64.const 2) (local.get $x)))))
              (else
                (local.set $id (i32.const 1))
                (local.set $x (f64.div (f64.sub (local.get $x) (f64.const 1)) (f64.add (local.get $x) (f64.const 1)))))))
          (else
            (if (i32.lt_u (local.get $ix) (i32.const 0x40038000))
              (then
                (local.set $id (i32.const 2))
                (local.set $x (f64.div (f64.sub (local.get $x) (f64.const 1.5)) (f64.add (f64.const 1) (f64.mul (f64.const 1.5) (local.get $x))))))
              (else
                (local.set $id (i32.const 3))
                (local.set $x (f64.div (f64.const -1) (local.get $x)))))))))
    (local.set $z (f64.mul (local.get $x) (local.get $x)))
    (local.set $w (f64.mul (local.get $z) (local.get $z)))
    (local.set $s1
      (f64.mul (local.get $z)
        (f64.add (f64.const 3.33333333333329318027e-01)
          (f64.mul (local.get $w)
            (f64.add (f64.const 1.42857142725034663711e-01)
              (f64.mul (local.get $w)
                (f64.add (f64.const 9.09088713343650656196e-02)
                  (f64.mul (local.get $w)
                    (f64.add (f64.const 6.66107313738753120669e-02)
                      (f64.mul (local.get $w)
                        (f64.add (f64.const 4.97687799461593236017e-02)
                          (f64.mul (local.get $w) (f64.const 1.62858201153657823623e-02)))))))))))))
    (local.set $s2
      (f64.mul (local.get $w)
        (f64.add (f64.const -1.99999999998764832476e-01)
          (f64.mul (local.get $w)
            (f64.add (f64.const -1.11111104054623557880e-01)
              (f64.mul (local.get $w)
                (f64.add (f64.const -7.69187620504482999495e-02)
                  (f64.mul (local.get $w)
                    (f64.add (f64.const -5.83357013379057348645e-02)
                      (f64.mul (local.get $w) (f64.const -3.65315727442169155270e-02)))))))))))
    (if (i32.lt_s (local.get $id) (i32.const 0))
      (then (return (f64.sub (local.get $x) (f64.mul (local.get $x) (f64.add (local.get $s1) (local.get $s2)))))))
    (local.set $z
      (f64.sub (call $atan_hi (local.get $id))
        (f64.sub
          (f64.sub (f64.mul (local.get $x) (f64.add (local.get $s1) (local.get $s2))) (call $atan_lo (local.get $id)))
          (local.get $x))))
    (if (result f64) (i32.lt_s (local.get $hx) (i32.const 0)) (then (f64.neg (local.get $z))) (else (local.get $z))))

  ;; e_atan2.c: atan2(y, x)
  (func $f_atan2 (param $y f64) (param $x f64) (result f64)
    (local $hx i32) (local $ix i32) (local $lx i32) (local $hy i32) (local $iy i32) (local $ly i32) (local $m i32)
    (local $k i32) (local $z f64)
    (local.set $hx (call $hi (local.get $x)))
    (local.set $ix (i32.and (local.get $hx) (i32.const 0x7fffffff)))
    (local.set $lx (call $lo (local.get $x)))
    (local.set $hy (call $hi (local.get $y)))
    (local.set $iy (i32.and (local.get $hy) (i32.const 0x7fffffff)))
    (local.set $ly (call $lo (local.get $y)))
    (if (i32.or (f64.ne (local.get $x) (local.get $x)) (f64.ne (local.get $y) (local.get $y)))
      (then (return (f64.add (local.get $x) (local.get $y)))))
    (if (f64.eq (local.get $x) (f64.const 1)) (then (return (call $atan (local.get $y)))))
    (local.set $m (i32.or (i32.and (i32.shr_u (local.get $hy) (i32.const 31)) (i32.const 1))
                          (i32.and (i32.shr_u (local.get $hx) (i32.const 30)) (i32.const 2))))
    (if (i32.eqz (i32.or (local.get $iy) (local.get $ly)))
      (then
        (if (i32.lt_u (local.get $m) (i32.const 2)) (then (return (local.get $y))))
        (if (i32.eq (local.get $m) (i32.const 2)) (then (return (f64.add (f64.const 3.1415926535897931160e+00) (f64.const 1.0e-300)))))
        (return (f64.sub (f64.const -3.1415926535897931160e+00) (f64.const 1.0e-300)))))
    (if (i32.eqz (i32.or (local.get $ix) (local.get $lx)))
      (then
        (if (i32.lt_s (local.get $hy) (i32.const 0))
          (then (return (f64.sub (f64.const -1.5707963267948965580e+00) (f64.const 1.0e-300)))))
        (return (f64.add (f64.const 1.5707963267948965580e+00) (f64.const 1.0e-300)))))
    (if (i32.eq (local.get $ix) (i32.const 0x7ff00000))
      (then
        (if (i32.eq (local.get $iy) (i32.const 0x7ff00000))
          (then
            (if (i32.eq (local.get $m) (i32.const 0)) (then (return (f64.add (f64.const 7.8539816339744827900e-01) (f64.const 1.0e-300)))))
            (if (i32.eq (local.get $m) (i32.const 1)) (then (return (f64.sub (f64.const -7.8539816339744827900e-01) (f64.const 1.0e-300)))))
            (if (i32.eq (local.get $m) (i32.const 2)) (then (return (f64.add (f64.mul (f64.const 3) (f64.const 7.8539816339744827900e-01)) (f64.const 1.0e-300)))))
            (return (f64.sub (f64.mul (f64.const -3) (f64.const 7.8539816339744827900e-01)) (f64.const 1.0e-300))))
          (else
            (if (i32.eq (local.get $m) (i32.const 0)) (then (return (f64.const 0))))
            (if (i32.eq (local.get $m) (i32.const 1)) (then (return (f64.const -0))))
            (if (i32.eq (local.get $m) (i32.const 2)) (then (return (f64.add (f64.const 3.1415926535897931160e+00) (f64.const 1.0e-300)))))
            (return (f64.sub (f64.const -3.1415926535897931160e+00) (f64.const 1.0e-300)))))))
    (if (i32.eq (local.get $iy) (i32.const 0x7ff00000))
      (then
        (if (i32.lt_s (local.get $hy) (i32.const 0))
          (then (return (f64.sub (f64.const -1.5707963267948965580e+00) (f64.const 1.0e-300)))))
        (return (f64.add (f64.const 1.5707963267948965580e+00) (f64.const 1.0e-300)))))
    (local.set $k (i32.shr_s (i32.sub (local.get $iy) (local.get $ix)) (i32.const 20)))
    (if (i32.gt_s (local.get $k) (i32.const 60))
      (then (local.set $z (f64.add (f64.const 1.5707963267948965580e+00) (f64.mul (f64.const 0.5) (f64.const 1.2246467991473531772e-16)))))
      (else
        (if (i32.and (i32.lt_s (local.get $hx) (i32.const 0)) (i32.lt_s (local.get $k) (i32.const -60)))
          (then (local.set $z (f64.const 0)))
          (else (local.set $z (call $atan (f64.abs (f64.div (local.get $y) (local.get $x)))))))))
    (if (i32.eq (local.get $m) (i32.const 0)) (then (return (local.get $z))))
    (if (i32.eq (local.get $m) (i32.const 1)) (then (return (f64.neg (local.get $z)))))
    (if (i32.eq (local.get $m) (i32.const 2))
      (then (return (f64.sub (f64.const 3.1415926535897931160e+00) (f64.sub (local.get $z) (f64.const 1.2246467991473531772e-16))))))
    (f64.sub (f64.sub (local.get $z) (f64.const 1.2246467991473531772e-16)) (f64.const 3.1415926535897931160e+00)))


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
  ;; 中断検査（jil.md §4・プレリュードの LIVE / STOP）: 生成部は自陣の手順への cast の前に $live（呼ぶ前に active で
  ;; 休止中でなかったか）を局所に取り、直後に $stop(i, live) で「この呼び出しで active でなくなった」ときだけ返る。
  ;; 呼ぶ前から active でない陣では止めない: 未 entered の summon の呼び先・done の陣・on exit の中（入れ子の finish / transfer は
  ;; no-op）、transfer で休止中の陣（入れ子の finish で done にはなるが巻き戻さない）。Issue #87 / #89・jil.md §4
  (func $live (param $i i32) (result i32) (call $is_active (local.get $i)))
  (func $stop (param $i i32) (param $live i32) (result i32)
    (i32.and (local.get $live) (i32.eqz (call $is_active (local.get $i)))))

  (func $lr_reset (param $l (ref null $Lr)) (struct.set $Lr 1 (local.get $l) (i32.const 0)))

  ;; ---------------------------------------------------------------- トレース行（runtime.md §5・DEBUG のとき）
  ;; kind: 0 enter / 1 exit / 2 event / 3 rite / 4 cast / 5 set / 6 emit / 7 transfer / 8 wait / 9 finish / 10 assert / 11 error / 12 frame
  (func $kind_str (param $k i32)
    (if (i32.eq (local.get $k) (i32.const 0)) (then (call $puts (i32.const 534) (i32.const 5)) (return)))
    (if (i32.eq (local.get $k) (i32.const 1)) (then (call $puts (i32.const 539) (i32.const 4)) (return)))
    (if (i32.eq (local.get $k) (i32.const 2)) (then (call $puts (i32.const 543) (i32.const 5)) (return)))
    (if (i32.eq (local.get $k) (i32.const 3)) (then (call $puts (i32.const 548) (i32.const 4)) (return)))
    (if (i32.eq (local.get $k) (i32.const 4)) (then (call $puts (i32.const 552) (i32.const 4)) (return)))
    (if (i32.eq (local.get $k) (i32.const 5)) (then (call $puts (i32.const 556) (i32.const 3)) (return)))
    (if (i32.eq (local.get $k) (i32.const 6)) (then (call $puts (i32.const 559) (i32.const 4)) (return)))
    (if (i32.eq (local.get $k) (i32.const 7)) (then (call $puts (i32.const 563) (i32.const 8)) (return)))
    (if (i32.eq (local.get $k) (i32.const 8)) (then (call $puts (i32.const 571) (i32.const 4)) (return)))
    (if (i32.eq (local.get $k) (i32.const 9)) (then (call $puts (i32.const 575) (i32.const 6)) (return)))
    (if (i32.eq (local.get $k) (i32.const 10)) (then (call $puts (i32.const 581) (i32.const 6)) (return)))
    (if (i32.eq (local.get $k) (i32.const 11)) (then (call $puts (i32.const 587) (i32.const 5)) (return)))
    (call $puts (i32.const 592) (i32.const 5)))

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
      (then (call $puts (i32.const 20) (i32.const 4)))
      (else (call $put_str (local.get $s)))))

  (func $put_opt_js (param $s (ref null $str))
    (if (ref.is_null (local.get $s))
      (then (call $puts (i32.const 20) (i32.const 4)))
      (else (call $put_js (local.get $s)))))

  ;; "/circles/<i>"
  (func $circle_ptr (param $i i32) (result (ref $str))
    (local $old (ref null $buf))
    (local.set $old (call $fmt_begin))
    (call $puts (i32.const 668) (i32.const 9))
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
    (call $puts (i32.const 597) (i32.const 7))
    (call $put_jn (f64.convert_i32_s (struct.get $Row 0 (local.get $r))))
    (call $puts (i32.const 604) (i32.const 8))
    (call $put_jn (f64.convert_i32_s (struct.get $Row 1 (local.get $r))))
    (call $puts (i32.const 612) (i32.const 10))
    (if (i32.lt_s (struct.get $Row 2 (local.get $r)) (i32.const 0))
      (then (call $puts (i32.const 20) (i32.const 4)))
      (else (call $put_js (call $prog_name (struct.get $Row 2 (local.get $r))))))
    (call $puts (i32.const 622) (i32.const 8))
    (call $putc (i32.const 34))
    (call $kind_str (struct.get $Row 3 (local.get $r)))
    (call $putc (i32.const 34))
    (call $puts (i32.const 630) (i32.const 8))
    (call $put_opt_js (struct.get $Row 4 (local.get $r)))
    (call $puts (i32.const 638) (i32.const 11))
    (call $put_opt_js (struct.get $Row 5 (local.get $r)))
    (call $puts (i32.const 649) (i32.const 9))
    (call $put_opt (struct.get $Row 6 (local.get $r)))
    (call $puts (i32.const 658) (i32.const 10))
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
          (then (call $puts (i32.const 704) (i32.const 9)) (call $put_jn (global.get $WREQ_TICKS)) (call $putc (i32.const 125)))
          (else (call $puts (i32.const 724) (i32.const 14))))
        (drop (call $row (i32.const 8) (local.get $i) (ref.null $str) (global.get $WREQ_PTR)
          (call $fmt_end (local.get $old)) (call $mem_str (i32.const 738) (i32.const 9))))))
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
                          (call $mem_str (select (i32.const 713) (i32.const 724) (i32.eq (struct.get $Wait 1 (local.get $w)) (i32.const 1)))
                                         (select (i32.const 11) (i32.const 14) (i32.eq (struct.get $Wait 1 (local.get $w)) (i32.const 1))))
                          (call $mem_str (i32.const 747) (i32.const 8))))))
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
        (call $puts (i32.const 1015) (i32.const 14))
        (call $put_str (call $prog_name (local.get $j)))
        (call $puts (i32.const 1029) (i32.const 32))
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
    (call $puts (i32.const 755) (i32.const 6))
    (call $put_jn (f64.convert_i32_s (global.get $ASKED)))
    (call $puts (i32.const 761) (i32.const 10))
    (call $put_js (call $prog_name (local.get $ci)))
    (call $puts (i32.const 771) (i32.const 8))
    (call $put_js (local.get $name))
    (call $puts (i32.const 779) (i32.const 10))
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
      (then (call $ERR (call $mem_str (i32.const 1061) (i32.const 96))))))

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
            (call $mem_str (select (i32.const 11) (i32.const 15) (local.get $delivered))
                           (select (i32.const 4) (i32.const 5) (local.get $delivered)))))))
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
            (local.set $idf (call $j_num (call $j_getk (local.get $ev) (i32.const 447) (i32.const 2))))
            ;; math.tointeger: 整数値のときだけ（0 は「id 無し」の印に使う）
            (local.set $id (i32.const 0))
            (if (i32.and (i32.eq (call $j_kind (call $j_getk (local.get $ev) (i32.const 447) (i32.const 2))) (i32.const 2))
                         (i32.and (f64.eq (local.get $idf) (f64.floor (local.get $idf))) (f64.lt (f64.abs (local.get $idf)) (f64.const 2147483648))))
              (then (local.set $id (i32.trunc_f64_s (local.get $idf)))))
            (local.set $a (if (result i32) (local.get $id) (then (call $ask_find (local.get $id))) (else (i32.const -1))))
            (local.set $text (call $j_str (call $j_getk (local.get $ev) (i32.const 434) (i32.const 4))))
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
                  (call $mem_str (select (i32.const 11) (i32.const 15) (local.get $delivered))
                                 (select (i32.const 4) (i32.const 5) (local.get $delivered)))))))
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
                (br_if $d2 (i32.eqz (call $is_active (local.get $i))))
                (br_if $d2 (global.get $ERRED))
                (local.set $kind (call $ev_kind (local.get $k)))
                (if (i32.and (i32.eq (local.get $kind) (i32.const 1)) (call $prog_has_on (local.get $i) (i32.const 1)))
                  (then (call $prog_on_key (local.get $i) (local.get $k))))
                (if (i32.and (i32.eq (local.get $kind) (i32.const 2)) (call $prog_has_on (local.get $i) (i32.const 2)))
                  (then (call $prog_on_pointer (local.get $i) (local.get $k))))
                (local.set $k (i32.add (local.get $k) (i32.const 1)))
                (br $n2)))
            (if (i32.and (call $is_active (local.get $i)) (i32.and (i32.eqz (global.get $ERRED)) (call $prog_has_on (local.get $i) (i32.const 3))))
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
    (if (i32.eq (local.get $s) (i32.const 1)) (then (call $puts (i32.const 793) (i32.const 6)) (return)))
    (if (i32.eq (local.get $s) (i32.const 2)) (then (call $puts (i32.const 799) (i32.const 4)) (return)))
    (call $puts (i32.const 789) (i32.const 4)))

  (func $put_hex64 (param $v i64)
    (local $shift i32) (local $d i32) (local $started i32)
    (call $puts (i32.const 803) (i32.const 2))
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
    (call $puts (i32.const 805) (i32.const 8))
    (call $put_jn (f64.convert_i64_s (global.get $SEED)))
    (call $puts (i32.const 813) (i32.const 8))
    (call $put_jn (f64.convert_i64_s (global.get $TICK)))
    (call $puts (i32.const 821) (i32.const 7))
    (call $put_jn (f64.convert_i32_s (global.get $SEQ)))
    (call $puts (i32.const 828) (i32.const 7))
    (call $putc (i32.const 34))
    (call $put_hex64 (global.get $RS))
    (call $putc (i32.const 34))
    (call $puts (i32.const 835) (i32.const 8))
    (call $put_bool (global.get $DONE))
    (call $puts (i32.const 843) (i32.const 9))
    (call $put_jn (f64.convert_i32_s (global.get $ASKED)))
    (call $puts (i32.const 852) (i32.const 12))
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $i) (global.get $N)))
        (if (local.get $i) (then (call $putc (i32.const 44))))
        (call $puts (i32.const 864) (i32.const 8))
        (call $put_js (call $prog_name (local.get $i)))
        (call $puts (i32.const 872) (i32.const 10))
        (call $putc (i32.const 34))
        (call $put_status (call $cst (local.get $i)))
        (call $putc (i32.const 34))
        (call $puts (i32.const 882) (i32.const 10))
        (call $put_bool (call $cget (global.get $CPAUSED) (local.get $i)))
        (call $puts (i32.const 892) (i32.const 11))
        (call $put_bool (call $cget (global.get $CPENDING) (local.get $i)))
        (call $puts (i32.const 903) (i32.const 10))
        (call $put_jn (f64.convert_i32_s (call $cget (global.get $CCURSOR) (local.get $i))))
        (call $puts (i32.const 913) (i32.const 13))
        (call $put_bool (call $cget (global.get $CPUB) (local.get $i)))
        (call $puts (i32.const 926) (i32.const 12))
        (local.set $d (call $cget (global.get $CDELEG) (local.get $i)))
        (if (i32.lt_s (local.get $d) (i32.const 0))
          (then (call $puts (i32.const 20) (i32.const 4)))
          (else (call $put_js (call $prog_name (local.get $d)))))
        (call $puts (i32.const 938) (i32.const 9))
        (if (call $prog_flow (local.get $i))
          (then (call $puts (i32.const 20) (i32.const 4)))
          (else (call $prog_dump (local.get $i))))
        (call $puts (i32.const 947) (i32.const 10))
        (if (call $prog_flow (local.get $i))
          (then (call $puts (i32.const 20) (i32.const 4)))
          (else (call $prog_pdump (local.get $i))))
        (call $putc (i32.const 125))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (call $puts (i32.const 957) (i32.const 2)))

  (func $note_push (param $b (ref null $buf)) (param $name (ref null $str))
    (local $old (ref null $buf))
    (local.set $old (global.get $OUT))
    (global.set $OUT (ref.as_non_null (local.get $b)))
    (if (struct.get $buf 1 (local.get $b)) (then (call $putc (i32.const 44))))
    (call $put_js (local.get $name))
    (global.set $OUT (ref.as_non_null (local.get $old))))

  (func $put_resume_note
    (call $puts (i32.const 959) (i32.const 8))
    (if (i32.eq (global.get $RN_MODE) (i32.const 1))
      (then (call $puts (i32.const 967) (i32.const 9)))
      (else (call $puts (i32.const 976) (i32.const 7))))
    (call $puts (i32.const 983) (i32.const 8))
    (call $put_jn (f64.convert_i32_s (global.get $RN_TICK)))
    (call $puts (i32.const 991) (i32.const 9))
    (call $put_buf (global.get $RN_KEPT))
    (call $puts (i32.const 1000) (i32.const 13))
    (call $put_buf (global.get $RN_DROPPED))
    (call $puts (i32.const 1013) (i32.const 2)))

  ;; 陣を名前で照合して状態を写す（restore_from）。root が照合できなければ通常の boot に落として 0
  (func $restore_from (param $resume (ref null $J)) (result i32)
    (local $snaps (ref null $J)) (local $k i32) (local $n i32) (local $sc (ref null $J)) (local $name (ref null $str)) (local $i i32)
    (local $status (ref null $str)) (local $d (ref null $str)) (local $di i32) (local $rs i64)
    (call $buf_clear (global.get $RN_KEPT))
    (call $buf_clear (global.get $RN_DROPPED))
    (local.set $snaps (call $j_getk (local.get $resume) (i32.const 455) (i32.const 7)))
    (local.set $n (call $j_len (local.get $snaps)))   ;; object なら ipairs は空
    (block $done
      (loop $next
        (br_if $done (i32.ge_u (local.get $k) (local.get $n)))
        (local.set $sc (call $j_at (local.get $snaps) (local.get $k)))
        (local.set $name (call $j_str (call $j_getk (local.get $sc) (i32.const 438) (i32.const 4))))
        (local.set $i (i32.const -1))
        (if (i32.eqz (ref.is_null (local.get $name))) (then (local.set $i (call $prog_find (local.get $name)))))
        ;; 核あり陣の snapshot は state を持ち（空でも {}）、核なし陣は null
        (if (i32.and (i32.ge_s (local.get $i) (i32.const 0))
                     (i32.eq (i32.ne (call $prog_flow (local.get $i)) (i32.const 0))
                             (i32.eqz (call $rd_rec (call $j_getk (local.get $sc) (i32.const 462) (i32.const 5))))))
          (then
            (local.set $status (call $j_str (call $j_getk (local.get $sc) (i32.const 467) (i32.const 6))))
            (if (i32.eqz (ref.is_null (local.get $status)))
              (then
                (if (call $str_eq_mem (local.get $status) (i32.const 793) (i32.const 6)) (then (call $cset (global.get $CST) (local.get $i) (i32.const 1))))
                (if (call $str_eq_mem (local.get $status) (i32.const 799) (i32.const 4)) (then (call $cset (global.get $CST) (local.get $i) (i32.const 2))))
                (if (call $str_eq_mem (local.get $status) (i32.const 789) (i32.const 4)) (then (call $cset (global.get $CST) (local.get $i) (i32.const 0))))))
            (call $cset (global.get $CPAUSED) (local.get $i) (call $j_is_true (call $j_getk (local.get $sc) (i32.const 473) (i32.const 6))))
            (call $cset (global.get $CPENDING) (local.get $i) (call $j_is_true (call $j_getk (local.get $sc) (i32.const 479) (i32.const 7))))
            (call $cset (global.get $CCURSOR) (local.get $i) (call $rd_int (call $j_getk (local.get $sc) (i32.const 486) (i32.const 6)) (i32.const 0)))
            (call $cset (global.get $CPUB) (local.get $i) (call $j_is_true (call $j_getk (local.get $sc) (i32.const 492) (i32.const 9))))
            (local.set $d (call $j_str (call $j_getk (local.get $sc) (i32.const 501) (i32.const 8))))
            (local.set $di (i32.const -1))
            (if (i32.eqz (ref.is_null (local.get $d))) (then (local.set $di (call $prog_find (local.get $d)))))
            (call $cset (global.get $CDELEG) (local.get $i) (local.get $di))
            (if (i32.lt_s (local.get $di) (i32.const 0))
              (then (call $cset (global.get $CPAUSED) (local.get $i) (i32.const 0)))
              (else
                (if (i32.eqz (call $cst (local.get $di))) (then (call $cset (global.get $CPENDING) (local.get $i) (i32.const 1))))))
            (if (i32.eqz (call $prog_flow (local.get $i)))
              (then
                (call $prog_restore (local.get $i) (call $j_getk (local.get $sc) (i32.const 462) (i32.const 5)))
                (if (call $rd_rec (call $j_getk (local.get $sc) (i32.const 509) (i32.const 6)))
                  (then (call $prog_prestore (local.get $i) (call $j_getk (local.get $sc) (i32.const 509) (i32.const 6)))))))
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
    (global.set $TICK (i64.extend_i32_s (call $rd_int (call $j_getk (local.get $resume) (i32.const 515) (i32.const 4)) (i32.const -1))))
    (global.set $SEQ (call $rd_int (call $j_getk (local.get $resume) (i32.const 519) (i32.const 3)) (i32.const 0)))
    (global.set $ASKED (call $rd_int (call $j_getk (local.get $resume) (i32.const 522) (i32.const 5)) (i32.const 0)))
    (local.set $rs (call $parse_hex64 (call $j_str (call $j_getk (local.get $resume) (i32.const 527) (i32.const 3)))))
    (if (global.get $RD_OK) (then (global.set $RS (local.get $rs))))
    (global.set $DONE (call $j_is_true (call $j_getk (local.get $resume) (i32.const 530) (i32.const 4))))
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
