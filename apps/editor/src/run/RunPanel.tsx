import { useEffect, useRef, useState } from "react";

import type { Replay } from "../debug/replay";
import type { JinGenerated } from "../rpc/protocol";
import { eventsFiredAt } from "../trace/filter";
import {
	maxSeq,
	pointerOf,
	seqOf,
	stringOf,
	type TraceRow,
} from "../trace/parse";

/**
 * 実行パネル（Jin v2・設計書 §8「実行パネル」）。
 *
 * **同一オリジンの iframe `/play/`** にプレイヤー（`apps/player` のビルド物。`jin editor` が
 * `/play/` として配る）を読み込み、`jin/model` / `jin/applyOps` の応答に載った JIL と manifest を
 * `postMessage({ type: "jin.load" })` で渡す。**保存しなくても動く**（ライブリロード）。
 * **`POST /run` は使わない**（それは v1 の ADK 実行の口・`docs/spec/ops.md` §5.2）。
 *
 * プレイヤーはトレース行を `postMessage({ type: "jin.trace", rows })` で返す。受け取った行は
 * 親（`App`）が `Replay` に積み、`jin/renderSvg` に `trace` + `upto` を付けて描き直す
 * （オーバーレイを描くのは `jin_render` 1 本・v1 のデバッグモードと同じ）。
 *
 * 操作（実行 / 一時停止 / 1 tick / 最初から）は `postMessage({ type: "jin.control" })` で
 * プレイヤーへ送る。iframe の中のボタンも同じ関数を呼ぶ。
 *
 * **message の送り先と受け取り元は iframe の `contentWindow` に限る**（プレイヤー側が
 * `window.parent` に限るのと対）。
 */
export interface RunPanelProps {
	/** `jin/model` / `jin/applyOps` の応答の JIL と manifest（v2 だけ。無ければ null）。 */
	readonly generated: JinGenerated | null;
	readonly replay: Replay | null;
	readonly selectedPointer: string | null;
	/** 行数の上限に当たった / 描画できなかった理由。**黙って捨てない**（NFR-FAIL-001）。 */
	readonly traceError: string | null;
	readonly onTrace: (rows: readonly TraceRow[]) => void;
	readonly onControl: (action: PlayerControl) => void;
	readonly onUpto: (upto: number) => void;
}

export type PlayerControl = "start" | "pause" | "step" | "reboot";

/** `jin editor` が配るプレイヤーの場所（このページからの相対）。 */
export const PLAYER_PATH = "./play/";

export function RunPanel(props: RunPanelProps): React.JSX.Element {
	const frame = useRef<HTMLIFrameElement>(null);
	const [loaded, setLoaded] = useState(false);
	const [missing, setMissing] = useState<string | null>(null);
	const [filtering, setFiltering] = useState(false);

	// プレイヤーの有無を先に見る（iframe の 404 は親から読めない）。
	useEffect(() => {
		let cancelled = false;
		void fetch(`${PLAYER_PATH}index.html`, { method: "HEAD" })
			.then((response) => {
				if (!cancelled && !response.ok) {
					setMissing(
						"プレイヤーが見つかりません（apps/player で pnpm build するか、jin editor --player-dist で場所を指定してください）",
					);
				}
			})
			.catch(() => {
				if (!cancelled) setMissing("プレイヤーを確かめられません");
			});
		return () => {
			cancelled = true;
		};
	}, []);

	// JIL が変わるたび（＝編集のたび）にプレイヤーへ差し替えを送る。
	// **中身で比べる**（`jil` は文字列、manifest は `jil` の sha256 を鍵にする）。応答のたびに
	// 新しいオブジェクトが来るので、参照で比べるとスクラブや focus の切り替えのたびに
	// ゲームが最初からになる。
	const jil = props.generated?.jil ?? null;
	const manifest = useRef(props.generated?.manifest ?? null);
	manifest.current = props.generated?.manifest ?? null;
	const manifestKey = manifest.current?.jil ?? null;
	useEffect(() => {
		const target = frame.current?.contentWindow;
		if (!loaded || target === null || target === undefined) return;
		if (jil === null || manifest.current === null) return;
		target.postMessage(
			{ type: "jin.load", jil, manifest: manifest.current },
			window.location.origin,
		);
	}, [loaded, jil, manifestKey]);

	// プレイヤーからのトレース。**この iframe からのものだけ**を受け取る。
	const onTrace = props.onTrace;
	useEffect(() => {
		const handler = (event: MessageEvent<unknown>): void => {
			if (event.source !== frame.current?.contentWindow) return;
			const data = event.data as { type?: unknown; rows?: unknown } | null;
			if (
				data === null ||
				typeof data !== "object" ||
				data.type !== "jin.trace"
			)
				return;
			if (!Array.isArray(data.rows)) return;
			onTrace(data.rows as readonly TraceRow[]);
		};
		window.addEventListener("message", handler);
		return () => window.removeEventListener("message", handler);
	}, [onTrace]);

	const control = (action: PlayerControl): void => {
		frame.current?.contentWindow?.postMessage(
			{ type: "jin.control", action },
			window.location.origin,
		);
		props.onControl(action);
	};

	const replay = props.replay;
	const events = replay?.events ?? [];
	const shown = eventsFiredAt(events, filtering ? props.selectedPointer : null);
	const upper = maxSeq(events);
	const jilError = props.generated?.jilError ?? null;

	return (
		<section className="jin-run-panel" data-testid="jin-run-panel">
			<h2>実行（プレイヤー）</h2>
			{missing === null ? null : (
				<p className="jin-trace-error" data-testid="jin-player-missing">
					{missing}
				</p>
			)}
			{jilError === null ? null : (
				<p className="jin-trace-error" data-testid="jin-jil-error">
					JIL を作れません: {jilError}
				</p>
			)}
			<div className="jin-run-controls">
				<button
					type="button"
					data-testid="jin-play-start"
					onClick={() => control("start")}
				>
					実行
				</button>
				<button
					type="button"
					data-testid="jin-play-pause"
					onClick={() => control("pause")}
				>
					一時停止
				</button>
				<button
					type="button"
					data-testid="jin-play-step"
					onClick={() => control("step")}
				>
					1 tick
				</button>
				<button
					type="button"
					data-testid="jin-play-reboot"
					onClick={() => control("reboot")}
				>
					最初から
				</button>
			</div>
			<iframe
				ref={frame}
				className="jin-player"
				data-testid="jin-player"
				title="Jin player"
				src={PLAYER_PATH}
				// 同一オリジンで、親とだけ話す。ダウンロード（録画の書き出し）は許す。
				sandbox="allow-scripts allow-same-origin allow-downloads"
				onLoad={() => setLoaded(true)}
			/>
			{props.traceError === null ? null : (
				<p className="jin-trace-error" data-testid="jin-trace-error">
					{props.traceError}
				</p>
			)}
			{replay === null ? (
				<p className="jin-hint">実行するとトレースが図に重なります。</p>
			) : (
				<>
					<p className="jin-hint" data-testid="jin-trace-name">
						{replay.name}（{events.length} 件）
					</p>
					<label className="jin-field">
						<span>
							upto <output data-testid="jin-upto-value">{replay.upto}</output> /{" "}
							{upper}
						</span>
						<input
							type="range"
							data-testid="jin-upto"
							min={0}
							max={upper}
							step={1}
							value={replay.upto}
							disabled={upper === 0}
							onChange={(event) => props.onUpto(Number(event.target.value))}
						/>
					</label>
					<label className="jin-check">
						<input
							type="checkbox"
							data-testid="jin-trace-filter"
							checked={filtering}
							disabled={props.selectedPointer === null}
							onChange={(event) => setFiltering(event.target.checked)}
						/>
						<span>この要素で発火した行だけ</span>
					</label>
					<ol className="jin-trace-rows" data-testid="jin-trace-rows">
						{shown.slice(-200).map((event) => (
							<li key={event.line}>
								<button
									type="button"
									data-testid="jin-trace-row"
									data-seq={String(seqOf(event) ?? "")}
									data-pointer={pointerOf(event) ?? ""}
									data-fired={fired(seqOf(event), replay.upto) ? "1" : "0"}
								>
									<span className="jin-trace-seq">{seqOf(event) ?? "?"}</span>
									<span className="jin-trace-kind">
										{stringOf(event, "kind") ?? "?"}
									</span>
									<span className="jin-trace-agent">
										{stringOf(event, "circle") ?? ""}
									</span>
									<span className="jin-trace-name">
										{stringOf(event, "name") ?? ""}
									</span>
								</button>
							</li>
						))}
					</ol>
				</>
			)}
		</section>
	);
}

function fired(seq: number | null, upto: number): boolean {
	return seq !== null && seq <= upto;
}
