# 鑑賞ページ（Jin v2.1・`apps/stage`）の変異の実測

実行: `uv run python delivery/20260904-1445-jin/stage-mutations/mutate_stage.py`（2026-09-17・macOS・隔離コピー上）

ベースライン（隔離コピー・変異なし）:

- pytest（`tests/contract/test_stage_contract.py` / `tests/spec/test_stage_spec_consistency.py` / `packages/jin-cli/tests/test_editor.py`）: 50 passed, 1 deselected
  （外したのは `test_the_svg_fixture_is_what_the_renderer_draws_today`。コピー側で `uv run jin render` を起こすため・スクリプトの docstring）
- `apps/stage` の `pnpm test`: 82 passed / `pnpm typecheck`: exit 0
- `apps/editor` の `pnpm test`: 117 passed / `pnpm typecheck`: exit 0

| 変異 | 対象 | 壊したもの | 結果 | 赤くしたテスト |
|---|---|---|---|---|
| `SCENE-computes-its-own-unit` | `apps/stage/src/scene.ts` | `const scale = width / 2 / HALF_EXTENT;` → `const scale = 400;` | KILLED | `test/scene.test.ts` > viewBox の大きさが違っても同じ正規化になる |
| `LAYERS-drift-from-the-spec` | `apps/stage/src/layers.ts` | `sigil: 3` → `sigil: 2` | KILLED | `tests/contract/test_stage_contract.py::test_the_kind_layers_in_the_code_are_the_table_of_stage_md` |
| `EFFECTS-no-habituation` | `apps/stage/src/effects.ts` | `count >= HABIT_AFTER` → `count >= Number.POSITIVE_INFINITY` | KILLED | `test/effects.test.ts` > 毎 tick 繰り返す rite は 3 回目からうなり（HUM）に落ちる / paddle の 90 tick: ball の set はうなりに落ち、score は boot の 1 回だけ強い |
| `EFFECTS-set-ignores-unchanged-values` | `apps/stage/src/effects.ts` | 値が同じ `set` の `strength = HUM` → `strength = 1` | KILLED | `test/effects.test.ts` > set は値が変わらなければ HUM、変われば強い |
| `NAMES-prefix-instead-of-segments` | `apps/stage/src/names.ts` | `pointers.has(current)` の段一致 → `current.startsWith(p)` の前方一致 | KILLED | `test/names.test.ts` > 段一致で祖先へ遡る > ステップは手順に落ちる |
| `GLOW-reads-the-clock` | `apps/stage/src/render/glowView.ts` | `tick / fps` → `performance.now() / 1000` | KILLED | `tests/contract/test_stage_contract.py::test_the_picture_does_not_read_the_clock_or_math_random` |
| `VOCAB-stage-only-word` | `apps/stage/src/messages.ts` | `"stage.ping"` を stage 側だけに足す | KILLED | `tests/contract/test_stage_contract.py::test_the_editor_and_the_stage_speak_the_same_four_words` |
| `PANEL-draws` | `apps/editor/src/stage/StagePanel.tsx` | `document.createElement("canvas").getContext("webgl2")` を足す | KILLED | `tests/contract/test_stage_contract.py::test_the_stage_panel_does_not_draw` |
| `EXPORTER-ignores-abort` | `apps/stage/src/exporter.ts` | ループの中と描き終えた後の `signal.aborted` の確認を 2 つとも外す | KILLED | `test/exporter.test.ts` > 中止したら cancel して null（何も渡さない） |
| `EDITOR-stage-escapes` | `packages/jin-cli/src/jin_cli/editor.py` | `/stage/` だけ `super().translate_path` の正規化を通さず `str(mount) + "/" + rest` を返す（`/play/` は元のまま） | KILLED | `packages/jin-cli/tests/test_editor.py::test_the_stage_is_served_under_stage_and_cannot_escape`（`-k stage` で選んだテストだけで赤） |

**10/10 mutations killed**

## 計画からの変更

- `EFFECTS-no-habituation`: 実コードの三項演算子は複数行に折られているので、`before` を一意な部分文字列 `count >= HABIT_AFTER` にした
- `EXPORTER-ignores-abort`: 計画はループの中の確認だけを外していた。描き終えた後の確認も残っていると「中止を無視する」を表しきれないので、2 つとも外した（ループの中の確認だけを外しても赤くなる）
- `EDITOR-stage-escapes`: `translate_path` は `/play/` と `/stage/` を 1 本のループで写す形になったので、計画の `return super()…` の置き換えだと `/play/` も一緒に壊れる。`/stage/` の前置きのときだけ素の結合で返す差し込みにし、検査を `-k stage` に絞って `/stage/` のテストが拾うことを確かめた

## この表が見ていないもの

e2e（Playwright）は回さない（隔離コピーに `dist` と `.venv` が無い）。「書き出したファイルを Node で読み戻せる」「エディタの鑑賞モードに行が届く」「書き出し中に届いた scene / trace を終わってから当てる」「同じ scene / trace を送り直さない」は `apps/stage/e2e/stage.spec.ts` / `apps/editor/e2e/stage.spec.ts` と単体テストだけが見張っている。

## ベースラインを緑にするために直したテスト

`packages/jin-cli/tests/test_editor.py::test_jin_editor_accepts_stage_dist_without_a_new_subcommand` は `"--stage-dist" in result.output` を見ていた。`FORCE_COLOR` が立った環境では typer/rich が `-` と `-stage-dist` の間に ANSI の色指定を挟むので、実ツリーでも落ちていた（`test_cli.py::test_lsp_help_describes_both_transports` が書き残している既知の罠）。オプションの説明文「鑑賞ページの場所」を見る形に直した。
