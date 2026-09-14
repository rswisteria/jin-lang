import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Replay } from "../debug/replay";
import {
	assertsAt,
	formatValue,
	frameAt,
	stateValuesAt,
} from "../debug/values";
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
 * 実行パネル（Jin v2・設計書 §8「実行パネル」・Phase 6 のデバッグ）。
 *
 * **同一オリジンの iframe `/play/`** にプレイヤー（`apps/player` のビルド物。`jin editor` が
 * `/play/` として配る）を読み込み、`jin/model` / `jin/applyOps` の応答に載った JIL と manifest を
 * `postMessage({ type: "jin.load" })` で渡す。**保存しなくても動く**（ライブリロード）。
 * **`POST /run` は使わない**（それは v1 の ADK 実行の口・`docs/spec/ops.md` §5.2）。
 *
 * 差し替えは既定で**状態を保つ**（`keep`・設計書 §11 #42）: プレイヤーが直前の tick 結果の `snapshot` を
 * 新しい JIL の `boot` に渡し、陣を名前で照合して state / tick / 乱数列を続ける。root が照合できない
 * （陣の改名など）ときはプレイヤーが最初からに落とし、`jin.status` の `notice` でそう言う。トレースは
 * 続けたときは続き（seq が通し）、最初からになったときは親（`App`）が世代（`generation`）の変化で捨てる。
 *
 * プレイヤーとの語彙（runtime.md §10）:
 * - 親 → プレイヤー: `jin.load`（JIL / manifest / keep）、`jin.control`（実行 / 一時停止 / 1 tick /
 *   最初から（seed）/ 録画 / 録画を止める / 記憶を消す / 止める・起こす（`suspend` / `wake`・隠れている間）、
 *   `jin.replay`（`.jinrec` のテキストを最初から再生）、
 *   `jin.frame`（スクラブ中の画面 = トレースの `frame` 行の表示リスト）
 * - プレイヤー → 親: `jin.trace`（トレース行。tick ごと / 再生では 1 回）、`jin.status`
 *   （状態が変わるたび）、`jin.recording`（録画を止めたときの `.jinrec` のテキスト。書き出しは親）
 *
 * 受け取った行は親（`App`）が `Replay` に積み、`jin/renderSvg` に `trace` + `upto` を付けて描き直す
 * （オーバーレイを描くのは `jin_render` 1 本・v1 のデバッグモードと同じ）。ここで**積算する**のは
 * runtime.md §5 が「エディタのスクラバの仕事」と書いた記憶環の値と `assert`（`debug/values.ts`）だけ。
 *
 * ファイル入力は `.jinrec`（録画 → プレイヤーで再生）と `jin run --trace` の JSONL（そのまま載せる）
 * の両方を受ける。見分けるのは 1 行目に `"jinrec"` が有るかだけで、`.jinrec` の中身は読まない
 * （読み手はプレイヤー側の `jinrec.ts`。壊れていればプレイヤーが行番号付きで断る）。
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
	/** 開いている `.jin` のファイル名（録画の書き出し名に使う）。 */
	readonly fileName: string;
	/**
	 * 編集モードでは隠す（外さない）。外すと iframe ごとプレイヤーが消えて、編集して戻ったときに
	 * 状態が続かない。隠れている間も `jin.load` は送る（編集のたびに差し替わる）が、プレイヤーは
	 * 止めておく（`jin.control` の `suspend` / `wake`・Issue #66）。見えないゲームが走ると親が
	 * 1 秒ごとに図を描き直し、編集のクリック / ドラッグと重なる。
	 */
	readonly hidden?: boolean;
	readonly onTrace: (rows: readonly TraceRow[]) => void;
	readonly onControl: (action: PlayerControl) => void;
	readonly onUpto: (upto: number) => void;
	/** 録画（`.jinrec`）の再生を始めた。次に届く行はこの録画のもの。 */
	readonly onReplay: (name: string) => void;
	/** `jin run --trace` の JSONL を選んだ（プレイヤーは使わない）。 */
	readonly onLoadTrace: (file: File) => void;
	/** プレイヤーの状態が変わった（止まったら親は即座に描き直す）。 */
	readonly onStatus: (status: PlayerStatus) => void;
}

export type PlayerControl =
	| "start"
	| "pause"
	| "step"
	| "reboot"
	| "record"
	| "stop"
	| "forget";

/** プレイヤーが `jin.status` で知らせる状態（runtime.md §10）。 */
export interface PlayerStatus {
	readonly loaded: boolean;
	readonly tick: number;
	readonly seed: number | null;
	readonly running: boolean;
	readonly done: boolean;
	readonly error: string | null;
	readonly recording: boolean;
	readonly recordedEvents: number;
	/** boot し直すたびに増える世代。状態を保った差し替えでは変わらない（親はこれでトレースを捨てる）。 */
	readonly generation: number;
	readonly notice: string | null;
}

/** `jin editor` が配るプレイヤーの場所（このページからの相対）。 */
export const PLAYER_PATH = "./play/";

/** 1 行目に `"jinrec"` の鍵があれば録画（runtime.md §7）。中身の検査はプレイヤーの読み手が行う。 */
export function looksLikeJinrec(text: string): boolean {
	const body = text.startsWith("﻿") ? text.slice(1) : text;
	const first = body.split("\n").find((line) => line.trim() !== "");
	if (first === undefined) return false;
	try {
		const value: unknown = JSON.parse(
			first.endsWith("\r") ? first.slice(0, -1) : first,
		);
		return value !== null && typeof value === "object" && "jinrec" in value;
	} catch {
		return false;
	}
}

/** `.jinrec` の書き出し名: `<jin の名前>-seed<seed>-<ticks>t.jinrec`。 */
export function recordingFileName(
	fileName: string,
	seed: number,
	ticks: number,
): string {
	const stem = fileName.replace(/\.jin$/, "") || "game";
	return `${stem}-seed${String(seed)}-${String(ticks)}t.jinrec`;
}

function isStatus(value: unknown): value is PlayerStatus {
	return (
		value !== null &&
		typeof value === "object" &&
		typeof (value as { tick?: unknown }).tick === "number" &&
		typeof (value as { running?: unknown }).running === "boolean" &&
		typeof (value as { generation?: unknown }).generation === "number"
	);
}

export function RunPanel(props: RunPanelProps): React.JSX.Element {
	const frame = useRef<HTMLIFrameElement>(null);
	const [loaded, setLoaded] = useState(false);
	const [missing, setMissing] = useState<string | null>(null);
	const [filtering, setFiltering] = useState(false);
	const [status, setStatus] = useState<PlayerStatus | null>(null);
	const [seedText, setSeedText] = useState("");
	// 差し替えで状態を保つか（既定 on）。効くのは tick が進んでいるときだけで、判断はプレイヤーが行う。
	// effect の依存に入れない（切り替えただけで `jin.load` を送り直さない）ので ref で読む。
	const [keep, setKeep] = useState(true);
	const keepRef = useRef(keep);
	keepRef.current = keep;
	const [lastRecording, setLastRecording] = useState<{
		readonly name: string;
		readonly text: string;
	} | null>(null);

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

	const post = useCallback(
		(message: Readonly<Record<string, unknown>>): void => {
			frame.current?.contentWindow?.postMessage(
				message,
				window.location.origin,
			);
		},
		[],
	);

	// 隠れている間（編集モード）はプレイヤーを止めておく（Issue #66・設計書 §11 #54）。見えないゲームが
	// 走り続けると、トレースを受けた親が 1 秒ごとに `jin/renderSvg` を往復して図を差し替え、編集の
	// クリック / ドラッグが差し替えと重なる。止める / 起こすの判断はプレイヤーが持つ（`suspend` は
	// 走っていたかを覚え、止められている間の `jin.load` は走り出さず、`wake` で走る）ので、ここは
	// `hidden` の変化を送るだけ。`control()` を通さない（親の `onControl` に知らせる操作ではない）。
	const hidden = props.hidden === true;
	useEffect(() => {
		if (!loaded) return;
		post({ type: "jin.control", action: hidden ? "suspend" : "wake" });
	}, [loaded, hidden, post]);

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
			{
				type: "jin.load",
				jil,
				manifest: manifest.current,
				keep: keepRef.current,
			},
			window.location.origin,
		);
	}, [loaded, jil, manifestKey]);

	// プレイヤーからの message。**この iframe からのものだけ**を受け取る。
	const { onTrace, onStatus, fileName } = props;
	useEffect(() => {
		const handler = (event: MessageEvent<unknown>): void => {
			if (event.source !== frame.current?.contentWindow) return;
			const data = event.data as {
				type?: unknown;
				rows?: unknown;
				text?: unknown;
				seed?: unknown;
				ticks?: unknown;
			} | null;
			if (data === null || typeof data !== "object") return;
			if (data.type === "jin.trace") {
				if (Array.isArray(data.rows)) onTrace(data.rows as readonly TraceRow[]);
			} else if (data.type === "jin.status") {
				if (!isStatus(data)) return;
				setStatus(data);
				setSeedText((current) =>
					current === "" && data.seed !== null ? String(data.seed) : current,
				);
				onStatus(data);
			} else if (data.type === "jin.recording") {
				if (typeof data.text !== "string") return;
				const seed = typeof data.seed === "number" ? data.seed : 0;
				const ticks = typeof data.ticks === "number" ? data.ticks : 0;
				const name = recordingFileName(fileName, seed, ticks);
				setLastRecording({ name, text: data.text });
				download(name, data.text);
			}
		};
		window.addEventListener("message", handler);
		return () => window.removeEventListener("message", handler);
	}, [onTrace, onStatus, fileName]);

	const seed = ((): number | null => {
		const value = Number.parseInt(seedText, 10);
		return Number.isFinite(value) ? value : null;
	})();

	const control = (action: PlayerControl): void => {
		const message: Record<string, unknown> = { type: "jin.control", action };
		if ((action === "reboot" || action === "record") && seed !== null)
			message["seed"] = seed;
		post(message);
		props.onControl(action);
	};

	const replayText = (name: string, text: string): void => {
		props.onReplay(name);
		post({ type: "jin.replay", text });
	};

	const openFile = async (file: File): Promise<void> => {
		let text: string;
		try {
			text = await file.text();
		} catch {
			// 読めない理由は trace の読み口（`loadTrace`）が同じファイルで報告する。
			props.onLoadTrace(file);
			return;
		}
		if (looksLikeJinrec(text)) replayText(file.name, text);
		else props.onLoadTrace(file);
	};

	// スクラブ中の画面: `upto` の位置の `frame` 行の表示リストをプレイヤーに描かせる（止まっている間だけ）。
	const replay = props.replay;
	const events = replay?.events ?? [];
	const upto = replay?.upto ?? 0;
	const shownFrame = useMemo(
		() => (replay === null ? null : frameAt(replay.events, replay.upto)),
		[replay],
	);
	const running = status?.running ?? false;
	useEffect(() => {
		if (shownFrame === null || running) return;
		post({ type: "jin.frame", ops: shownFrame });
	}, [shownFrame, running, post]);

	const values = useMemo(() => stateValuesAt(events, upto), [events, upto]);
	const asserts = useMemo(() => assertsAt(events, upto), [events, upto]);
	const shown = eventsFiredAt(events, filtering ? props.selectedPointer : null);
	const upper = maxSeq(events);
	const jilError = props.generated?.jilError ?? null;

	return (
		<section
			className="jin-run-panel"
			data-testid="jin-run-panel"
			hidden={props.hidden === true}
		>
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
				<button
					type="button"
					data-testid="jin-forget"
					title="storage の記憶（localStorage）を空にして最初から"
					onClick={() => control("forget")}
				>
					記憶を消す
				</button>
				<label className="jin-seed">
					seed{" "}
					<input
						type="number"
						step={1}
						data-testid="jin-seed"
						value={seedText}
						onChange={(event) => setSeedText(event.target.value)}
					/>
				</label>
				{status?.recording === true ? (
					<button
						type="button"
						data-testid="jin-play-stop"
						onClick={() => control("stop")}
					>
						録画を止めて書き出す
					</button>
				) : (
					<button
						type="button"
						data-testid="jin-play-record"
						onClick={() => control("record")}
					>
						録画
					</button>
				)}
				{lastRecording === null ? null : (
					<button
						type="button"
						data-testid="jin-replay-last"
						onClick={() => replayText(lastRecording.name, lastRecording.text)}
					>
						この録画を再生
					</button>
				)}
				<label className="jin-check">
					<input
						type="checkbox"
						data-testid="jin-keep-state"
						checked={keep}
						onChange={(event) => setKeep(event.target.checked)}
					/>
					<span>編集しても状態を保つ</span>
				</label>
			</div>
			<p className="jin-hint" data-testid="jin-player-status">
				{status === null
					? "プレイヤーの状態を待っています"
					: statusLine(status)}
			</p>
			{status?.notice === null || status?.notice === undefined ? null : (
				<p className="jin-hint" data-testid="jin-player-notice">
					{status.notice}
				</p>
			)}
			{status?.error === null || status?.error === undefined ? null : (
				<p className="jin-trace-error" data-testid="jin-player-error">
					{status.error}
				</p>
			)}
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
			<label className="jin-field">
				<span>録画（.jinrec）か `jin run --trace` の JSONL を読む</span>
				<input
					type="file"
					data-testid="jin-run-file"
					accept=".jinrec,.jsonl,.json,.log,text/plain,application/json,application/x-ndjson"
					onChange={(event) => {
						const file = event.target.files?.[0];
						// **同じファイルを選び直しても発火させる**（DebugPanel と同じ技）。
						event.target.value = "";
						if (file !== undefined) void openFile(file);
					}}
				/>
			</label>
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

					{/* 記憶環の値（runtime.md §5 の積算）。図のラベルと同じ値を全部出す。 */}
					<table className="jin-state-values" data-testid="jin-state-values">
						<tbody>
							{[...values.entries()].flatMap(([circle, states]) =>
								[...states.entries()].map(([name, value]) => (
									<tr
										key={`${circle}.${name}`}
										data-testid="jin-state-value"
										data-circle={circle}
										data-name={name}
									>
										<th scope="row">
											{circle}.{name}
										</th>
										<td>{JSON.stringify(value) ?? ""}</td>
									</tr>
								)),
							)}
						</tbody>
					</table>
					{asserts.length === 0 ? null : (
						<ul className="jin-asserts" data-testid="jin-asserts">
							{asserts.map((hit) => (
								<li
									key={hit.seq}
									data-testid="jin-assert"
									data-seq={String(hit.seq)}
									data-pointer={hit.pointer}
								>
									<span className="jin-trace-seq">{hit.seq}</span>{" "}
									{hit.circle ?? ""} {formatValue(hit.message)}
								</li>
							))}
						</ul>
					)}

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

function statusLine(status: PlayerStatus): string {
	if (!status.loaded) return "プレイヤーは JIL を待っています";
	const parts = [
		`tick ${String(status.tick)}`,
		status.seed === null ? "" : `seed ${String(status.seed)}`,
		status.running ? "実行中" : status.done ? "終了" : "停止",
	];
	if (status.recording)
		parts.push(`録画中 ${String(status.recordedEvents)} events`);
	return parts.filter((part) => part !== "").join(" · ");
}

function fired(seq: number | null, upto: number): boolean {
	return seq !== null && seq <= upto;
}

/** テキストをブラウザのダウンロードとして渡す（録画の書き出し）。 */
function download(name: string, text: string): void {
	const blob = new Blob([text], { type: "application/x-ndjson" });
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	a.click();
	window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
