# 鑑賞ページ（Jin v2.1・`apps/stage`）の変異の実測

実行: `uv run python delivery/20260904-1445-jin/stage-mutations/mutate_stage.py`（2026-09-17・macOS・隔離コピー上）

ベースライン（隔離コピー・変異なし）:

- pytest（`tests/contract/test_stage_contract.py` / `tests/spec/test_stage_spec_consistency.py` / `packages/jin-cli/tests/test_editor.py`）: 50 passed, 1 deselected
  （外したのは `test_the_svg_fixture_is_what_the_renderer_draws_today`。コピー側で `uv run jin render` を起こすため・スクリプトの docstring）
- `apps/stage` の `pnpm test`: 90 passed / `pnpm typecheck`: exit 0
- `apps/editor` の `pnpm test`: 117 passed / `pnpm typecheck`: exit 0

| 変異 | 対象 | 壊したもの | 結果 | 赤くしたテスト |
|---|---|---|---|---|
| `SCENE-computes-its-own-unit` | `apps/stage/src/scene.ts` | `const scale = width / 2 / HALF_EXTENT;` → `const scale = 400;` | KILLED | `test/scene.test.ts` > viewBox の大きさが違っても同じ正規化になる |
| `LAYERS-drift-from-the-spec` | `apps/stage/src/layers.ts` | `sigil: 3` → `sigil: 2` | KILLED | `tests/contract/test_stage_contract.py::test_the_kind_layers_in_the_code_are_the_table_of_stage_md` |
| `EFFECTS-no-habituation` | `apps/stage/src/effects.ts` | `count >= HABIT_AFTER` → `count >= Number.POSITIVE_INFINITY` | KILLED | `test/effects.test.ts` > 毎 tick 繰り返す rite は 3 回目からうなり（HUM）に落ちる / paddle の 90 tick: ball の set はうなりに落ち、score は boot の 1 回だけ強い |
| `LAYERS-height-ignores-unit` | `apps/stage/src/layers.ts` | `layerHeight` の `× unit` → `× 1`（最終レビュー #1: 入れ子の小陣が塔になる） | KILLED | `test/gilded.test.ts` > 入れ子の小陣は幅に比例して低い（塔にならない） / ignite は光った陣の層だけを、その陣の単位で浮かせる、`test/layers.test.ts` > 実際の高さは層の値 × 陣の単位 |
| `EFFECTS-whole-circle-uses-the-raw-pointer` | `apps/stage/src/effects.ts` | `glowTarget(spec.effect, targets.primary)` → `targets.primary`（最終レビュー #2: `finish` / `error` がステップの部分木だけを光らせる） | KILLED | `test/effects.test.ts` > finish（crown）と error（crack）はステップの pointer を持っていても陣が target |
| `EFFECTS-set-ignores-unchanged-values` | `apps/stage/src/effects.ts` | 値が同じ `set` の `strength = HUM` → `strength = 1` | KILLED | `test/effects.test.ts` > set は値が変わらなければ HUM、変われば強い |
| `NAMES-prefix-instead-of-segments` | `apps/stage/src/names.ts` | `pointers.has(current)` の段一致 → `current.startsWith(p)` の前方一致 | KILLED | `test/names.test.ts` > 段一致で祖先へ遡る > ステップは手順に落ちる |
| `GLOW-reads-the-clock` | `apps/stage/src/render/glowView.ts` | `tick / fps` → `performance.now() / 1000` | KILLED | `tests/contract/test_stage_contract.py::test_the_picture_does_not_read_the_clock_or_math_random` |
| `VOCAB-stage-only-word` | `apps/stage/src/messages.ts` | `"stage.ping"` を stage 側だけに足す | KILLED | `tests/contract/test_stage_contract.py::test_the_editor_and_the_stage_speak_the_same_four_words` |
| `PANEL-draws` | `apps/editor/src/stage/StagePanel.tsx` | `document.createElement("canvas").getContext("webgl2")` を足す | KILLED | `tests/contract/test_stage_contract.py::test_the_stage_panel_does_not_draw` |
| `EXPORTER-ignores-abort` | `apps/stage/src/exporter.ts` | ループの中と描き終えた後の `signal.aborted` の確認を 2 つとも外す | KILLED | `test/exporter.test.ts` > 中止したら cancel して null（何も渡さない） |
| `EXPORTER-delivers-after-finish` | `apps/stage/src/exporter.ts` | `finish()` の後の `signal.aborted` の確認を外す（最終レビュー #3: 仕上げの最中の中止でもファイルを渡す） | KILLED | `test/exporter.test.ts` > 仕上げ（finish）の最中に中止したら、仕上がっても null（何も渡さない） |
| `EDITOR-stage-escapes` | `packages/jin-cli/src/jin_cli/editor.py` | `/stage/` だけ `super().translate_path` の正規化を通さず `str(mount) + "/" + rest` を返す（`/play/` は元のまま） | KILLED | `packages/jin-cli/tests/test_editor.py::test_the_stage_is_served_under_stage_and_cannot_escape`（`-k stage` で選んだテストだけで赤） |

| `PALETTE-swaps-canvas-and-input` | `apps/stage/src/palette.ts` | 力の宝玉の表の `canvas` と `input` を入れ替える | KILLED | `test/palette.test.ts` > cast は名前空間の宝玉 / 種別ごとの宝玉、`test/effects.test.ts` > cast canvas.rect の発火はサファイア |
| `PARTICLES-reads-math-random` | `apps/stage/src/particles.ts` | `mulberry32(glow.seq)` → `Math.random`（粒子の散り方が実時間の乱数を読む） | KILLED | `tests/contract/test_stage_contract.py::test_the_picture_does_not_read_the_clock_or_math_random` |
| `PALETTE-throws-without-fields` | `apps/stage/src/palette.ts` | `circle?.sigilKinds?.[…]` → 欄が有る前提で引く（古いエディタの表で例外） | KILLED | `test/palette.test.ts` > 欄の無い古い表でも例外を投げず金、`test/effects.test.ts` > paddle の 90 tick |
| `GLOW-endpoints-ignore-layer-spin` | `apps/stage/src/render/glowView.ts` | 端点の変換で層の行列（自転・浮き沈み）を通さない | KILLED | `test/gilded.test.ts` > 層の自転で光線の端点も同じ角だけ陣の中心まわりに回る |
| `DRAW-skips-rect` | `apps/stage/src/screen/draw.ts` | 描画の写しが `rect` を描かない | KILLED | `test/draw.test.ts`（clear・ink・未知の op の各テスト） |
| `GLYPHS-copy-drifts` | `apps/stage/src/screen/glyphs.ts` | 字形の写しの `BITMAPS` を 1 字ずらす | KILLED | `tests/contract/test_stage_contract.py::test_the_stage_glyphs_are_the_generated_copy` |
| `SOUND-ignores-speed` | `apps/stage/src/screen/sound.ts` | 音の置き場所に速度を掛けない | KILLED | `test/sound.test.ts` > 0.5 倍速では置き場所が 2 倍 |
| `FRAMES-shows-the-oldest` | `apps/stage/src/screen/frames.ts` | 映すコマを最新ではなく最古から選ぶ | KILLED | `test/frames.test.ts` > 時刻 t の tick 以前で最新のコマ |

**21/21 mutations killed**（最終レビューの修正で 3 件、宝玉と金細工の世界観（設計書 2026-10-01 §9.4）で 4 件、召喚の窓と音（設計書 2026-10-01-jin-stage-summon §4.4）で 4 件を足した）

2026-10-01（WSL2・隔離コピー上）に全件を回し直した。ベースライン: pytest 60 passed / 3 deselected、`apps/stage` の `pnpm test` 190 passed、`apps/editor` の `pnpm test` 126 passed。`PALETTE-throws-without-fields` は agent の cast の修正で行が変わったので置換元を直して回した。
外したのは `test_the_svg_fixture_is_what_the_renderer_draws_today` の 3 件（parametrize で paddle の陣・手順の図・tetris に広げた）。

## 計画からの変更

- `EFFECTS-no-habituation`: 実コードの三項演算子は複数行に折られているので、`before` を一意な部分文字列 `count >= HABIT_AFTER` にした
- `EXPORTER-ignores-abort`: 計画はループの中の確認だけを外していた。描き終えた後の確認も残っていると「中止を無視する」を表しきれないので、2 つとも外した（ループの中の確認だけを外しても赤くなる）
- `EDITOR-stage-escapes`: `translate_path` は `/play/` と `/stage/` を 1 本のループで写す形になったので、計画の `return super()…` の置き換えだと `/play/` も一緒に壊れる。`/stage/` の前置きのときだけ素の結合で返す差し込みにし、検査を `-k stage` に絞って `/stage/` のテストが拾うことを確かめた

## この表が見ていないもの

e2e（Playwright）は回さない（隔離コピーに `dist` と `.venv` が無い）。「書き出したファイルを Node で読み戻せる」「エディタの鑑賞モードに行が届く」「書き出し中に届いた scene / trace を終わってから当てる」「同じ scene / trace を送り直さない」は `apps/stage/e2e/stage.spec.ts` / `apps/editor/e2e/stage.spec.ts` と単体テストだけが見張っている。

## ベースラインを緑にするために直したテスト

`packages/jin-cli/tests/test_editor.py::test_jin_editor_accepts_stage_dist_without_a_new_subcommand` は `"--stage-dist" in result.output` を見ていた。`FORCE_COLOR` が立った環境では typer/rich が `-` と `-stage-dist` の間に ANSI の色指定を挟むので、実ツリーでも落ちていた（`test_cli.py::test_lsp_help_describes_both_transports` が書き残している既知の罠）。オプションの説明文「鑑賞ページの場所」を見る形に直した。
