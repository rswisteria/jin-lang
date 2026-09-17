import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { TraceRow } from "../trace/parse";
import { buildStageNames } from "./names";

/**
 * 鑑賞モード（Jin v2・docs/spec/v2/stage.md・設計書 §1）。
 *
 * **同一オリジンの iframe `/stage/`**（`jin editor` が `apps/stage/dist` を配る）に、
 * オーバーレイ無しの SVG・名前の表・トレース行を渡すだけ。**エディタは 3D を描かない**
 * （three は `apps/stage` にだけある）。書き出されたファイルは親がダウンロードさせる。
 *
 * 語彙（stage.md §6。**エディタ側で語を書いてよいのはこのファイルだけ**）:
 * - 親 → stage: `stage.scene`（svg / names / fps / jinName / circleName）、`stage.trace`（rows / seed）
 * - stage → 親: `stage.status`（ready / rows / codec / exporting / error）、`stage.file`（name / mime / bytes）
 */
export const STAGE_PATH = "./stage/";

export interface StagePanelProps {
	/** `jin/renderSvg` の**オーバーレイ無し**の SVG。 */
	readonly svg: string | null;
	readonly model: Readonly<Record<string, unknown>> | null;
	readonly rows: readonly TraceRow[];
	readonly seed: number | null;
	readonly fileName: string;
	readonly circleName: string;
	readonly hidden: boolean;
}

interface StageStatusView {
	readonly ready: boolean;
	readonly rows: number;
	readonly codec: string | null;
	readonly exporting: { readonly done: number; readonly total: number } | null;
	readonly error: string | null;
}

export function stageFps(model: Readonly<Record<string, unknown>> | null): number {
	const stage = model?.["stage"];
	const fps = stage !== null && typeof stage === "object" ? (stage as { fps?: unknown }).fps : undefined;
	return typeof fps === "number" && fps > 0 ? fps : 60;
}

export function rootCircleName(model: Readonly<Record<string, unknown>> | null, focus: string | null): string {
	if (focus !== null) return focus.split("/")[0] ?? "";
	const root = model?.["root"];
	return typeof root === "string" ? root : "";
}

export function StagePanel(props: StagePanelProps): React.JSX.Element {
	const frame = useRef<HTMLIFrameElement>(null);
	const [loaded, setLoaded] = useState(false);
	const [missing, setMissing] = useState<string | null>(null);
	const [status, setStatus] = useState<StageStatusView | null>(null);

	useEffect(() => {
		let cancelled = false;
		void fetch(`${STAGE_PATH}index.html`, { method: "HEAD" })
			.then((response) => {
				if (!cancelled && !response.ok) {
					setMissing("鑑賞ページが見つかりません（apps/stage で pnpm build するか、jin editor --stage-dist で場所を指定してください）");
				}
			})
			.catch(() => {
				if (!cancelled) setMissing("鑑賞ページを確かめられません");
			});
		return () => {
			cancelled = true;
		};
	}, []);

	const post = useCallback((message: Readonly<Record<string, unknown>>): void => {
		frame.current?.contentWindow?.postMessage(message, window.location.origin);
	}, []);

	const names = useMemo(() => (props.model === null ? {} : buildStageNames(props.model)), [props.model]);
	const fps = stageFps(props.model);
	const { svg, fileName, circleName, rows, seed } = props;

	useEffect(() => {
		if (!loaded || svg === null) return;
		post({ type: "stage.scene", svg, names, fps, jinName: fileName, circleName });
	}, [loaded, svg, names, fps, fileName, circleName, post]);

	useEffect(() => {
		if (!loaded) return;
		post({ type: "stage.trace", rows, seed });
	}, [loaded, rows, seed, post]);

	useEffect(() => {
		const handler = (event: MessageEvent<unknown>): void => {
			if (event.source !== frame.current?.contentWindow) return;
			const data = event.data as Record<string, unknown> | null;
			if (data === null || typeof data !== "object") return;
			if (data["type"] === "stage.status") {
				setStatus(data as unknown as StageStatusView);
			} else if (data["type"] === "stage.file") {
				const { name, mime, bytes } = data;
				if (typeof name === "string" && typeof mime === "string" && bytes instanceof ArrayBuffer) download(name, mime, bytes);
			}
		};
		window.addEventListener("message", handler);
		return () => window.removeEventListener("message", handler);
	}, []);

	return (
		<section className="jin-stage-panel" data-testid="jin-stage-panel" hidden={props.hidden}>
			{missing === null ? null : (
				<p className="jin-trace-error" data-testid="jin-stage-missing">
					{missing}
				</p>
			)}
			<p className="jin-hint" data-testid="jin-stage-status">
				{status === null
					? "鑑賞ページを待っています"
					: status.error ?? `トレース ${String(status.rows)} 行${status.exporting === null ? "" : `・書き出し中 ${String(status.exporting.done)} / ${String(status.exporting.total)}`}`}
			</p>
			{props.rows.length === 0 ? (
				<p className="jin-hint">「実行」で録画（.jinrec）を再生すると、その詠唱で陣が発動します。</p>
			) : null}
			<iframe
				ref={frame}
				className="jin-stage"
				data-testid="jin-stage"
				title="Jin stage"
				src={STAGE_PATH}
				sandbox="allow-scripts allow-same-origin"
				onLoad={() => setLoaded(true)}
			/>
		</section>
	);
}

function download(name: string, mime: string, bytes: ArrayBuffer): void {
	const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	a.click();
	window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
