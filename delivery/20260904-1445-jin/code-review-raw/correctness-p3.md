# Stage 5 review: correctness — Phase 3 (jin-render)

- 対象: ブランチ `feat/jin-phase3-render` の作業ツリー（`git diff origin/main` + 未追跡）。中心は
  `packages/jin-render/src/jin_render/{geometry,svg,ornament,overlay,layout}.py`、`packages/jin-cli/src/jin_cli/main.py` の
  `render` / `_read_trace_rows` / `_write_svg` / `_write_atomically(allow_create)`、テスト一式、`docs/spec/layout.md`
- 正典: `jin-requirements.md` §2.5 / §4 / §5 → `docs/spec/layout.md` → `docs/spec/adk-mapping.md` §2.4
- 実装者の記録（implementation-notes P3 節 / decision-conformance §2.24 / phase3-handoff）は読んだが根拠にしていない。
  判断材料は差分コード・生成 SVG・テスト・仕様のみ

confidence の基準: 85 以上 = 隔離コピーで実測して直接確認、60〜80 = 実測で間接確認または仕様の読解に解釈の余地がある、
60 未満 = 読解のみ / 記述の不一致。

## 実測した環境・コマンド（隔離コピーのパス・件数）

- 隔離コピー: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-correctness/`（`packages` / `tests` / `examples` / `docs` /
  `schemas` / `pyproject.toml` / `jin-requirements.md` を `cp -r`。`delivery/` と `CLAUDE.md` は複製していない）
- 実行: `run_pytest.sh`（`PYTHONDONTWRITEBYTECODE=1`・`__pycache__` 削除・`PYTHONPATH` にコピー側 4 パッケージの `src`・
  `-o addopts=--import-mode=importlib -p no:cacheprovider`・python は worktree の `.venv`）。import 元がコピー側であることの証拠は、
  コピー側のソースだけを書き換えた変異で結果が変わったこと（`OVL-no-break` の 4 failed、スナップショット限定 6 件の赤）
- ベースライン（コピー）: `packages/jin-render/tests` + `packages/jin-cli/tests/test_render.py` → **177 passed・4 snapshots passed**
- 契約（コピー）: `tests/contract/{test_render_contract,test_guard_claims,test_packaging_contract,test_dependency_direction}.py` + `tests/spec`
  → 144 passed / 7 failed。**7 件はすべて `FileNotFoundError`**（コピーに `delivery/` と `CLAUDE.md` が無いため。実装の欠陥ではない）。
  `test_render_contract.py` は live `jin run --model fake` を含めて全緑
- 全スイート（worktree・読み取り専用 `run_full_wt.sh`・bytecode / cache を書かない）: **1005 passed, 68 warnings**（実装者の申告と一致）
- 実測スクリプト: 同ディレクトリの `probe1.py`（挙動の実測 16 項目）/ `mutate_probe.py`（変異 12 件・スナップショット除外）/
  `mutate_probe2.py`（同 6 件・スナップショットのみ）
- 実ツリーは本ファイルの追加以外に変更していない。`git status --short` には他エージェント（auto-decider）による
  `delivery/auto-*` / `docs/pending-decisions.md` / `docs/adr/ADR-019,020` の変更が同時に現れているが、本レビューの操作ではない

## 上位 5 件（親のトリアージ用）

| ID | 要旨 | conf |
|---|---|---|
| F-C-P3-001 | `--trace` の読み取りが `str.splitlines()` で U+2028 / U+2029 / U+0085 を行区切りに数え、`jin run` が書いた正当な JSONL を exit 2 で拒む | 90 |
| F-C-P3-002 | loop の矢印が節 j → 節 j+k を指し（S0→S2）、要件書 §2.5「辺の順を訪問順に一致させる」と逆。layout.md §2.1 / §6 とテストがこの挙動を固定 | 70 |
| F-C-P3-003 | layout.md §7.2「`summon` なら入れ子の小陣の外枠」が強調される、は実物と不一致。wrapper `<g>` の朱は入れ子 `<g>` の `stroke="#000000"` に上書きされ、赤くなるのは放射線だけ | 85 |
| F-C-P3-004 | `read_trace` が `seq <= 0` を拒まない。layout.md §7.5「1 始まり」に反し、`--upto 0` で seq 0 の行が発火する。拒む変異を入れても全テスト緑 | 75 |
| F-C-P3-005 | 放射線・flow の弦の終端が固定値 0.266（106.4 px）で、入れ子 circle の実際の最外環（Drafter は 84 px）より外側で止まる | 80 |

## Findings

### F-C-P3-001 [confidence 90] `_read_trace_rows` の `splitlines()` が JSONL の行区切りとして誤り。正当なトレースを exit 2 で拒む
- 場所: `packages/jin-cli/src/jin_cli/main.py:854`（`for number, line in enumerate(text.splitlines(), start=1)`）
- 内容: `str.splitlines()` は `\n` / `\r\n` のほかに U+0085（NEL）・U+2028（LINE SEPARATOR）・U+2029（PARAGRAPH SEPARATOR）でも割る
  （U+000B / U+000C / U+001C〜U+001E でも割るが、これらは 0x20 未満で `json.dumps` が必ずエスケープするので到達しない）。
  JSON はこの 3 文字を文字列値の中に**生で**許し、`jin_adk.trace.TraceWriter._emit` は
  `json.dumps(..., ensure_ascii=False)`（`packages/jin-adk/src/jin_adk/trace.py:338`）で書くので、モデル出力・ツール出力に
  U+2028 が 1 文字あるだけで `jin run --trace` の出力そのものが `jin render --trace` で読めなくなる。行番号の表示も狂う
- 再現（隔離コピー・`probe1.py`）: `{"seq": 1, "pointer": "/circles/2/core", "output": "a<U+2028>b"}` の 1 行を書いた JSONL →
  `splitlines()` の要素数 2 → `jin render pipeline.jin --trace t.jsonl` が **exit 2**・stderr
  `t.jsonl:1: JSON として読めません（Unterminated string starting at）`。U+0085 でも同じ（exit 2）
- 期待との差: NFR-FAIL-001 の「黙って読み飛ばさない」は満たすが、**壊れていない入力を壊れていると報告する**（誤検出）。
  JSONL の区切りは `\n` だけである
- 変異検証: 該当なし（欠陥そのものを実測）。テスト側の fixture 読み取りも同じ `splitlines()`（`packages/jin-render/tests/conftest.py:71`、
  `packages/jin-cli/tests/test_render.py:188`、`tests/contract/test_render_contract.py:103,116`）なので、fixture にこの文字が
  混ざっても両側が同じに割れて検出できない
- 提案: `text.split("\n")`（末尾の `\r` は `rstrip("\r")`）に替え、U+2028 を含む `output` を持つ 1 行の JSONL を読める
  テストを `packages/jin-cli/tests/test_render.py` に足す。テスト側 4 箇所の `splitlines()` も同じ理由で `split("\n")` に

### F-C-P3-002 [confidence 70] loop の矢印の向きが要件書 §2.5「辺の順を訪問順に一致させる」と一致しない（仕様側・コード側の両方）
- 場所: `packages/jin-render/src/jin_render/layout.py:532-534`（`pairs = [(j, (j + step) % count) ...]`）、
  `docs/spec/layout.md` §2.1 最終段（「辺は『節 j から節 (j + k) mod n』を結ぶ」）と §6 の `loop` 行、
  `packages/jin-render/tests/test_layout.py::test_loop_edges_follow_the_star_polygon`
- 内容: 節 i は配列順に角位置 i に置かれ、辺は j → (j+k) mod n に**矢じり付き**で描かれる。n=5（k=2）を実測すると
  矢印は `S0→S2, S1→S3, S2→S4, S3→S0, S4→S1`（`probe1.py`）。実行順（`flow.steps` の配列順）は S0→S1→S2→S3→S4 なので、
  矢じりは「S0 のあとに S2 が走る」と読める。要件書 §2.5 は「星形多角形 {n/k} で描き、辺の順を訪問順に一致させる」で、
  自然な読みは「辺を順に辿ると訪問順になる」。implementation-notes P3-7 の 5 は「矢じりが無いと訪問順を目で追えない」と
  矢じりを足した理由を書いているが、その矢じりが訪問順と食い違っている
- 期待との差: {n/k} を保ちつつ訪問順に一致させる配置は存在する。節 i を角位置 `(i * k) mod n` に置き、辺を i → i+1（配列順）で
  結べば、辺列は同じ星形を描き、矢じりは実行順を指す（gcd(n,k)=1 なので角位置は全単射）。現在の layout.md §2.1 は
  「辺の順は訪問順に一致させる」と書きながら直後に j → j+k を定義しており、文書内でも食い違っている
- 変異検証: 該当なし（挙動の実測）。`STAR-reversed`（j → j−k）は実装者ハーネスで赤くなるが、これは「現在の定義に合っているか」の検査
- 提案: (a) 節の角位置を `(i*k) mod n` にし辺を i → i+1 にする（仕様 §2.1 / §6・テストの期待値を同時に直す）、または
  (b) 要件書 §2.5 の当該句の解釈を HANDOFF にして人間に決めさせ、決まるまでは loop の矢じりを外す（要件書は
  `sequence` にだけ「（矢印）」と書いている）。どちらでも layout.md §2.1 の「辺の順は訪問順に一致させる」の文を実物に合わせる

### F-C-P3-003 [confidence 85] layout.md §7.2 / §7.3 の「`summon` の紋（入れ子の小陣の外枠）が強調される」が実物と一致しない
- 場所: `docs/spec/layout.md` §7.2 の `/circles/i/tools/j` 行（「`summon` なら入れ子の小陣の外枠」）と §7.3（「呼ばれたは見える: tool 行が紋を強調する」）、
  `packages/jin-render/src/jin_render/layout.py:392`（wrapper `<g>` は属性なし）、`layout.py:211-219`（入れ子の `<g>` が `stroke=INK` を明示）
- 内容: researcher に `{"seq":1,"pointer":"/circles/0/tools/2"}`（summon `summarize`）を渡した実測（`probe1.py`）:
  fired になるのは放射線 `<line data-jin=/circles/0/tools/2>` と wrapper `<g data-jin=/circles/0/tools/2 data-jin-ref=/circles/1>`。
  wrapper には `stroke="#cc0000" stroke-width="2.000"` が付くが、その唯一の子 `<g data-jin="/circles/1" stroke="#000000" stroke-width="1.000">`
  が継承を断つので、**入れ子の小陣に朱は 1 px も現れない**。目に見える強調は放射線だけで、「外枠」に当たる要素は存在しない
- 期待との差: 仕様が「外枠が強調される」と書いているものが描画に無い。`test_a_summoned_circle_stays_unfired_when_only_the_tool_row_appears`
  は入れ子の内側が未強調であることだけを固定しており、「呼ばれたことが見える」側は検査していない
- 変異検証: 該当なし（実物の読み取り）
- 提案: 仕様文を実物（放射線だけが朱くなる）に合わせるか、summon の紋として見える外枠（入れ子の最外環の少し外側の円・
  pointer は参照側・kind は `tool`）を wrapper 直下に描いて wrapper の accent が見えるようにする。後者なら F-C-P3-005 の extent とも整合する

### F-C-P3-004 [confidence 75] `read_trace` が `seq <= 0` を受理し、`--upto 0` で発火する。layout.md §7.5「seq（int・1 始まり）」に反する
- 場所: `packages/jin-render/src/jin_render/overlay.py:48-52`、`docs/spec/layout.md` §7.5
- 内容: `read_trace([{"seq": 0, ...}, {"seq": -1, ...}])` は例外なく通る（実測）。`render(pipeline, trace=[{"seq":0,"pointer":"/circles/2/core"}], upto=0)`
  で `/circles/2/core` が fired になる（実測）。`--upto 0` は「まだ何も発火していない」状態を見るための値だが、seq 0 の行があれば強調される
- 変異検証: `if ... or seq < 1:` で拒む変異（`SEQ-zero-accepted-is-untested`）を入れても `test_overlay` / `test_layout` / `test_determinism` /
  `test_snapshots` / `test_render.py` の **126 件すべて緑**。仕様の「1 始まり」を検査するテストが無い
- 提案: `seq < 1` を `ValueError` にする（「黙って捨てない」の方針と同じ側）か、§7.5 の「1 始まり」を「int」に緩めて実物と揃える。どちらでもテストを 1 本足す

### F-C-P3-005 [confidence 80] 放射線・flow の弦の終端が固定値 `NESTED_SCALE * RING_BOUNDARY` で、入れ子の実際の最外環と一致しない
- 場所: `packages/jin-render/src/jin_render/layout.py:304-310`（`_tool_extent`）、`513-518`（`_flow_extent`）
- 内容: 深さ 1 の入れ子は「境界環を持つ」前提で extent = 0.28 × 0.95 = 0.266（106.4 px）に固定されている。
  Pipeline→Drafter の弦はスナップショット上 Drafter 中心から 106.4 px で始まる（`M 553.200 372.145` と中心 `(500, 280)` の距離）が、
  Drafter は boundary を持たず最外環は state 環 0.75 × 112 = **84.0 px**（実測）。22 px の隙間が出る。核なし・環なしの入れ子
  （flow だけの circle）ではさらに大きい
- 期待との差: layout.md §6 は「入れ子の小陣の縮尺 0.28 は境界環をはみ出さない」根拠しか書いておらず、線の終端の決め方は書いていない。
  数値が仕様に無いので仕様違反ではないが、「核 → 紋へ放射線を引く」（§2）の線が紋に届いていない
- 変異検証: `RADIAL-full-length`（extent を 0 にして環まで引く）は非スナップショットの 110 件が緑、スナップショットのみ赤（下表）
- 提案: 入れ子 circle の最外半径（存在する環の最大、無ければ節 / 核 / 点の半径）から extent を計算する。仕様 §6 に決め方を 1 行足す

### F-C-P3-006 [confidence 60] `-o` の親ディレクトリが無いときの文言が誤り（「書き込む直前にファイルが消えました」）
- 場所: `packages/jin-cli/src/jin_cli/main.py:376-380`（`mkstemp` の `OSError` → `_classify_write_failure`）、`_WRITE_ERRNO_HINTS` の ENOENT
- 内容: `jin render pipeline.jin -o <無いディレクトリ>/x.svg` → **exit 1**・stderr `…/nope/x.svg: 書き込む直前にファイルが消えました（No such file or directory）`
  （実測）。exit code と fail-closed は正しいが、ENOENT の文言は `fmt`（対象が在る前提）向けで、`allow_create=True` の経路では
  「最初から無い」のに「消えた」と言う。既存ディレクトリを `-o` に指定して `--force` した場合は `Is a directory` で exit 1（妥当）
- 変異検証: 該当なし
- 提案: `allow_create=True` で `mkstemp` が ENOENT のときは「出力先のディレクトリがありません」にする（`_classify_write_failure` に
  `allow_create` を渡すか、`_write_svg` で `path.parent.is_dir()` を先に見る）

### F-C-P3-007 [confidence 55] `_trace_dots` の `accent_attr="fill"` は到達しない設定
- 場所: `packages/jin-render/src/jin_render/layout.py:691`
- 内容: 点は `fired_indices` の**あと**に `group.children` に足される（`layout.py:753-759`）ので `fired` になる経路が無い。
  「点は fill で強調される」と読めるが、実際には強調されない（§7.4 の意図どおり）
- 変異検証: `DOT-accent-fill-dead`（この引数を削除）で `test_overlay` / `test_layout` / `test_snapshots` / `test_render.py` の 114 件が緑
- 提案: 引数を外すか、「点は強調しないため未使用」とコメントする。害は無い

### F-C-P3-008 [confidence 50] テストの docstring が参照する規則番号が layout.md §7.1 に存在しない
- 場所: `packages/jin-render/tests/test_overlay.py:87`（「規則 2（祖先一致）」）、`:103`（「規則 4（referent 規則）」）、`docs/spec/layout.md` §7.1（項目は 3 つ）
- 内容: §7.1 の番号は 1 = 完全一致 / 2 = `data-jin-ref` 一致 / 3 = 見つからない行。「祖先一致」は番号付きの規則ではなく段の削り方の説明で、
  「規則 4」は無い。仕様を読みながらテストを追う人が対応を取れない
- 提案: docstring を §7.1 の実際の項目名（「末尾から削る」「規則 2（data-jin-ref）」）に合わせる

### F-C-P3-009 [confidence 50] 装飾が使うダイジェストの末尾バイトの記述が 3 箇所で食い違う
- 場所: `docs/spec/layout.md:85`（「24 バイト目まで」）、`packages/jin-render/src/jin_render/ornament.py` docstring（`1 + 3*7 + 2 = 24` バイト目）、
  `packages/jin-render/tests/test_determinism.py:157`（「25 バイト目まで」）
- 内容: 8 点目の大きさは `digest[24]`（0 始まりの添字 24 = **25 バイト目**）。layout.md と ornament.py は添字と序数を混同している。
  SHA-256 は 32 バイトなので範囲外にはならず、動作上の欠陥ではない
- 提案: layout.md と ornament.py を「添字 24（25 バイト目）まで」に直す

### F-C-P3-010 [confidence 45] layout.md §4 の丸め根拠「キャンバス内の最大座標（1300 px 級）」がキャンバスの実寸と合わない
- 場所: `docs/spec/layout.md:144`、`decision-conformance.md` §2.24.1、`packages/jin-render/tests/test_svg.py:48`（`largest = 1300.0`）
- 内容: `viewBox="0 0 1000 1000"` なので座標の上限は 1000 px 級（トレースの点 1.10 × 400 + 500 = 940）。1300 は上界として安全側だが、
  根拠として書かれた数値がどこから来たか読めない
- 提案: 「1000 px 級（上界として 1300 を検査に用いる）」と書く。値の変更は不要

### F-C-P3-011 [confidence 55] `jin render -o` の成功メッセージだけ `_safe` を通していない
- 場所: `packages/jin-cli/src/jin_cli/main.py:953`（`typer.echo(f"書き出しました: {out}")`）。同関数の他の出力（`:947,951`）は `_safe(str(out))`
- 内容: `out` は利用者入力のパス。`build` の同種メッセージ（`:665`）も通していないので既存踏襲だが、Phase 3 で新たに足した行で
  同じ関数内の規律と揃っていない。security 軸と重なる可能性あり
- 提案: `_safe(str(out))` に揃える

### F-C-P3-012 [confidence 60] 核なし circle に `state` / `boundary` / `delegate` があるときの描き方がテスト・スナップショットに 1 件も無い
- 場所: `packages/jin-render/src/jin_render/layout.py:263-274`（`_rings`）、`411-436`（`_delegate_lines` の `else (frame.cx, frame.cy)` 分岐）
- 内容: flow だけの circle に `state` と `boundary.guards` を足したモデルを描くと state 環（300 px）と boundary 環（380 px）が描かれる（実測）。
  layout.md §1 は「核なし circle（**flow だけ**）は環を 1 本も描かない」なので矛盾ではないが、「核なし + delegate」では破線が
  中心点から出る、という分岐は §5 の「意味エラーを含むモデルも描く」の範囲にあるのに検査されていない
- 変異検証: `STATE-ring-needs-core`（核が無ければ state 環を描かない）と `DELEGATE-line-from-core-only`（核が無ければ破線を小円上で潰す）
  のどちらも、スナップショットを含む全テストが**緑**
- 提案: `MODELABLE_ERROR_FIXTURES` の中に JIN022 系（core と flow の両立）の fixture があるなら、その描画で環と破線の有無を 1 本固定する。
  無ければ合成モデルを 1 本足す

### F-C-P3-013 [confidence 40] `pointer_prefixes("/")` が `["/"]` を返す
- 場所: `packages/jin-render/src/jin_render/overlay.py:66-72`
- 内容: JSON Pointer の `"/"` は「空キー」を指す正当な pointer だが、描画要素に `data-jin="/"` は無いので何も強調されない。害は無く、
  `""`（ルート）は `[]` を返して同様に無害。記録のみ

## 変異で緑のままだったテスト（偽 green の候補）

隔離コピーで実装を 1 箇所ずつ壊し、**スナップショット（`test_snapshots.py`）を除いた**関連テストを回した結果。
右列は「スナップショットだけを回したとき」の結果。**スナップショットだけが捕まえる変異**は、`--snapshot-update` で
差分を読まずに更新すると素通りするので、専用のアサーションを 1 本置く価値がある。

| 変異 | 内容 | 非スナップショットのテスト | スナップショットのみ |
|---|---|---|---|
| `SEQ-reversed` | `sequence` の弦を `(j+1, j)` にして矢印を逆向きにする | **緑**（110 passed: test_layout / test_overlay / test_render.py） | 赤（2 failed） |
| `ARROW-head-zero` | 矢じりの大きさを 0 にする | **緑**（110 passed） | 赤（2 failed） |
| `AWAIT-wrong-tool-angle` | `await` の欠けと刻印を対象の紋から 2 つずれた角度に置く | **緑**（110 passed）— `test_await_cuts_the_boundary_ring` は弧の本数しか見ていない | 赤（1 failed） |
| `AWAIT-gap-misaligned` | 欠けの角度の基準を `- TOP_ANGLE` から `+ TOP_ANGLE` に変え、欠けと刻印を別の場所にする | **緑**（138 passed・geometry を含む） | 赤（1 failed） |
| `ORN-radius-byte` | 装飾の半径を角度と同じバイトから取る | **緑**（70 passed: test_determinism / test_layout） | 赤（4 failed） |
| `RADIAL-full-length` | 放射線を紋の中まで引く（extent を無視） | **緑**（110 passed） | 赤（1 failed） |
| `SEQ-zero-accepted-is-untested` | `seq < 1` を拒むようにする | **緑**（126 passed・スナップショット含む） | 緑 |
| `STATE-ring-needs-core` | 核が無ければ state 環を描かない | **緑**（114 passed・スナップショット含む） | 緑 |
| `DELEGATE-line-from-core-only` | 核が無い circle の delegate 破線を小円上で潰す | **緑**（90 passed・スナップショット含む） | 緑 |
| `DOT-accent-fill-dead` | トレースの点の `accent_attr="fill"` を削除 | **緑**（114 passed・スナップショット含む） | 緑 |
| `STAR-le` | `star_step` の `2*j < n` を `2*j <= n` にする | 緑（90 passed・スナップショット含む） | 緑 — **等価変異**（偶数 n では j = n/2 が n を割るので gcd ≠ 1。欠陥ではない。layout.md §2.1 の n=6 の説明「探索範囲に入らない」は正しいが、`<=` でも結果は同じであることは書かれていない） |
| `OVL-no-break` | 段を見つけても止まらず全段を強調する | 赤（4 failed） | — |

特に `AWAIT-*` の 2 件は「欠けが**どの紋**の角度にあるか」（要件書 §2.5「`await` の紋の角度に、境界環の欠けを作る」）を
何も固定していないことを示す。`test_await_cuts_the_boundary_ring` に、弧の切れ目の角度が `publish`（tools[3]・6 時）を挟むこと、
または刻印の角度と欠けの角度が一致することのアサーションを足すのが安い。

実装者ハーネス `phase3-mutations/mutate_p3.py` は 42 エントリ（`grep -c '^    ("'` で確認。「42/42」の分母と一致）。
本レビューでは再実行していない（`mkdtemp()` が `/tmp` に落ちるため）。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 実物 | 参照 |
|---|---|---|
| implementation-notes P3-7 の 5「loop の辺にも矢じりを付けた … 矢じりが無いと訪問順を目で追えない」 | 矢じりは j → j+k を指し、n=5 で S0→S2。訪問順（S0→S1）とは一致しない | F-C-P3-002 |
| layout.md §2.1「辺の順は訪問順（`flow.steps` の配列順）に一致させる」と同節末尾「辺は節 j から節 (j+k) mod n」 | 同じ節の中で食い違う。実装は後者 | F-C-P3-002 |
| layout.md §7.2「`summon` なら入れ子の小陣の外枠」/ §7.3「tool 行が紋を強調する」 | summon の tool 行で朱くなるのは放射線だけ。外枠に当たる要素は無い | F-C-P3-003 |
| layout.md §7.5「`seq`（int・1 始まり）」 | `read_trace` は 0 / 負数を受理する | F-C-P3-004 |
| layout.md §2.2 / ornament.py「24 バイト目まで」 vs test_determinism「25 バイト目まで」 | 実際は添字 24 = 25 バイト目 | F-C-P3-009 |
| layout.md §4 / conformance §2.24.1「最大座標（1300 px 級）」 | キャンバスは 1000 px 角で最大座標は 1000 px 級 | F-C-P3-010 |
| test_overlay.py の「規則 2（祖先一致）」「規則 4（referent 規則）」 | layout.md §7.1 の項目は 3 つで番号が対応しない | F-C-P3-008 |
| implementation-notes P3-2「壊れた行は … 黙って読み飛ばさない」 | 壊れていない行（U+2028 を含む JSON 文字列）を壊れていると報告する | F-C-P3-001 |
| implementation-notes P3-1「1005 passed」 | worktree で 1005 passed を実測（一致） | — |
| implementation-notes P3-1「42/42 caught」 | ハーネスのエントリ数 42 は一致。caught の再実測はしていない | — |
| decision-conformance §2.24.3 の確定値（核 0.12 / 紋 0.06 / state 0.05 / 刻印 0.12 / 欠け 16 度 / delegate 0.05・0.82 / 縮尺 0.28 / 点 0.03 / 矢じり 0.05 / exit 0.05 / rune 0.05・43 文字 / トレース 1.10・0.025） | `geometry.py` / `layout.py` の定数と一致（一致） | — |
