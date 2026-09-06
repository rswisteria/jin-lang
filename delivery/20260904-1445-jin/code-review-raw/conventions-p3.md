# Stage 5 review: conventions — Phase 3 (jin-render)

レビュア: review-p3-conventions（Stage 5・観点 conventions）／ 2026-09-06
対象: ブランチ `feat/jin-phase3-render`（worktree `/home/wisteria/jin-lang/.claude/worktrees/jin-phase3-6`・ベース origin/main `32c215e`）。
**レビュー対象はレビュー開始時点の `git diff origin/main` と未追跡ファイル一覧**（ブリーフ記載の 11 変更 + 6 未追跡）。
作業中に他エージェント（auto-decider-p3 / main）が worktree に加えた変更（`auto-decisions.*` / `auto-review.html` /
`implement-ledger.md` / `docs/pending-decisions.md` / `docs/adr/ADR-019` / `ADR-020` / `implementation-plan.json` の `decision_record` 追記）は
本レビューの対象外。本レビューが worktree に書いたのはこのファイル 1 本だけ。

## 実測した環境・コマンド（隔離コピーのパス・件数）

| 項目 | 値 |
|---|---|
| 隔離コピー（読み取り・ベースライン） | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-conventions/`（`.venv` / `.git` / `__pycache__` を除いて rsync） |
| 隔離コピー（変異用） | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-conventions-m/`（変異ごとに書き換え → 復元。最後に `diff -rq` で pristine と同一を確認） |
| インタプリタ | worktree の `.venv/bin/python`（Python 3.14.7）。`PYTHONPATH` にコピー側 `packages/*/src` 4 本を前置し、`PYTHONDONTWRITEBYTECODE=1` / `-p no:cacheprovider` / `__pycache__` 削除 |
| `ruff check --no-cache <copy>` | All checks passed! |
| `ruff format --check --no-cache <copy>` | 77 files already formatted |
| `pytest`（全体・コピー上） | **1005 passed**（0 failed / 0 skipped・6 snapshots passed・30.88s） |
| `mutate_p3.py`（コピー上・`TMPDIR` をジョブ tmp に向けて実行） | **42/42 mutations caught**（baseline 210 passed・EXPECT_GREEN 1 件を含む。implementation-notes P3-5 の主張と一致） |
| `implementation-plan.json` の schema 検証 | `jsonschema` 4.26.0 / `implementation-plan.schema.json`（bundle 0.5.0）で **errors 0**。`scope_labels = ["backend-unit-verified"]` は enum 内。P3 追加の skill_plan 2 / tasks 3 / domain_checks 3 はすべて `jin_phase: 3` を持つ |
| 独自変異プローブ | `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-conventions-scripts/{probe.py,mutate_probe.py}`（M1〜M7 + guard 削除。結果は各 finding と「偽 green 候補」に記載） |
| worktree の不変性 | `git status --short` に本ファイル以外の本レビュー由来の変更なし（`diff -rq packages <copy>/packages` = 同一） |

規約チェックリスト（CLAUDE.md）に対する結論を先に書く:

- パッケージ追加チェックリスト 7 点: **全部満たしている**（ルート `pyproject.toml` 5 箇所 / `packages/jin-cli/pyproject.toml` / `packages/jin-render/tests/__init__.py`）。layers は `"jin_adk | jin_render"` の 1 要素。forbidden 2 本に `jin_render` 追加。契約名に `google-adk` の語を残している
- 正準形規則の分散: `jin_core.canonical` に触れていない。該当なし
- 診断コードを増やさない: 新コードなし（`RenderError` は例外クラス。ただし根拠の引用先が不正確 → F-V-P3-010）
- 生成コード非編集: `agent.py.j2` / スナップショットに触れていない。該当なし
- `guard:` / `hazard:` 記法: 新規 4 主張（`fmt_coord` ×2 / `attr_value` / `text_value`）+ CLI 2 主張。**形式は正しいが、走査対象に `jin_render` が入ったことを固定するテストが無い**（F-V-P3-006）。`_write_svg -> path.is_symlink` は実効ガードではない（F-V-P3-005）
- テスト配置 ADR-003: パッケージ単体 / `tests/contract/` の切り分けは守られている（`jin_adk` を import するのは `tests/contract/test_render_contract.py` だけ）
- `layout.md` の `machine-readable` ブロック 2 本（`ring-radii` / `data-jin-kinds`）: **書式不変**。§3 の 9 種表の直後に §3.1 を足しているがブロックの外。`tests/spec/test_spec_consistency.py` 緑

## Findings

### F-V-P3-001 [confidence 90] `DASH` 定数が `fmt_coord` を通らない数値の第 2 経路であり、正規表現テストはそれを一度も見ていない
- 場所: `packages/jin-render/src/jin_render/svg.py:52`（`DASH = "6.000 4.000"`）、`layout.py:173,430,499,750`（`stroke-dasharray` に直接埋める）、`docs/spec/layout.md` §4「座標を SVG へ書き出す経路は必ず丸め関数 1 本を通す … 実装は `jin_render.svg.fmt_coord`」、`svg.py` モジュール docstring「座標を SVG に書き出す経路は `fmt_coord` 1 本だけ」、`decision-conformance.md` P3 行「`jin_render.svg.fmt_coord` が唯一の書き出し口」
- 内容: `stroke-dasharray` は `test_layout.py::NUMERIC_ATTRS` に「幾何・体裁属性」として列挙されており、規約上は丸め関数の対象である。しかし値は手書きリテラルで、`COORD_DECIMALS` を変えても追従しない（`DET-two-decimals` 変異では他の数値が先に落ちるので気づかない）。仕様（§4）・docstring・conformance 行の 3 箇所が「1 本」と主張しているので、仕様側とコード側の同じ欠陥として扱う
- 変異検証: **M3** `DASH = "6 4"` にして `test_layout.py -k three_decimals` → **2 passed（緑のまま）**。理由: examples 2 本の root 描画には破線要素（未解決参照 / `delegate` / JIN070 の印 / root 未解決）が 1 つも現れず、`stroke-dasharray` 属性が SVG に出ないため正規表現検査が空振りする。layout.md §4 の「幾何・体裁属性の数値がすべて 3 桁で終わることを正規表現で検査できる」は、examples に現れる属性についてしか成立していない
- 提案: (1) `DASH` を `f"{fmt_coord(6.0)} {fmt_coord(4.0)}"` のように `fmt_coord` で組む（定数の初期化時に 1 回評価すれば決定性は変わらない）。(2) `test_all_geometry_numbers_are_written_with_three_decimals` に破線が出るモデル（未解決 `summon` + `delegate`）を 1 本足す、または「`NUMERIC_ATTRS` の各属性が少なくとも 1 回現れた」ことを assert して空振りを検出する

### F-V-P3-002 [confidence 90] `test_a_hostile_circle_name_cannot_break_out_of_an_attribute` は空虚（circle 名は SVG に一切出ない）。`svg.py` docstring の「入力」列挙も過大
- 場所: `packages/jin-render/tests/test_layout.py:421-424`、`packages/jin-render/src/jin_render/svg.py` モジュール docstring「circle 名 / tool 名 / state 名 / rune / pointer は `.jin` 由来の入力である」
- 内容: 実測（probe.py）: `ZZNAME` / `ZZTOOL` / `ZZSTATE` を名前に持つモデルを render しても SVG に **どれも現れない**（`data-jin` は添字 pointer、`data-jin-seq` は int）。SVG に流れる `.jin` 由来の文字列は **rune のテキストノードだけ**。したがって「敵対的な circle 名が属性から抜け出さない」テストは、属性エスケープを外しても通る名前と実効ガードの不一致（DP-REVIEW-JIN-007 型）。docstring が列挙する 5 種のうち 4 種は SVG に出ないので主張が実装より広い（Phase 2 で問題になった「docstring の旧前提文」型）。これはセキュリティの穴ではない（入力が属性値に流れていないことの裏返し）が、属性エスケープの実効カバレッジが `test_svg.py` の単体テスト 3 本（`test_attribute_escaping_closes_the_tag_injection` / `test_attribute_escaping_keeps_double_quotes_as_the_delimiter` / `test_ampersand_is_escaped_before_the_other_entities`）だけであることは明記しておく
- 変異検証: **M1** `attr_value` を素通し（`return value`）→ `test_layout.py -k hostile_circle_name` **1 passed（緑）**。**M1b** `-k hostile`（rune 側も含む 2 本）→ **2 passed（緑）**。rune は `text_value` を通るので属性側の変異では落ちない。属性側を落とすのは `test_svg.py::test_attribute_escaping_*` だけ（mutate_p3 の `ESC-attr-passthrough` が RED になるのはそちらの 3 本）
- 提案: テストを削除するか「circle 名は SVG に出ない」ことを主張する名前（`test_names_are_not_emitted_into_the_svg`）に変えて、実際に `name not in svg` を assert する。docstring は「rune（テキストノード）と、将来属性に流れうる値」に書き直す。将来 `title` / `aria-label` に名前を出すときの受け皿として `attr_value` を残すなら、その旨を書く

### F-V-P3-003 [confidence 90] `test_every_live_pointer_resolves_for_each_focus` の名前は「全 pointer が解決する」だが、本体は「1 行でも解決すれば良い」
- 場所: `tests/contract/test_render_contract.py:150-155`
- 内容: docstring は「少なくとも 1 つの行が解決すること（描画が空になっていない側の確認）」と正直に書いているが、関数名は `every_live_pointer_resolves` であり、`test_every_live_pointer_resolves_at_the_root_focus`（本当に全件を assert する）と並べると読み手が同じ強さの検査だと誤読する。DP-REVIEW-JIN-007 型
- 変異検証: **M2** `data-jin-ref` 属性の出力を消す → `-k "for_each_focus or at_the_root_focus"`: `at_the_root_focus` **1 failed**（`seq=3 /circles/4/core が解決しない`）、`for_each_focus[Pipeline/Refine/Drafter]` **3 passed（緑のまま）**
- 提案: `test_at_least_one_live_pointer_resolves_for_each_focus` に改名する。あるいは焦点ごとに「解決すべき pointer の期待集合」を書いて全件 assert にする

### F-V-P3-004 [confidence 85] トレース行のエラーメッセージが 0 始まりの「N 行目」で、同じコマンド内の JSON エラー（`path:N:`・1 始まり）と基数も書式も違う
- 場所: `packages/jin-render/src/jin_render/overlay.py:41-55`（`f"トレースの {index} 行目 …"`・`enumerate(rows)` の 0 始まり）、`packages/jin-cli/src/jin_cli/main.py:858-873`（`f"{path}:{number}: …"`・1 始まり）
- 内容: 実測（probe.py）: `read_trace([{"seq": "1", "pointer": None}])` → `トレースの 0 行目の seq が整数ではありません: '1'`。CLI では `_read_trace_rows` が空行を読み飛ばしてから渡すので、この `index` はファイルの行番号とも一致しない（空行があるとずれる）。CLAUDE.md「診断の行・列は 1 始まり」の規約と、同じ `jin render --trace` の 2 種類のエラーが別書式になる点の両方に反する。`test_a_trace_row_with_the_wrong_types_exits_two` はメッセージを見ていないので機械では捕まらない
- 変異検証: 該当テスト無し（メッセージを assert するテストが存在しない）
- 提案: `read_trace` は「何番目の要素か」を 1 始まりで報告する（`enumerate(rows, start=1)`）か、CLI 側で行番号を持ち回って `path:N:` 書式にそろえる（`_read_trace_rows` が `(line_number, row)` を持ち `overlay` は添字だけ返す、など）。メッセージを assert するテストを 1 本足す

### F-V-P3-005 [confidence 80] `guard: _write_svg -> path.is_symlink` は同じ docstring が「文言のため」と認める判定を `guard:` として主張している（実効ガードではない）
- 場所: `packages/jin-cli/src/jin_cli/main.py:57,884`（主張）、`main.py:878-880`（docstring「事前判定は文言のためで、実際の防御は `_write_atomically` の …」）、`delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py` `EXPECT_GREEN = {"CLI-follow-symlink-upfront-only"}`
- 内容: CLAUDE.md は `guard:` を「危険な操作に対する**防御**の所在」の記法と定めている（`hazard:` は危険の所在）。`_write_svg` の `path.is_symlink()` は、実装者自身が docstring で「文言のため」と書き、変異ハーネスでも「消しても緑が正しい」と宣言している。つまり **`guard:` の名指し先が防御として効いていない**ことが実測で示されているのに `guard:` で主張している。`test_guard_claims.py` はトークンが関数内に在ることしか見ないので通る。DP-REVIEW-JIN-007 型（名前と実効ガードの不一致）。付随して、`_write_svg` の `SymlinkWriteRefused` はパスを含まず、二層目（`_write_atomically`）の同名例外は `: {path}` を含むため、二層目が発火したときの CLI 出力は `out.svg: シンボリックリンクなので書き込みを拒みました: out.svg` とパスが 2 回出る
- 変異検証: mutate_p3 の `CLI-follow-symlink-upfront-only`（事前判定だけを消す）→ **GREEN（実装者も期待どおりとしている）**。実効ガードは `_write_atomically` の `Path(path).is_symlink`（`guard: _write_atomically -> Path(path).is_symlink` として既に主張済み）
- 提案: `_write_svg` の主張を `guard: _write_svg -> _write_atomically(path,text,allow_create=True)` の 1 本にし、事前判定は「利用者向けメッセージのための早期判定（防御ではない）」と散文で書く。または事前判定そのものを消して二層目のメッセージ 1 本にする（パスの二重表示も消える）

### F-V-P3-006 [confidence 80] `guard:` 走査の網羅テストは部分集合比較で、`jin_render` に主張が在ることを誰も固定していない
- 場所: `tests/contract/test_guard_claims.py:96-105`（`{main.py, build.py, runtime.py, codegen.py} <= found`）
- 内容: ブリーフの「契約テストが宣言してあるだけ」型。`svg.py` の `guard:` 4 主張は `test_guard_claims_point_at_real_guards` の parametrize に自動で入るが、**主張を全部消しても** 網羅テストは `<=` なので通り、parametrize の要素が 1 つ減るだけで誰も気づかない。`MINIMUM_TOTAL_CLAIMS = 15` も main.py だけで超える。Phase 3 で走査対象が 1 パッケージ増えたのに、期待集合が Phase 2 のまま
- 変異検証: 変異用コピーで `svg.py` から `guard:` 行を全削除（`sed -i '/guard: /d'`・残 0 件）→ `tests/contract/test_guard_claims.py` **22 passed（緑のまま）**
- 提案: 期待集合に `"jin-render/src/jin_render/svg.py"` を足す（`<=` のままでよい）。Phase 4 で `jin_lsp` を足すときも同じ 1 行を足す運用を CLAUDE.md のチェックリスト（または `phase3-handoff` 相当）に書く

### F-V-P3-007 [confidence 80] `data-jin-kind` の個別の値はどのテストにも固定されていない（集合一致と「全 9 種が現れる」だけ）
- 場所: `packages/jin-render/tests/test_layout.py:74-117`、`docs/spec/layout.md` §7.2 の表（pointer → kind）、§3 の 9 種表（対象列）
- 内容: kind を要素間で入れ替える変異（例: `flow.exit` の菱形を `flow-edge` から `core` に）は、値が 9 種の中にあり、かつ他の要素で全 9 種が出続ける限り全部通る。kind を個別に assert しているのは `await`（`test_await_cuts_the_boundary_ring`）とトレースの点（`circle`）と装飾（`rune`）の 3 箇所だけ。layout.md §7.2 の「pointer 列 → kind」の表と §3 の「kind → 対象」の表はコードと一致している（読解で確認）が、機械では縛られていない。Phase 5 のエディタは kind でヒットテストの種別を判定するので、仕様表とコードのドリフトはここで止めたい
- 変異検証: **M6** `flow.exit` の印の `kind="flow-edge"` → `"core"` にして `test_layout.py test_overlay.py -k "nine or exit_mark or kind"` → **5 passed（緑のまま）**
- 提案: 「pointer の末尾セグメント → 期待 kind」の対応表テスト 1 本（`/core`→`core`、`/tools/N`→`tool`、`/state/N`→`state`、`/flow`・`/flow/exit`・`/flow/steps/N`→`flow-edge`、`/boundary/guards/N`→`guard`、`/boundary/await/N`→`await`、`/delegate/N`→`delegate`、`/instruction/rune`→`rune`、`/circles/N`→`circle`）を examples + 合成モデルで回す。layout.md §7.2 の表をそのまま写せる

### F-V-P3-008 [confidence 85] 丸め桁数の根拠にある「キャンバス内の最大座標（1300 px 級）」は 1000 px 角キャンバスと矛盾し、実測とも合わない
- 場所: `docs/spec/layout.md` §4 根拠 2、`decision-conformance.md` §2.24.1 根拠 2 と P3 行、`packages/jin-render/tests/test_svg.py::test_rounding_step_is_far_above_the_float_noise`（`largest = 1300.0`）、`implementation-notes.md` P3-3 の表。auto-decider が書いた `DP-IMPL-JIN-P3-ROUNDING-01` の `decision_record.constraints[0]` にも同じ「最大座標 1300 px 級」が転記されている
- 内容: 同じ段落が「キャンバスは 1000 px 角（`viewBox="0 0 1000 1000"`）」と書いており、実測（probe.py）でもスナップショット 4 本に現れる数値の最大は **1000.000**（ベジェの制御点を含めても境界環 0.95 の弧の制御点は約 933 px）。1300 の出所が無い。値としては保守側（ULP が大きくなる方向）なので結論は変わらないが、ブリーフの「根拠とコードの一致」の観点で、根拠に書いた数が実装から導けない。テストの `largest` も `geo.CANVAS_PX` から導いていない
- 変異検証: 該当なし（数値の根拠の問題）
- 提案: 「最大座標は 1000 px（キャンバスの縁）。1 ULP は約 1.1e-13 px」に直し、テストは `largest = geo.CANVAS_PX` から導く。auto-decider の constraint 文も追従が要る（親へ申し送り）

### F-V-P3-009 [confidence 70] `test_layout.py` が `__import__("xml.etree.ElementTree", …)` を使っている（リポジトリの検出器が「動的 import」と見なす形）
- 場所: `packages/jin-render/tests/test_layout.py:136`
- 内容: `tests/contract/test_packaging_contract.py::test_dynamic_import_detector_sees_each_form` は `__import__` を検出対象の 1 形として扱い、CLAUDE.md は動的 import を 2 モジュールに閉じ込めることを規約にしている。検出器の走査対象は `src` だけなのでテストは通るが、`conftest.py` が既に `import xml.etree.ElementTree as ET` しているのに、同じテストファイルで `__import__` を使う理由が無い。grep で `__import__` を探した読み手がテストにヒットして手を止める
- 変異検証: 該当なし
- 提案: `from .conftest import parse` または `import xml.etree.ElementTree as ET` に置き換える

### F-V-P3-010 [confidence 65] 「診断コード（JINxxx）は増やさない」の根拠として `docs/spec/model.md` §3.3 を引いているが、§3.3 は State の `output_key` に限った文
- 場所: `packages/jin-render/src/jin_render/layout.py:76`（`RenderError` docstring）、`docs/spec/layout.md` §5 末尾、`packages/jin-cli/src/jin_cli/main.py:935`（コメント）
- 内容: model.md §3.3 は「`out: true` が 2 件以上のとき、v1 では診断コードを増やさず Phase 2 のコード生成時エラーとして落とす（DP-JIN-SEMANTIC-GAPS-01 が認めた新規コードは 2 件のみ）」という**個別ケース**の記述であり、一般規則ではない。一般規則の所在は CLAUDE.md（「診断コードは増やさない」）/ `docs/adr/ADR-012-DP-JIN-DIAGCODE-NUMBERING-01.md` / `docs/spec/adk-mapping.md` §3.1。引用先が違うと、§3.3 を書き換えた人が描画側の規則を壊した気になれない（逆も同じ）
- 変異検証: 該当なし
- 提案: 3 箇所の引用を `CLAUDE.md`「診断コードは増やさない」と ADR-012 に向ける

### F-V-P3-011 [confidence 60] `# noqa: TRY004` と「ruff TRY004 を意図的に外す」のコメントは、有効化されていない規則を指している
- 場所: `packages/jin-render/src/jin_render/overlay.py:36-43,50`
- 内容: ルート `pyproject.toml` の `[tool.ruff]` は `line-length` / `target-version` / `extend-exclude` だけで `select` が無く、既定の E/F 系しか走らない。`TRY004` は無効なので `noqa` は何も抑止しておらず、コメントは「ruff が指摘する」という前提を読み手に与える。Phase 2 の `resolver.py:89` の `# noqa: BLE001` も同じ状態なので、リポジトリ内では一貫している（precedent あり）。将来 `select` を広げるまでは無害
- 変異検証: 該当なし（`ruff check` は変異前後とも All checks passed）
- 提案: コメントを「`TypeError` ではなく `ValueError` を選ぶ理由」だけにして `noqa` を外す。または `[tool.ruff.lint] select` を明示して `TRY` を有効にし、`noqa` を意味のあるものにする（後者は既存コードの再点検が要るので Phase 4 以降）

### F-V-P3-012 [confidence 60] 装飾が読むハッシュのバイト数の表記が「24 バイト目」と「25 バイト目」で割れている
- 場所: `packages/jin-render/src/jin_render/ornament.py` docstring「`1 + 3 * 7 + 2 = 24` バイト目までしか使わない」、`docs/spec/layout.md` §2.2「最大でも 24 バイト目まで」、`packages/jin-render/tests/test_determinism.py:127`「25 バイト目までしか使わない」
- 内容: 最大添字は 24（0 始まり）= 25 バイト目。docstring と仕様は添字を「バイト目」と呼び、テストは序数で数えている。どちらも 32 バイト以内なので実害は無いが、仕様側とコード側の数え方を揃える規約に反する
- 変異検証: **M4** `base = 10 + index * 3` にする → `test_the_ornament_never_reads_past_the_digest` **1 failed（IndexError）**。テストは名前どおり範囲外読みを捕まえる（空虚ではない）
- 提案: 3 箇所を「添字 24 まで（25 バイト）」に統一する

### F-V-P3-013 [confidence 60] `implementation-plan.json` の `$comment` がラウンド 2 の extend までしか記録していない
- 場所: `delivery/20260904-1445-jin/implementation-plan.json` 2 行目
- 内容: 「実装ラウンド 2/5 が 2026-09-05 に extend した（impl-p2）」で終わっており、ラウンド 3（impl-p3・2026-09-06）の追記が無い。extend 規律（既存要素を消さない・追記する）自体は守られている（schema errors 0・既存 tasks/skill_plan/milestones の削除なし・`round` は「現在のラウンド」なので書き換えが正しい）。`pipeline_e2e` を `passed` → `not_run` に戻したのは既存値の書き換えだが、申し送り §10 の指示どおりで `evidence[]` に理由を残している
- 変異検証: 該当なし
- 提案: `$comment` に「実装ラウンド 3/5（Phase 3・jin-render）が 2026-09-06 に extend した（impl-p3）」を追記する

### F-V-P3-014 [confidence 60] `test_layout.py` に読み手を止める書き方が残っている（恒等関数 `radii_or` / 未使用の `enumerate` / `approx in list`）
- 場所: `packages/jin-render/tests/test_layout.py:207-213`（`radii_or(values)` は `return values`）、`:242-243`（`for position, element in enumerate(...)`: `_ = position`）、`:207-209`（`pytest.approx(x) in list`）
- 内容: `radii_or` は名前が何も意味せず本体は恒等。`enumerate` の添字を捨てるための `_ = position`。`approx in list` は `__eq__` 経由で動くが読み手が一瞬迷う。いずれも動作には影響しないが、Phase 2 のレビューで「テスト側の誤りを直した痕跡」が残る型と同じ
- 変異検証: 該当なし
- 提案: `radii_or` を消して `full` を直接見る。`enumerate` を外す。`assert any(r == pytest.approx(...) for r in full)` の形に書き換える

### F-V-P3-015 [confidence 55] `_write_svg` の「`jin fmt` / `jin build` と同じ規約」は build と一致していない（build は umask を尊重する `os.open(0o644)`、render は `os.chmod(0o644)`）
- 場所: `packages/jin-cli/src/jin_cli/main.py:876`（docstring）、`main.py:384-390`（`os.chmod(temporary, 0o644)`）、`implementation-notes.md` P3-7 項 9（差異を自認）
- 内容: implementation-notes は「render だけが build より緩い方向にずれる。この差を許容してよいかは Stage 5 の判断に委ねる」と正直に書いているのに、コードの docstring は「同じ規約」と書く。docstring と記録の不一致（Phase 2 の「docstring の旧前提文」型）。差そのものの是非は security / correctness の観点に委ねる
- 変異検証: 該当なし（`test_the_output_file_is_created_with_the_generated_file_mode` は 0644 を固定している）
- 提案: docstring を「tmp + `os.replace` / リンクを辿らない / `--force` 無しで拒む、は `fmt` と共有。新規作成のモードは umask を無視した 0644（`build` の `os.open` と異なる・P3-7 項 9）」と事実どおりに書く

### F-V-P3-016 [confidence 50] 成功メッセージだけ `_safe` を通していない（同じ関数の失敗経路は `_safe(str(out))`）
- 場所: `packages/jin-cli/src/jin_cli/main.py:954`（`typer.echo(f"書き出しました: {out}")`）、`:951`（`_safe(str(out))`）
- 内容: `build` の `書き出しました: {path}`（`main.py:665`）も同じなので、コマンド間では一貫している。ただし同じ関数内で失敗経路だけ `_safe` を通すのは読み手に「どちらかが漏れ」に見える。`out` は利用者自身の引数なので実害は低い
- 変異検証: 該当なし
- 提案: `_safe(str(out))` にそろえる（`build` 側も同時に）

### F-V-P3-017 [confidence 50] layout.md §6「実装は `jin_render.geometry`（定数）と `jin_render.layout`（描き方）」に対し、`ARROW_HEAD` / `RUNE_MAX_CHARS` / `RUNE_ELLIPSIS` は `layout.py` にある
- 場所: `docs/spec/layout.md` §6 冒頭、`packages/jin-render/src/jin_render/layout.py:63-70`
- 内容: §6 の表の値のうち矢じり 0.05 と rune 43 文字は `geometry.py` に無い。定数の所在を仕様が名指ししている以上、探した人が見つからない。`RUNE_MAX_CHARS` が `geo.RING_INSTRUCTION / geo.RUNE_FONT` から導出される点は妥当
- 変異検証: 該当なし
- 提案: `ARROW_HEAD` を `geometry.py` に移す（`RUNE_MAX_CHARS` は導出値なので layout に残し、§6 に「導出値は `layout.py`」と 1 語足す）

### F-V-P3-018 [confidence 50] `layout.__all__` が `fired_indices` / `fit_rune` / `RUNE_*` / `ARROW_HEAD` を公開しており、「`render` が唯一の入口」の主張と幅が違う
- 場所: `packages/jin-render/src/jin_render/layout.py:763-772`、`__init__.py` docstring「`render` が唯一の入口」
- 内容: `__init__.py` の `__all__` は 4 名（`COORD_DECIMALS` / `DATA_JIN_KINDS` / `RenderError` / `render`）に絞られており、これは主張と一致する。`layout.__all__` が広いのはテストが直接 import するため。Phase 4 の `jin_lsp` が `jin_render.layout.fired_indices` を直接呼ぶ道が開いている
- 変異検証: 該当なし
- 提案: `layout.__all__` から `fired_indices` / `fit_rune` を外して `_` 接頭にするか、`__init__.py` に「サブモジュールの名前はテスト用で契約ではない」と 1 行書く

### F-V-P3-019 [confidence 50] layout.md §7.5「`seq`（int・1 始まり）」は記述であって検証ではない（0 / 負 / 重複の `seq` は受理される）
- 場所: `docs/spec/layout.md` §7.5、`packages/jin-render/src/jin_render/overlay.py:29-58`
- 内容: `read_trace` は int 型だけを検査し、`seq <= 0` も重複も通す（docstring は重複を明示的に許容）。仕様が「1 始まり」と書くと読み手は拒否されると期待しうる。`jin run` の出力は常に 1 始まりなので実害は薄い
- 変異検証: 該当なし
- 提案: §7.5 を「`seq` は int（`jin run` は 1 始まりで振る。`jin_render` は値の範囲を検査しない）」と書き分ける

### F-V-P3-020 [confidence 45] ライブラリコードに `assert` が 2 箇所（`-O` で消える前提条件）
- 場所: `packages/jin-render/src/jin_render/layout.py:278,514`
- 内容: `_await_angles` / `_flow_extent` の `assert circle.boundary is not None` / `assert circle.flow is not None`。呼び出し側が None を弾いてから呼ぶので到達しないが、`-O` で消える文を型の絞り込みに使うのは CLAUDE.md「schema を通るモデルなら例外を投げない」の観点では中立、規約としては `jin_core.parser.py:167` に 1 件の precedent がある
- 変異検証: 該当なし
- 提案: 引数の型を `Boundary` / `Flow` にして呼び出し側で渡す（assert が要らなくなる）

### F-V-P3-021 [confidence 45] `test_the_svg_uses_no_elliptical_arc_command` の正規表現 `\bA[ \-0-9]` は rune 本文の英語（例 `A tool`）に誤反応する
- 場所: `packages/jin-render/tests/test_layout.py:148-151`
- 内容: SVG 全文を対象にしているので、`<textPath>` のテキストに `A ` が入るモデルで偽陽性になる。researcher の rune は日本語なので現状は通る。検査対象は `d` 属性の値に限るべき
- 変異検証: 該当なし
- 提案: `d` 属性だけを集めて `re.search(r"\bA\b", d)` を見る

### F-V-P3-022 [confidence 40] `test_determinism.py` の関数内 import（`import os` / `from jin_core.check import check_file`）
- 場所: `packages/jin-render/tests/test_determinism.py:36,97`
- 内容: モジュール先頭に `from .conftest import EXAMPLES, model_from, trace_rows` があり、`load_model` も conftest にあるのに関数内で `check_file` を import している。`_src_path` の `import os` も関数内。ruff の既定規則では指摘されない。読みやすさだけの問題
- 変異検証: 該当なし
- 提案: 先頭に寄せる。`test_two_renders_in_one_process_are_byte_identical` は `load_model` を使う

### F-V-P3-023 [confidence 55] implementation-notes P3-8「`packages/jin-cli/tests/test_cli.py` の既存 42 件は全緑」の 42 が実物と合わない
- 場所: `delivery/20260904-1445-jin/implementation-notes.md` P3-8 項 4
- 内容: `test_cli.py` の `def test_` は 65 本（parametrize 展開でさらに増える）。「42 件」がどの時点・どの数え方か記録に無い。全緑であること自体はベースライン（exit 0）で確認できたが、件数の主張は検証できない
- 変異検証: 該当なし
- 提案: 件数を書くなら `pytest packages/jin-cli/tests/test_cli.py -q` の実測値と日時を書く（Phase 2 の記録が「696 passed」等と実測値で書いているのと同じ流儀）

### F-V-P3-024 [confidence 60] layout.md 冒頭「§1〜§4 は Phase 0 で確定、§5〜§7 は Phase 3」は実際の追記範囲と合わない
- 場所: `docs/spec/layout.md` 3-5 行目
- 内容: Phase 3 の追記は §1（環を描く条件）/ §2.1（実装参照）/ §2.2（ハッシュの使い方の表）/ §3.1（契約の範囲）/ §4（丸め桁数・ベジェ・transform）/ §5〜§8 に及ぶ。§4 の丸め桁数は Phase 3 の中心的な確定値であり、「§1〜§4 は Phase 0」と読んだ人が §4 を Phase 0 の確定事項と誤認する
- 変異検証: 該当なし
- 提案: 「§1〜§3 の骨格と §4 の『丸め関数 1 本』は Phase 0。各節の『Phase 3 で確定』『実装で確定した値』と印した部分と §5〜§8 は Phase 3」と書く

### F-V-P3-025 [confidence 60] `test_every_pointer_resolves_in_the_model` は `data-jin` 欠落を `""`（ルート）に潰すので単独では欠落を検出しない
- 場所: `packages/jin-render/tests/conftest.py:58`（`element.get("data-jin", "")`）、`test_layout.py:83-89`
- 内容: 実測: `pointer_exists(document, "")` は `True`。`data-jin` を落とした要素は `""` に化けてこのテストを通り、検出は隣の `test_every_element_carries_both_attributes` に依存する。テスト名は「全 pointer が解決する」だが、欠落は解決扱いになる。mutate_p3 の `CONTRACT-core-no-pointer` が RED になるのは `carries_both_attributes` 側
- 変異検証: mutate_p3 `CONTRACT-core-no-pointer` の failed 5 件の内訳は未確認（`-k` に両方を含めているため）。`pointers()` の既定値の問題は読解で確定
- 提案: `pointers()` を `element.get("data-jin")` にして `None` を返し、テスト側で `assert pointer is not None` を先に置く（`""` への潰しをやめる）

## 変異で緑のままだったテスト（偽 green の候補）

| 変異 | 対象テスト | 結果 | 意味 |
|---|---|---|---|
| M1: `attr_value` を素通し | `test_layout.py::test_a_hostile_circle_name_cannot_break_out_of_an_attribute` | **1 passed** | circle 名が SVG に出ないので空虚（F-V-P3-002） |
| M1b: 同上 | `test_layout.py -k hostile`（rune 版を含む 2 本） | **2 passed** | 統合テストは属性エスケープを一切見ていない。単体 `test_svg.py` だけが守る |
| M3: `DASH = "6 4"` | `test_layout.py::test_all_geometry_numbers_are_written_with_three_decimals` | **2 passed** | examples に破線が出ないので `stroke-dasharray` は検査されない（F-V-P3-001） |
| M6: `flow.exit` の印を `kind="core"` に | `test_layout.py` / `test_overlay.py -k "nine or exit_mark or kind"` | **5 passed** | kind の個別値は固定されていない（F-V-P3-007） |
| M2: `data-jin-ref` を出さない | `test_render_contract.py::test_every_live_pointer_resolves_for_each_focus[×3]` | **3 passed**（同時に `..._at_the_root_focus` は 1 failed） | 名前と実効検査の不一致（F-V-P3-003） |
| guard 削除: `svg.py` の `guard:` 行を全削除 | `tests/contract/test_guard_claims.py` | **22 passed** | 走査の網羅テストが部分集合比較（F-V-P3-006） |
| mutate_p3 `CLI-follow-symlink-upfront-only` | `test_render.py::test_a_symlinked_output_is_refused` | GREEN（実装者が期待） | `guard: _write_svg -> path.is_symlink` は実効ガードではない（F-V-P3-005） |

赤くなった（非空虚を確認した）もの: M2 の root 版（1 failed）、M4 装飾の範囲外読み（IndexError で 1 failed）、M7 トレースの点の pointer を `/circles` に変える（`test_a_trace_never_changes_the_pointer_contract` 1 failed）、mutate_p3 の 41 RED。

## 実装者の記録（notes / conformance / plan / layout.md）と実物の不一致

| 記録 | 記述 | 実物 | finding |
|---|---|---|---|
| layout.md §4 / decision-conformance §2.24.1 / P3 行 / notes P3-3 / auto-decider の constraint | 「キャンバス内の最大座標（1300 px 級）」 | キャンバス 1000 px 角。スナップショット 4 本の最大値は 1000.000。テストの `largest = 1300.0` はどこからも導かれていない | F-V-P3-008 |
| layout.md §4 / svg.py docstring / decision-conformance P3 行 | 「書き出し経路は `fmt_coord` 1 本」「唯一の書き出し口」 | `DASH = "6.000 4.000"` はリテラル。examples ではテストも見ていない | F-V-P3-001 |
| svg.py docstring | 「circle 名 / tool 名 / state 名 / rune / pointer は `.jin` 由来の入力」 | SVG に出るのは rune（テキスト）と添字 pointer だけ。名前は出ない | F-V-P3-002 |
| main.py `_write_svg` docstring / `guard:` 主張 | `guard: _write_svg -> path.is_symlink` | 同 docstring と mutate_p3 が「防御ではない（EXPECT_GREEN）」と認めている | F-V-P3-005 |
| main.py `_write_svg` docstring | 「`jin fmt` / `jin build` と同じ規約」 | notes P3-7 項 9 が build との差（umask）を自認 | F-V-P3-015 |
| ornament.py / layout.md §2.2 vs test_determinism.py | 「24 バイト目まで」 vs 「25 バイト目まで」 | 最大添字 24 = 25 バイト目 | F-V-P3-012 |
| layout.md 冒頭 | 「§1〜§4 は Phase 0、§5〜§7 は Phase 3」 | §1 / §2.1 / §2.2 / §3.1 / §4 / §8 にも Phase 3 の追記 | F-V-P3-024 |
| layout.md §6 冒頭 | 「定数は `jin_render.geometry`」 | `ARROW_HEAD` / `RUNE_MAX_CHARS` / `RUNE_ELLIPSIS` は `layout.py` | F-V-P3-017 |
| layout.md §5 / layout.py / main.py | 「診断コードは増やさない（model.md §3.3）」 | §3.3 は State の個別ケース。一般規則は CLAUDE.md / ADR-012 | F-V-P3-010 |
| implementation-plan.json `$comment` | ラウンド 2 の extend まで | ラウンド 3 の追記が無い | F-V-P3-013 |
| implementation-notes P3-8 | 「test_cli.py の既存 42 件」 | `def test_` 65 本 | F-V-P3-023 |
| overlay.py / layout.md §7.5 | 「`seq`（int・1 始まり）」「黙って捨てない」 | 1 始まりは検査されない。エラーメッセージは 0 始まりの「N 行目」 | F-V-P3-004 / F-V-P3-019 |

一致を確認できた記録（不一致なし）: 変異 42/42（実測一致）/ ruff 2 ゲート / schema errors 0 / `scope_labels` enum / P3 行 7 件と §2.24 の 7 小節 / HANDOFF 5 件と `undecided[]` 5 件 / 描画順（§6 の列挙と `draw_circle` の呼び順）/ `RUNE_MAX_CHARS = 43`（`fit_rune("a"*200)` は 43 文字）/ 強調色のコントラスト比 5.9:1・3.6:1（WCAG 相対輝度で再計算一致）/ `layout.md` の machine-readable ブロック 2 本の書式不変 / CLAUDE.md 依存図 `jin-lsp ← jin-cli` は design.yaml rule 5 / 6 と一致 / `tests/fixtures/traces/pipeline-fake.jsonl` 11 行。

## 補記

- `uv run pytest` 相当（コピー上・全体・`-p no:warnings`）: **1005 passed in 30.88s**（0 failed / 0 skipped・6 snapshots passed）。implementation-notes P3-1 の「1005 passed」と一致。ログ: `/home/wisteria/.claude/jobs/e2bcfe94/tmp/review-conventions-scripts/pytest-full.log`
