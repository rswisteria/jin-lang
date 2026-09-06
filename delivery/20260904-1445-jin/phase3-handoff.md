# Jin Phase 3（jin-render）への申し送り

作成: 親（`/aid auto-deliver` 実行主体）／ 2026-09-06
根拠: Issue #4 / design.yaml `implementation_phases.items[3]` / Phase 2 ラウンドの実測（`phase2-handoff.md` §6・§8）。
**Phase 3 の implementer 起動プロンプトにこのファイルのパスを渡す。** 本ファイルは Phase 2 の
`phase2-handoff.md` と同じ役割で、Issue #4 本文に書かれていない罠を集めたものである。

## 0. スコープ（design.yaml `implementation_phases.items[3]`・Issue #4）

成果物: `packages/jin-render` と `packages/jin-cli`（`render` を追加）。

完了条件（machine）は design.yaml の `verification.machine` を **verbatim** で満たす（8 項目）:

1. SVG スナップショット（正規化後）が examples 2 本について安定
2. 同一入力を 2 回レンダリングしてバイト単位で完全一致する
3. SVG 内の全要素が `data-jin` と `data-jin-kind` を持ち、全 pointer がモデルに解決できる
4. `data-jin-kind` の値が §2.5 の 9 種のいずれか
5. trace + upto を渡したとき、upto を増やすと強調要素が単調増加する（減らない）
6. focus を切り替えると展開対象の circle が変わる
7. 同一モデルを異なる `PYTHONHASHSEED` で 2 回レンダリングしてバイト一致する（辞書順序非依存の担保）
8. `instruction.rune` の SHA-256 由来の装飾が rune を変えると変わり、変えなければ変わらない

human_only（**実施しない。`not_run` として PR レビューへ送る**）: 図としての可読性・魔法陣としての見た目の妥当性。

正典（優先順）: `jin-requirements.md` §2.5 / §4 / §5（`jin render` の引数）→ `docs/spec/layout.md` →
`docs/spec/adk-mapping.md` §2.4（トレース行の pointer の形）→ `docs/spec/model.md` §6（pointer）。
判断ポイント `DP-JIN-SVG-DETERMINISM-01`（ADR-010・人間確定）は覆さない。

## 1. Phase 3 で**必ず赤くなる**テストと、その正しい直し方

`packages/jin-render/` を作った瞬間に次が赤くなる。いずれも**名指しの指示に従って直す**（テストを消さない・緩めない）:

| テスト | 直し方 |
|---|---|
| `tests/contract/test_dependency_direction.py::test_later_packages_do_not_exist_yet[jin_render]` | 意図的なトリップワイヤ。メッセージどおり下記 7 箇所を直したうえで、parametrize から `jin_render` を外す（`jin_lsp` は残す） |
| `tests/contract/test_packaging_contract.py::test_every_package_is_a_root_package` | `[tool.importlinter].root_packages` に `jin_render` |
| `::test_every_package_appears_in_the_layers_contract` / `::test_layers_contract_keeps_sibling_packages_in_one_element` | layers の `"jin_adk"` を **`"jin_adk | jin_render"`** に書き換える（素朴な直列は落とされる） |
| `::test_resolver_isolation_contract_covers_every_package_but_the_cli` | forbidden 契約「任意コード実行の実装は …に閉じる」の `source_modules` に `jin_render` |
| `::test_every_package_is_declared_in_the_workspace` / `::test_every_package_declares_the_jin_packages_it_imports` | ルート `pyproject.toml` の `[project].dependencies` と `[tool.uv.sources]`、および **`packages/jin-cli/pyproject.toml`** の `dependencies` と `[tool.uv.sources]` |
| `::test_every_package_test_directory_is_a_package` | `packages/jin-render/tests/__init__.py` |
| `test_dependency_direction.py::test_import_linter_actually_bites_on_a_forbidden_import` | `copy_sources` が `packages/*` を全部コピーするので、`jin_render` の `src/jin_render` が無いと落ちる。パッケージ構成を他と同じ `src/` レイアウトにする |

**加えて** forbidden 契約「jin_core は google-adk に依存しない」の `source_modules` にも `jin_render` を足す
（design.yaml rule 4「jin-render は google-adk に依存しない」。契約名は「jin_core / jin_render は google-adk に依存しない」等に改名してよいが、
`test_import_linter_contracts_are_declared` が `"google-adk"` を名前に含むことを見ている）。
`test_adk_version_contract.py::test_jin_adk_does_not_import_jin_cli_or_later_packages` は jin_adk 側の検査で、Phase 3 では触らない。

`uv lock` を通して **`uv.lock` をコミット**する（CI は `UV_LOCKED=1 uv sync` で stale lock を落とす。`--frozen` は付けない）。

## 2. 依存方向（design.yaml rule 4・機械で落ちる）

- `jin_render` が import してよいのは **`jin_core` と標準ライブラリだけ**。`jin_adk` は**兄弟**であり import すると layers 契約が BROKEN になる。
- したがって **トレースの型を `jin_adk.trace`（`KIND_POINTERS` / `TraceEvent` 等）から取らない**。overlay に必要なのは各行の
  `seq`（int・1 始まり）と `pointer`（str または null）だけなので、`jin_render` 側に**最小の読み取り型**を置く
  （`Sequence[Mapping[str, Any]]` を受け取り、`seq` / `pointer` 以外のキーは無視。`seq` が int でない・`pointer` が str/None でない行は
  `ValueError` で拒む＝黙って捨てない）。
- **動的 import（`importlib` / `__import__` / `exec` / `eval` / `runpy`）を `jin_render` に一切置かない**
  （`test_dynamic_imports_are_confined_to_the_cli_resolver_and_jin_run` が 2 モジュール厳密一致）。
- `jin_render` は**純関数**（DP-COMMON-07 の constraint「`jin_core` / `jin_render` はキャッシュの存在を知らない純関数のままとし、内部に状態を持たない」/
  「SVG はキャッシュしない」）。モジュールレベルの可変状態を持たない。ファイルを読まない（要件書 §4「入力は意味モデル」）。
- `packages/jin-render/tests/` からも `jin_adk` を import しない（`test_every_package_declares_the_jin_packages_it_imports` はテストも走査する）。
  トレースを使うテストは **コミット済み fixture** を読む（§4）。`jin run` を実際に回して突合する横断テストは `tests/contract/` に置く。

## 3. 公開 API と CLI

- `jin_render.render(model: JinFile, *, focus: str | None = None, trace: Sequence[Mapping[str, Any]] | None = None, upto: int | None = None) -> str`
  を**唯一の入口**にする。CLI の `jin render` と Phase 4 の `jin/renderSvg` はこの関数だけを呼ぶ（要件書 §4 最終項）。
- `focus` 省略時は `root` の circle を展開する。`focus` に存在しない circle 名が来たら例外（`jin_render.RenderError` 等・メッセージに定義済み circle 名の候補）。
  **診断コード（JINxxx）は増やさない。**
- `upto` は「`seq <= upto` のイベントまで発火済み」。`upto` 省略時は全イベント。`trace` 無しで `upto` だけ来たら拒む。
- CLI: `jin render <file> [-o out.svg] [--trace t.jsonl] [--upto N] [--focus name]`（要件書 §5）。`-o` 無しは stdout。
  `--trace` の JSONL は 1 行 1 JSON オブジェクトとして読み、壊れた行・`seq` / `pointer` の型違いは **exit 2 で拒む**（黙って読み飛ばさない）。
  `--upto` だけ・`--focus` に未定義名は usage エラー（exit 2）で、メッセージに候補を出す。
  `-o` の書き込みは既存の `jin fmt` / `jin build` と同じ規約（tmp + `os.replace`・リンクを辿らない・既存ファイルは `--force` 無しで拒む）を
  `jin_cli/main.py` の既存ヘルパで再利用する。**新しい書き込み経路を作らない。**
- `.jin` の読み込み → モデル化は `jin_cli/main.py` の既存ヘルパ（`main.py:604` 付近「`.jin` を診断し、error が無ければモデルを返す。
  error があれば診断を出して exit 1」・`jin build` / `jin run` が使っているもの）を**再利用**する。したがって既定では error 診断がある
  ファイルは render しない。「エラーがあっても図を出す」方が使い道があるとは思うので、`--force` 等で図を出す選択肢を **HANDOFF
  `DP-IMPL-JIN-P3-RENDER-ON-ERROR-01`** として起票し（推奨: 既定は build と同じく拒む・オプションは Phase 3 では足さない）、推奨案で進める。
  ただし `jin_render.render` 自体は §5 のとおり意味エラーを含むモデルでも落ちない。

## 4. トレース overlay（要件書 §4 / adk-mapping §2.4）

- 強調対象の決め方を **`docs/spec/layout.md` に新しい節として明文化**し、コードとテストを同じ規則で書く。推奨規則:
  1. イベントの `pointer` と `data-jin` が**完全一致**する要素を強調する
  2. 完全一致する要素が無いときは、pointer のセグメントを末尾から削って**最も近い祖先**の要素を強調する
     （例: focus=Pipeline のとき `/circles/2/core` は Pipeline の描画に無いが、Drafter を表す要素があればそれ）
  3. `pointer: null` の行と、祖先も見つからない行は**強調せず、点だけ**に数える
  4. **参照を表す要素は参照先の配下 pointer でも強調される（referent 規則）。** focus=Pipeline のとき Drafter は `flow.steps` の
     弦端点として描かれ、その要素の `data-jin` は**参照側** `/circles/0/flow/steps/0`（編集の hit-test 上そうあるべき）。一方トレースの行は
     **参照先** `/circles/2/core`。規則 2 の祖先一致だけでは Pipeline の描画に `/circles/2` の要素が無く、root 焦点では下位 circle の
     `model` 行が**何も強調されない**。よって「参照を表す要素（step の端点・delegate の小円・summon の紋）は、参照先 circle の配下 pointer
     （`/circles/<k>/...`）のイベントでも強調対象になる」を規則として明記する。実装は要素に内部的な referent 集合を持たせるか
     `data-jin-ref="<参照先 pointer>"` のような**追加属性**で表す（契約は「2 属性を持つ」であり追加属性を禁じていない。契約テストは
     2 属性の存在と 9 種だけを見る形にする）。これは判断ポイントなので `DP-IMPL-JIN-P3-OVERLAY-REFERENT-01` として HANDOFF に載せ、推奨案で進める。
- §4 の横断テスト（`tests/contract/`）は「focus=各 circle の和集合」ではなく **「focus=root（`Pipeline`）で全 pointer が何かの要素に解決する」**
  を含める。referent 規則の有無を機械で検出できるのはこの形だけ。
- 「境界環の外側にイベント数ぶんの点を並べる」: `seq <= upto` の行数ぶんの点。半径・配置・キャンバスの余白は layout.md に書く
  （§1 の環半径は固定なので、点の半径は 0.95 より外・キャンバスに収まる値を決めて明記）。
- 強調は 1 色（白黒 2 値 + 強調 1 色）。色の値は要件書に無いので**実装判断として** `decision-conformance.md` §2 に根拠を 1 行残す
  （「要件値ではない」と明記）。`<style>` を使わず属性で完結させる。
- adk-mapping §2.4 の pointer 列（`/circles/i/core` / `/circles/i/tools/j` / `/circles/i/delegate/k` / `/circles/i/flow/exit` / `/circles/i`）が
  **focus した circle の描画の中で何に対応するか**を layout.md に表で書く。特に `/circles/i/flow/exit`（loop の終了判定）は
  対応する要素（loop 多角形の閉じ目・exit の印など）を決めるか、規則 2 の祖先一致で `/circles/i` に落ちることを明記する。
- **summon 先の内部イベントはトレースに現れない**（`phase2-handoff.md` §6 / adk-mapping §2.4）。overlay で summon 先の陣は常に「未発火」に見える。
  「呼ばれた（`tool` 行 → `/circles/i/tools/j` が強調）」と「中で何が起きたかは不明」を描き分け、layout.md に書く。
- fixture: `PYTHONPATH=tests/fixtures/stubs uv run jin run examples/pipeline/pipeline.jin "go" --model fake --trace <path>` の出力（11 行・
  `/circles/N/core` と `/circles/1/flow/exit`）を **`tests/fixtures/traces/pipeline-fake.jsonl` としてコミット**し、jin-render のテストはこれを読む。
  `tests/contract/` に「`jin run --model fake` を実際に回した JSONL の全 pointer が、`render(focus=<各 circle>)` の `data-jin` 集合か
  その祖先に解決する」横断テストを置く（`jin_adk` を import してよいのは `tests/contract/` だけ）。

## 5. 壊れたモデルでも落ちない（Phase 4 のエラー回復のため）

Phase 4 の `jin/renderSvg` は JSON 構文エラー中に**直前の正常モデル**で応答する（NFR-AVAIL-001）。その「正常」は
「パースでき schema を通った」までで、意味エラー（未定義 circle への `summon` / `delegate` / `steps`、JIN012 の循環、JIN013 の多重親 …）を含みうる。
したがって **`jin_render.render` は schema を通る `JinFile` なら例外を投げない**（`focus` 不正だけが例外）。

- 未定義 circle への参照は「解決できない参照」として点（または破線の空円）で描き、`data-jin` にはその参照の pointer
  （例 `/circles/0/tools/2` / `/circles/0/delegate/1` / `/circles/0/flow/steps/0`）を付ける
- 循環（A が B を summon し B が A を summon）で無限展開しない: 展開は深さ 1 まで（layout.md §2）で構造的に止まる。テストで固定する
- **既定 focus が無いとき**: focus 省略時の既定は `root` の circle だが、`root` が未定義（JIN060）ならその circle は無い。
  落ちない挙動（例: `circles[0]` に fallback し、`root` 未解決の印を描く／`circles` が空なら空キャンバスだけ）を決めて layout.md に書き、
  テストで固定する。`circles: []` を schema（`model.py` の `JinFile.circles: list[Circle]`）が許すかを実測して、許すなら空のケースも回す。
- `tests/fixtures/errors/JIN0*.jin` のうちパース・schema を通る fixture 全部について「render が例外を投げない・全要素に `data-jin`」を
  parametrize で回す

## 6. 決定性（ADR-010 / DP-JIN-SVG-DETERMINISM-01）

- 座標を SVG に書き出す経路は**丸め関数 1 本**（例 `fmt_coord`）だけを通す。`f"{x}"` / `str(float)` / `repr` を SVG 生成に混在させない。
  これを **`guard: <関数名> -> <トークン>` 記法**で主張し（`jin_cli/main.py` / `jin_adk/*.py` の既存例を見る）、
  `tests/contract/test_guard_claims.py` は `packages/*/src` を走査するので新パッケージも自動で検査対象になる。
  さらに jin-render のテストで「SVG 内の数値リテラルが全部その桁数で終わっている（正規表現）」を固定する。
- 丸め関数は **固定小数（`format(x, ".Nf")`）**で出し、末尾ゼロを落とさない（そうしないと「数値リテラルが全部 N 桁で終わる」検査が成立しない）。
  **`-0.0` は `0.0` に正規化する**（`cos(90°)` 級の微小値の符号は libm で揺れ、`-0.000` / `0.000` の差が macOS 開発機と CI Linux で
  snapshot をずらす）。丸めたあとに `== 0` なら符号を捨てる形で実装し、テストで固定する。
- **丸め桁数は Phase 3 で決める**（要件書に無い）。決めたら `docs/spec/layout.md` §4 **と** `decision-conformance.md` §2 の**両方**に根拠を書く
  （仕様側とコード側は同じ欠陥・片方だけ直さない）。根拠は「px 換算後の解像度に対して十分か」「桁を増やすと浮動小数の末尾ノイズが
  プロセス間で揺れるか」の 2 点を実測で示す。確信が持てなければ HANDOFF（§9）に載せて推奨値で進める。
- 決定性テストは **`subprocess` で `PYTHONHASHSEED` を変えた別プロセス 2 回**（例 `0` と `4242`）で examples 2 本を render し
  バイト一致を見る（machine 7）。同一プロセス 2 回のバイト一致（machine 2）は**別のテスト**として両方置く。
- 辞書順序・`set` の反復・`id()`・時刻・乱数に依存しない。`hashlib.sha256` は `PYTHONHASHSEED` の影響を受けない（`hash()` は受ける）ので装飾は sha256 で。
- SVG スナップショットは syrupy（`packages/jin-render/tests/__snapshots__/`）。「正規化後」は出力が決定的なので**素のバイト列**でよいが、
  そう決めた理由を implementation-notes に 1 行書く。

## 7. `data-jin` 契約（layout.md §3）

- 描画された**すべての**要素（`<g>` / `<circle>` / `<path>` / `<line>` / `<text>` / `<textPath>` …）に `data-jin` と `data-jin-kind`。
  ルートの `<svg>` 自身も含めるか（`data-jin=""` = ルート文書・kind は 9 種に無い）は**含めない**方向で決め、layout.md に「`<svg>` 要素と
  `<defs>` 配下は契約の対象外」と書く（要件書 §2.5「描画された全ての要素」の解釈として implementation-notes に理由を残す）。
  テストは「`<svg>` と `<defs>` 配下を除く全要素」で回す。
- `data-jin-kind` は 9 種のみ（`tests/spec/test_spec_consistency.py` が layout.md と要件書を突合している。`machine-readable` マーカーの書式を変えない）。
  9 種に無い描画要素（トレースの点・強調の縁取りなど）を作るなら、**既存 9 種のどれに属するかを決めて layout.md に書く**
  （例: 点は `data-jin-kind="circle"` で pointer は focus 中の circle）。10 種目を増やさない。
- 同じ pointer を持つ要素が複数あってよい（同じ circle を 2 回 summon した入れ子など）。`data-jin` は ID ではなく鍵。layout.md §3 に明記。
- `<textPath>` が参照する `<path id="…">` の id は**決定的かつ XML NCName 互換**にする（pointer をそのまま id にしない。
  `rune-path-<circle index>` のような形）。同じ id が 2 回出ない（入れ子で同じ circle を 2 回描くときも）ことをテストで固定する。
- **XML エスケープ**: circle 名 / tool 名 / state 名 / rune / pointer は `.jin` 由来の**入力**。属性値・テキストノードは必ず
  `xml.sax.saxutils.escape` / `quoteattr` 相当を通し、`guard:` 記法で主張する。rune に `</svg><script>` を入れた fixture で
  「出力がタグとして解釈されない（`<` が残らない）」をテストで固定する（Phase 5 のエディタは SVG を DOM に埋め込む）。

## 8. レイアウトで layout.md に**書いていない**こと（実装で決めて仕様に書き戻す）

要件書 §2.5 / layout.md は環半径・配置角・k の規則までしか決めていない。次は実装判断であり、**決めたら layout.md に追記**する
（値は「要件値」ではなく「実装で確定した値」と明記。`decision-conformance.md` §2 にも 1 行）:

- キャンバスの px サイズと余白（点を境界環の外に置くため 1.0 を超える座標が要る）
- 核（core）の半径、紋（tool）/ 四角（state）/ 刻印（guard）の大きさ、入れ子小陣の縮尺（深さ 1）、深さ 2 以降の「点」の半径
- `flow.steps` の circle をどこに置くか（弦の端点）。`sequence` の矢印の描き方、`parallel` の対称配置、`loop` の多角形/星形の頂点半径
- `delegate` の小円の半径と配置、核との破線
- `await` の欠けの角幅
- rune の `<textPath>` のフォントサイズ、文字数が環より長いときの扱い（切り詰め位置を決定的に）
- 装飾（sha256 由来）の生成規則: ハッシュの何バイトを何に使うか（角度・半径・個数）。`rune` 無しの circle には描かない

**core が無い circle**（`flow` だけの circle）と **state / tools / boundary が無い circle** の描画（環を描かない・半径を詰めない）も
テストで固定する。

## 9. 判断ポイント（実装者が決めてはならないもの・HANDOFF の出し方）

- `DP-JIN-SVG-DETERMINISM-01`（人間確定）を覆さない。丸め桁数は「Phase 3 で決めて根拠を残す」までが確定内容。
- Phase 2 と同じく、**人間判断が要ると思った論点は HANDOFF（non-blocking）として `implementation-plan.json` の `undecided[]` と
  `undecided_details[]` に `DP-IMPL-JIN-P3-<TOPIC>-01` の ID で登録**し（既存の `DP-IMPL-JIN-P2-*` の形式に合わせる）、
  `implementation-notes.md` に質問セット（選択肢・推奨・理由）を書く。親が auto-decider に回して `ai_provisional` で記録する。
  推奨案で実装を進めてよい（ブロックしない）。候補: 丸め桁数 / 強調色 / `<svg>` 要素を契約対象外にする解釈 / trace overlay の祖先一致規則。
- `DP-REVIEW-JIN-P2-002`（空トレースの印）は未決のまま。Phase 3 では「空トレース（0 行）は点 0 個・強調なし」で描き、判断を待つ。

## 10. 記録（Phase 2 と同じ extend 規律）

- `implementation-plan.json` は **extend**（`round.index` を 3 / `round.jin_phases` を累積 `[0,1,2,3]` / `scope` を Phase 3 に、
  `skill_plan[]` / `tasks[]` / `verification_status.domain_checks[]` の追加要素に `jin_phase: 3`。既存要素を消さない・書き換えない）。
  `scope_labels` は schema の enum に従う（Phase 2 の実測: `backend-unit-verified` のみ）。`human_only` と `pipeline_e2e` は `not_run`。
- `implementation-notes.md` に **P3-1〜** の節を**追記**（既存節を消さない）。TDD の Red 証跡 / 8 ゲートの実測 / HANDOFF / Stage 5 レビュー依頼。
- `decision-conformance.md` §2 に **P3** 行を追記: `DP-JIN-SVG-DETERMINISM-01` の constraint ごと（丸め関数 1 本・桁数と根拠・別プロセス決定性テスト・
  k の規則の実装）と `DP-COMMON-07` の「SVG はキャッシュしない」「純関数」。
- `docs/spec/layout.md` §5「本ラウンドでの実装状況」を更新。§1 / §3 の `machine-readable` ブロックの書式は変えない。
- `CLAUDE.md`: Phase 3 の行を「実装済み」に、「Phase 2 時点で実在するのは …」を更新、開発コマンドに `jin render` を追加、
  パッケージ境界の図に `jin-render` を反映。`test_claude_md_has_the_package_addition_checklist` が見る 7 点チェックリストは消さない。
- `README.md` に `jin render` の使い方を追記。
- 変異ハーネス: `delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py` を **`phase2-mutations/mutate_p2.py` と同じ流儀**
  （隔離コピー上で変異・`__pycache__` 削除 + `PYTHONDONTWRITEBYTECODE=1`・実ツリー不変・`/tmp` 残骸 0）で作り、
  少なくとも「丸め関数を素の `str()` に替える」「`data-jin` を 1 要素だけ落とす」「装飾を sha256 でなく固定にする」「祖先一致を消す」
  「XML エスケープを外す」「`focus` を無視する」「k を `n//2` にする」の各変異で対応テストが**赤くなる**ことを実測する。

## 11. 環境と実行上の制約（このマシン・この worktree）

- 作業ツリー: `/home/wisteria/jin-lang/.claude/worktrees/jin-phase3-6`（ブランチ `feat/jin-phase3-render`・origin/main `32c215e` から）。
  **このディレクトリの外（特に `/home/wisteria/jin-lang` 本体や隣の worktree）を書き換えない。**
- Python 3.14.7 / uv 0.12.10 / `.venv` は同期済み。ベースラインは全緑 **811 passed**（2026-09-06・親が実測。Phase 2 完了時 800 + Issue #8 の 11）。
- **Bash サンドボックスの制約**: `python3 - <<'EOF'` の heredoc、`$VAR/script.py` のような変数で組んだパス、`cd X && …` の複合コマンドは
  拒否される。ファイル作成・編集は Write / Edit ツールで行い、スクリプトは**固定の絶対パス**で呼ぶ。一時ファイルは
  `/home/wisteria/.claude/jobs/e2bcfe94/tmp/` に置く（`/tmp` は他ジョブと共有）。
- CI と同じ 8 ゲート（`UV_LOCKED=1 uv sync` / `ruff check .` / `ruff format --check .` / `pytest` / `lint-imports` /
  `jin schema | diff -u schemas/jin.schema.json -` / `jin check examples` / `jin fmt --check examples`）を**修正後に実測**して
  implementation-notes に件数つきで書く。`__pycache__` を消し `PYTHONDONTWRITEBYTECODE=1` で回す。
- 委譲プロトコル: 最終応答は**短く**（成果物のパス・件数・4 状態 `DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT` の 1 行）。
  長文は implementation-notes.md に書く。Stage 5 レビューは親が行うので、レビュー依頼（対象ファイル一覧・decision-conformance の行・
  constraints・verification_status）を implementation-notes の P3 節に書いて返す。コミットは親が行う（implementer は `git commit` しない）。

## 12. Phase 2 から引き継ぐ原則（`phase2-handoff.md` §8）

1. テストが緑であることは品質の証拠にならない（Phase 2 は 696 件緑で 78 件の finding）。
2. 「検査が存在する」と「検査が落ちる」は別。実装を壊して赤くなることを確認する（§10 の変異）。
3. 仕様側とコード側は同じ欠陥。片方だけ直さない（layout.md とコード）。
4. 要件書に無い値を捏造しない。決めたら根拠を `decision-conformance.md` に書く。
5. 未確定の判断を実装者が勝手に決めない。HANDOFF に載せる。
6. コメントの安全宣言は `guard:` / `hazard:` 記法で機械固定する。
