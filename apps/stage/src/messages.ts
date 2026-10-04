import type { StageNames, TraceRow } from "./names";

/**
 * エディタとの語彙（docs/spec/v2/stage.md §6）。**stage 側で語を書いてよいのはこのファイルだけ**
 * （エディタ側は `apps/editor/src/stage/StagePanel.tsx`。`tests/contract/test_stage_contract.py` が等号で見る）。
 */
export const STAGE_SCENE = "stage.scene";
export const STAGE_TRACE = "stage.trace";
export const STAGE_STATUS = "stage.status";
export const STAGE_FILE = "stage.file";

export interface SceneMessage {
	readonly svg: string;
	/** 銘環の帯の SVG（陣書き S7・stage.md §2.2）。無い・文字列でなければ null（帯を描かない・古いエディタ）。 */
	readonly inscription: string | null;
	readonly names: StageNames;
	readonly fps: number;
	readonly jinName: string;
	readonly circleName: string;
	/** 舞台の大きさ（論理解像度・仕様書 2026-10-01-jin-stage-summon §2.1）。無い・壊れていれば null（召喚の窓を出さない）。 */
	readonly stageSize: {
		readonly width: number;
		readonly height: number;
	} | null;
}

/**
 * 舞台の大きさの範囲（モデルの `Stage.width` / `height` と同じ・整数）。stage はリポジトリのファイルを読まないので写しを持ち、
 * `tests/contract/test_stage_contract.py` が `schemas/jin-v2.schema.json` と突き合わせる。
 */
export const MIN_STAGE_SIZE = 16;
export const MAX_STAGE_SIZE = 1024;

function isStageSide(value: unknown): value is number {
	return (
		typeof value === "number" &&
		Number.isInteger(value) &&
		value >= MIN_STAGE_SIZE &&
		value <= MAX_STAGE_SIZE
	);
}

/** 範囲の外は丸めずに null（窓を出さない）。巨大な値で窓の canvas とテクスチャを作らない。 */
function stageSizeOf(value: unknown): SceneMessage["stageSize"] {
	if (!isRecord(value)) return null;
	const { width, height } = value;
	if (!isStageSide(width) || !isStageSide(height)) return null;
	return { width, height };
}

export interface TraceMessage {
	readonly rows: readonly TraceRow[];
	readonly seed: number | null;
}

export type Inbound =
	| { readonly type: "scene"; readonly value: SceneMessage }
	| { readonly type: "trace"; readonly value: TraceMessage };

export interface StageStatus {
	readonly ready: boolean;
	readonly rows: number;
	readonly codec: "avc" | "vp9" | null;
	readonly exporting: { readonly done: number; readonly total: number } | null;
	readonly error: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isRow(value: unknown): value is TraceRow {
	return (
		isRecord(value) &&
		typeof value["seq"] === "number" &&
		typeof value["tick"] === "number" &&
		(typeof value["circle"] === "string" || value["circle"] === null) &&
		typeof value["kind"] === "string" &&
		typeof value["pointer"] === "string"
	);
}

export function parseInbound(data: unknown): Inbound | null {
	if (!isRecord(data)) return null;
	if (data["type"] === STAGE_SCENE) {
		const { svg, names, fps, jinName, circleName } = data;
		if (
			typeof svg !== "string" ||
			!isRecord(names) ||
			typeof fps !== "number" ||
			!(fps > 0)
		)
			return null;
		if (typeof jinName !== "string" || typeof circleName !== "string")
			return null;
		return {
			type: "scene",
			value: {
				svg,
				inscription:
					typeof data["inscription"] === "string" ? data["inscription"] : null,
				names: names as StageNames,
				fps,
				jinName,
				circleName,
				stageSize: stageSizeOf(data["stageSize"]),
			},
		};
	}
	if (data["type"] === STAGE_TRACE) {
		const { rows, seed } = data;
		if (!Array.isArray(rows) || !rows.every(isRow)) return null;
		if (seed !== null && typeof seed !== "number") return null;
		return { type: "trace", value: { rows, seed } };
	}
	return null;
}

export function statusMessage(status: StageStatus): Record<string, unknown> {
	return { type: STAGE_STATUS, ...status };
}

export function fileMessage(
	name: string,
	mime: string,
	bytes: ArrayBuffer,
): Record<string, unknown> {
	return { type: STAGE_FILE, name, mime, bytes };
}
