import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { REPO_ROOT, type RunningEditor, startEditor } from "./editor";

/**
 * デバッグモード（要件書 §7.2 / design.yaml `implementation_phases.items[6]`）の machine 4 件。
 *
 * 台本は `examples/pipeline/pipeline.jin` と、**`jin run --model fake` が実際に書いた**
 * `tests/fixtures/traces/pipeline-fake.jsonl`（11 行）である。作り物のトレースを
 * 使うと「レンダラが読める形」から静かにずれる（突合は `tests/contract/test_render_contract.py`）。
 */
const SOURCE = readFileSync(join(REPO_ROOT, "examples/pipeline/pipeline.jin"), "utf8");
const TRACE = join(REPO_ROOT, "tests/fixtures/traces/pipeline-fake.jsonl");

let editor: RunningEditor;

test.beforeEach(async () => {
  editor = await startEditor(SOURCE);
});

test.afterEach(() => {
  editor?.stop();
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    await testInfo.attach("jin editor stderr", { body: editor.log(), contentType: "text/plain" });
  }
});

/** デバッグモードに入ってトレースを読み込むところまで。 */
async function openTrace(page: Page, path = TRACE): Promise<Locator> {
  await page.goto(editor.url);
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");
  await page.getByTestId("jin-mode-debug").click();
  await page.getByTestId("jin-trace-file").setInputFiles(path);
  return page.getByTestId("jin-canvas");
}

async function scrub(page: Page, upto: number): Promise<void> {
  await page.getByTestId("jin-upto").fill(String(upto));
  await expect(page.getByTestId("jin-upto-value")).toHaveText(String(upto));
  // **図が届くまで待つ。** `upto` の表示は状態を置いた時点で変わるが、SVG は
  // `jin/model` → `jin/renderSvg` の往復のあとに入る。ここで待たないと
  // machine 2（決定性）が**古い図どうし**を比べて、遅い実行環境で揺れる。
  // この fixture の `seq` は 1..11 の連番なので、点の数がそのまま `upto` になる。
  await expect(page.getByTestId("jin-canvas").locator("[data-jin-seq]")).toHaveCount(upto);
}

test("machine 1: JSONL を読み込み、スクラバで upto を動かすとオーバーレイが変わる", async ({
  page,
}) => {
  const canvas = await openTrace(page);

  // 読み込んだ直後は**最後まで**発火済み（seq の最大値 = 11）。
  await expect(page.getByTestId("jin-upto-value")).toHaveText("11");
  await expect(page.getByTestId("jin-trace-name")).toContainText("11 件");
  // 11 行あるが、発火する**要素**は 5 つ（同じ pointer が繰り返し出る）。
  await expect(canvas.locator('[data-jin-fired="1"]')).toHaveCount(5);
  // 境界環の外側の点は seq ごとに 1 つ（`docs/spec/layout.md` §7.4）。
  await expect(canvas.locator("[data-jin-seq]")).toHaveCount(11);

  // 0 まで戻すと**何も発火していない**。
  await scrub(page, 0);
  await expect(canvas.locator('[data-jin-fired="1"]')).toHaveCount(0);
  await expect(canvas.locator("[data-jin-seq]")).toHaveCount(0);

  // 3 まで進めると 3 要素 / 点 3 つ。
  await scrub(page, 3);
  await expect(canvas.locator('[data-jin-fired="1"]')).toHaveCount(3);
  await expect(canvas.locator("[data-jin-seq]")).toHaveCount(3);
  // 点は 1..3 の連番（`upto` を増やしても既に置いた点は動かない・§7.4）。
  await expect(canvas.locator('[data-jin-seq="3"]')).toHaveCount(1);
  await expect(canvas.locator('[data-jin-seq="4"]')).toHaveCount(0);

  // 一覧では未発火の行が残ったまま薄く出る（消さない）。
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(11);
  await expect(page.locator('[data-testid="jin-trace-row"][data-fired="1"]')).toHaveCount(3);
});

test("machine 2: 同一 upto では常に同じ SVG（エディタ経由でも決定的）", async ({ page }) => {
  const canvas = await openTrace(page);
  const svg = canvas.locator("svg");

  await scrub(page, 5);
  const first = await svg.evaluate((node) => node.outerHTML);

  // **間に別の upto を挟む。** キャッシュを返しているだけなら一致してしまう
  // （エディタは SVG をキャッシュしない・DP-COMMON-07）。
  await scrub(page, 3);
  const middle = await svg.evaluate((node) => node.outerHTML);
  expect(middle).not.toBe(first);

  await scrub(page, 5);
  const again = await svg.evaluate((node) => node.outerHTML);
  expect(again).toBe(first);

  // 三度目も同じ（往復のたびに `jin/renderSvg` を呼び直している）。
  await scrub(page, 0);
  await scrub(page, 5);
  expect(await svg.evaluate((node) => node.outerHTML)).toBe(first);
});

test("machine 3: pointer 一致フィルタが、その紋で発火した行だけを残す", async ({ page }) => {
  const canvas = await openTrace(page);
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(11);

  // 要素を選ぶまでフィルタは押せない。
  await expect(page.getByTestId("jin-trace-filter")).toBeDisabled();

  // Drafter の核（`/circles/2/core`）を選ぶ。トレースでは seq 1 だけがここで発火する。
  await canvas.locator('[data-jin="/circles/2/core"]').first().click();
  await expect(page.getByTestId("jin-trace-selected")).toHaveText("/circles/2/core");
  await page.getByTestId("jin-trace-filter").check();
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(1);
  await expect(page.getByTestId("jin-trace-row")).toHaveAttribute("data-seq", "1");
  await expect(page.getByTestId("jin-trace-row")).toHaveAttribute(
    "data-pointer",
    "/circles/2/core",
  );

  // **別の紋を選ぶと別の行になる。** 常に 1 件出しているだけではないこと。
  await canvas.locator('[data-jin="/circles/3/core"]').first().click();
  await expect(page.getByTestId("jin-trace-selected")).toHaveText("/circles/3/core");
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(1);
  await expect(page.getByTestId("jin-trace-row")).toHaveAttribute("data-seq", "2");

  // **発火していない紋を選ぶと 0 件。** 全件へ黙って戻さない（「一致」であって
  // 「絞り込めなければ全部」ではない）。
  await canvas.locator('[data-jin="/circles/2/instruction/rune"]').first().click();
  await expect(page.getByTestId("jin-trace-selected")).toHaveText("/circles/2/instruction/rune");
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(0);
  await expect(page.getByTestId("jin-trace-empty")).toBeVisible();

  // 外すと全件に戻る。
  await page.getByTestId("jin-trace-filter").uncheck();
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(11);
});

test("machine 4: 詳細パネルが行の input / output / name / kind を出す", async ({ page }) => {
  await openTrace(page);

  // seq 5 は `escalate`（`Refine` の脱出判定）。入出力がオブジェクトの行を選ぶ。
  await page.locator('[data-testid="jin-trace-row"][data-seq="5"]').click();
  const detail = page.getByTestId("jin-trace-detail");
  await expect(detail).toBeVisible();
  await expect(page.getByTestId("jin-detail-kind")).toHaveText("escalate");
  await expect(page.getByTestId("jin-detail-name")).toHaveText("Refine");
  await expect(page.getByTestId("jin-detail-agent")).toHaveText("Refine_exit_check");
  await expect(page.getByTestId("jin-detail-pointer")).toHaveText("/circles/1/flow/exit");
  // **そのまま**出す（要約も切り詰めもしない）。
  await expect(page.getByTestId("jin-detail-input")).toContainText('"key": "approved"');
  await expect(page.getByTestId("jin-detail-input")).toContainText('"expected": true');
  await expect(page.getByTestId("jin-detail-output")).toContainText('"actual": "fake-response"');
  await expect(page.getByTestId("jin-detail-output")).toContainText('"matched": false');

  // `input: null` の行（model 行）も **null と書く**。欄ごと消さない。
  await page.locator('[data-testid="jin-trace-row"][data-seq="1"]').click();
  await expect(page.getByTestId("jin-detail-kind")).toHaveText("model");
  await expect(page.getByTestId("jin-detail-name")).toHaveText("gemini-2.5-flash");
  await expect(page.getByTestId("jin-detail-input")).toHaveText("null");
  await expect(page.getByTestId("jin-detail-output")).toHaveText('"fake-response"');
});

test("壊れた JSONL は行番号を添えて断り、図は残る（NFR-FAIL-001）", async ({ page }) => {
  const dir = mkdtempSync(join(tmpdir(), "jin-trace-"));
  const broken = join(dir, "broken.jsonl");
  // 3 行目が壊れている（1 行目は空行なので、並びの位置とはずれる）。
  writeFileSync(broken, '\n{"seq": 1, "pointer": null}\nこわれている\n', "utf8");

  const canvas = await openTrace(page, broken);
  await expect(page.getByTestId("jin-trace-error")).toContainText("broken.jsonl:3:");
  // **図は消えない。** 壊れているのはトレースであって `.jin` ではない。
  await expect(canvas.locator("svg")).toBeVisible();
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");
  await expect(canvas.locator('[data-jin-fired="1"]')).toHaveCount(0);

  // 行の契約違反（`seq` が整数でない）はサーバ（`jin_render.overlay`）が拒む。
  // エディタはその文言をそのまま出し、トレースを外して図を出し直す。
  const badSeq = join(dir, "bad-seq.jsonl");
  writeFileSync(badSeq, '{"seq": "x", "pointer": null}\n', "utf8");
  await page.getByTestId("jin-trace-file").setInputFiles(badSeq);
  await expect(page.getByTestId("jin-trace-error")).toContainText("seq");
  await expect(canvas.locator("svg")).toBeVisible();
  await expect(page.getByTestId("jin-status")).toHaveAttribute("data-state", "ready");
});

test("編集モードとデバッグモードが同じ面・同じ選択を共有する（DP-COMMON-18）", async ({
  page,
}) => {
  const canvas = await openTrace(page);
  await canvas.locator('[data-jin="/circles/2/core"]').first().click();
  await expect(page.getByTestId("jin-trace-selected")).toHaveText("/circles/2/core");

  // 編集モードへ戻ると同じ選択のフォームが出る（選択は 3 つ組で保たれている）。
  await page.getByTestId("jin-mode-edit").click();
  await expect(page.getByTestId("jin-form")).toBeVisible();
  await expect(page.getByTestId("jin-pointer")).toHaveText("/circles/2/core");

  // 編集してもトレースは保持される（読み込み直さずにスクラブできる）。
  await page.getByTestId("jin-add-state").click();
  await expect(canvas.locator('[data-jin-fired="1"]')).toHaveCount(5);
  await page.getByTestId("jin-mode-debug").click();
  await expect(page.getByTestId("jin-trace-row")).toHaveCount(11);
  await scrub(page, 2);
  await expect(canvas.locator('[data-jin-fired="1"]')).toHaveCount(2);
});
