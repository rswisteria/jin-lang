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
	readonly names: StageNames;
	readonly fps: number;
	readonly jinName: string;
	readonly circleName: string;
}

export interface TraceMessage {
	readonly rows: readonly TraceRow[];
	readonly seed: number | null;
}

export type Inbound = { readonly type: "scene"; readonly value: SceneMessage } | { readonly type: "trace"; readonly value: TraceMessage };

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
		typeof value["circle"] === "string" &&
		typeof value["kind"] === "string" &&
		typeof value["pointer"] === "string"
	);
}

export function parseInbound(data: unknown): Inbound | null {
	if (!isRecord(data)) return null;
	if (data["type"] === STAGE_SCENE) {
		const { svg, names, fps, jinName, circleName } = data;
		if (typeof svg !== "string" || !isRecord(names) || typeof fps !== "number" || !(fps > 0)) return null;
		if (typeof jinName !== "string" || typeof circleName !== "string") return null;
		return { type: "scene", value: { svg, names: names as StageNames, fps, jinName, circleName } };
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

export function fileMessage(name: string, mime: string, bytes: ArrayBuffer): Record<string, unknown> {
	return { type: STAGE_FILE, name, mime, bytes };
}
