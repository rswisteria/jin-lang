import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
	buildPaddleWithPlayer,
	serveDirectory,
	type StaticServer,
} from "./harness";

/**
 * 状態を保った差し替え（runtime.md §1 の `manifest.resume`・設計書 §11 #42）を**実ブラウザ**で。
 *
 * lupa の側は `packages/jin-wasm/tests/test_resume.py` が「途切れずに走らせた列と一致」まで見るので、
 * ここで見るのは Wasmoon 経路だけの心配: JS のオブジェクト（`snapshot`）が proxy の userdata として
 * Lua に渡り、名前の照合・数値・空の `state`（paddle の root `Game` は state を持たない）・
 * 16 進の PCG32 状態が読めること。`__jinPlayer.load(jil, manifest, true)` で同じ JIL に差し替えても
 * tick と公開 state が続き、世代は変わらない。`keep` 無しは最初から（世代が進む）。
 */
let server: StaticServer;
let dist: string;

test.beforeAll(async () => {
	const built = buildPaddleWithPlayer();
	dist = built.dist;
	server = await serveDirectory(built.dist);
});

test.afterAll(async () => {
	await server?.close();
});

test("keep 付きの load は snapshot から続け（tick / 公開 state / 世代が続く）、keep 無しは最初から", async ({
	page,
}) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto(server.url);
	await page.waitForFunction(() => window.__jinPlayer?.ready === true);
	await page.waitForFunction(() => (window.__jinPlayer?.ticks() ?? 0) >= 20);
	await page.evaluate(() => window.__jinPlayer?.pause());

	const before = await page.evaluate(() => ({
		ticks: window.__jinPlayer?.ticks() ?? 0,
		seed: window.__jinPlayer?.seed() ?? 0,
		generation: window.__jinPlayer?.generation() ?? 0,
		publicState: window.__jinPlayer?.publicState() ?? {},
		trace: window.__jinPlayer?.trace().length ?? 0,
	}));
	expect(before.ticks).toBeGreaterThanOrEqual(20);
	expect(before.generation).toBeGreaterThan(0);

	const jil = readFileSync(join(dist, "game.lua"), "utf8");
	const manifest = JSON.parse(
		readFileSync(join(dist, "game.manifest.json"), "utf8"),
	) as Parameters<NonNullable<Window["__jinPlayer"]>["load"]>[1];

	// 状態を保って差し替える（止めたまま）。
	await page.evaluate(([j, m]) => window.__jinPlayer?.load(j, m, true), [
		jil,
		manifest,
	] as const);
	const kept = await page.evaluate(() => ({
		ticks: window.__jinPlayer?.ticks() ?? 0,
		seed: window.__jinPlayer?.seed() ?? 0,
		running: window.__jinPlayer?.running() ?? true,
		generation: window.__jinPlayer?.generation() ?? 0,
		publicState: window.__jinPlayer?.publicState() ?? {},
		trace: window.__jinPlayer?.trace().length ?? 0,
	}));
	expect(kept.ticks).toBe(before.ticks);
	expect(kept.seed).toBe(before.seed);
	expect(kept.running).toBe(false);
	expect(kept.generation).toBe(before.generation);
	expect(kept.publicState).toEqual(before.publicState);
	expect(kept.trace).toBe(before.trace);

	// 1 tick 進めると復元の知らせが来て、tick は N + 1、行は通しで続く（seq が戻らない）。
	await page.evaluate(() => window.__jinPlayer?.step());
	const after = await page.evaluate(() => ({
		ticks: window.__jinPlayer?.ticks() ?? 0,
		resume: window.__jinPlayer?.lastResume() ?? null,
		generation: window.__jinPlayer?.generation() ?? 0,
		publicState: window.__jinPlayer?.publicState() ?? {},
		seqs: (window.__jinPlayer?.trace() ?? []).map((row) => row.seq),
	}));
	expect(after.ticks).toBe(before.ticks + 1);
	expect(after.generation).toBe(before.generation);
	expect(after.resume).toEqual({
		mode: "resumed",
		tick: before.ticks - 1,
		kept: ["Game", "Play", "Result"],
		dropped: [],
	});
	expect(after.seqs).toEqual(after.seqs.map((_, i) => i)); // 0, 1, 2, … と途切れない
	expect(after.seqs.length).toBeGreaterThan(before.trace);
	// 公開 state（`Play.score` / `Result.quit`）は同じ鍵のまま続く。
	expect(Object.keys(after.publicState).sort()).toEqual(
		Object.keys(before.publicState).sort(),
	);

	// keep 無し: 最初から走り出し、世代が進み、知らせは無い。
	await page.evaluate(([j, m]) => window.__jinPlayer?.load(j, m, false), [
		jil,
		manifest,
	] as const);
	const restarted = await page.evaluate(() => ({
		generation: window.__jinPlayer?.generation() ?? 0,
		resume: window.__jinPlayer?.lastResume() ?? null,
		running: window.__jinPlayer?.running() ?? false,
	}));
	expect(restarted.generation).toBe(before.generation + 1);
	expect(restarted.resume).toBeNull();
	expect(restarted.running).toBe(true);
	expect(errors).toEqual([]);
});
