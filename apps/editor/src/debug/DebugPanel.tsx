import { useState } from "react";

import { eventsFiredAt } from "../trace/filter";
import {
	maxSeq,
	pointerOf,
	seqOf,
	stringOf,
	type TraceEvent,
} from "../trace/parse";
import type { Replay } from "./replay";

/**
 * デバッグモードのパネル（要件書 §7.2）。
 *
 * ここが持つのは (1) トレースの読み込み口、(2) タイムラインスクラバ、
 * (3) イベント一覧と「この紋で発火したイベントだけ」のフィルタ、
 * (4) 選択イベントの詳細、の 4 つだけである。
 * **オーバーレイは描かない。** `upto` を親へ返し、親が `jin/renderSvg` を
 * `trace + upto` 付きで呼び、返ってきた SVG をそのまま埋める（要件書 §0）。
 */
export interface DebugPanelProps {
	readonly replay: Replay | null;
	/** 図で選ばれている要素の pointer。フィルタの基準になる。 */
	readonly selectedPointer: string | null;
	/** 読み込みに失敗した理由（`path:N: …`）。**黙って捨てない**（NFR-FAIL-001）。 */
	readonly error: string | null;
	readonly onLoad: (file: File) => void;
	readonly onUpto: (upto: number) => void;
	/** 実行中か。ボタンを二度押しさせない（サーバも 409 で断るが、押せる見た目にしない）。 */
	readonly running: boolean;
	/** 実行を頼めなかった / 落ちた理由。**黙って捨てない**（NFR-FAIL-001）。 */
	readonly runError: string | null;
	/** 終わったときの一言（`jin run` の stderr の最後の行）。 */
	readonly runSummary: string | null;
	readonly onRun: (prompt: string, model: string | null) => void;
}

export function DebugPanel(props: DebugPanelProps): React.JSX.Element {
	const [selectedLine, setSelectedLine] = useState<number | null>(null);
	const [filtering, setFiltering] = useState(false);
	const [prompt, setPrompt] = useState("");

	const replay = props.replay;
	const events = replay?.events ?? [];
	const shown = eventsFiredAt(events, filtering ? props.selectedPointer : null);
	const detail = events.find((event) => event.line === selectedLine) ?? null;
	const upper = maxSeq(events);

	return (
		<section className="jin-debug" data-testid="jin-debug">
			<h2>デバッグ（トレースリプレイ）</h2>

			{/*
			 * 実行（Issue #34・要件書 §7.2 のライブ実行）。**ここは LSP を通らない。**
			 * 同一オリジンの `POST /run`（`jin editor` が配っているのと同じサーバ）へ投げ、
			 * SSE で返ってくる行を親が `Replay` に積む。`jin/…` は増やさない。
			 */}
			<form
				className="jin-run"
				data-testid="jin-run-form"
				onSubmit={(event) => {
					event.preventDefault();
					if (!props.running && prompt !== "") props.onRun(prompt, "fake");
				}}
			>
				<label className="jin-field">
					<span>実行（最初の利用者メッセージ）</span>
					<input
						type="text"
						data-testid="jin-run-prompt"
						value={prompt}
						disabled={props.running}
						onChange={(event) => setPrompt(event.target.value)}
					/>
				</label>
				<button
					type="submit"
					data-testid="jin-run"
					disabled={props.running || prompt === ""}
				>
					{props.running ? "実行中…" : "fake モデルで実行"}
				</button>
			</form>

			{props.runError === null ? null : (
				<p className="jin-trace-error" data-testid="jin-run-error">
					{props.runError}
				</p>
			)}
			{props.runSummary === null ? null : (
				<p className="jin-hint" data-testid="jin-run-summary">
					{props.runSummary}
				</p>
			)}

			<label className="jin-field">
				<span>トレース（`jin run --trace` の JSONL）</span>
				<input
					type="file"
					data-testid="jin-trace-file"
					accept=".jsonl,.json,.log,text/plain,application/json"
					onChange={(event) => {
						const file = event.target.files?.[0];
						// **同じファイルを選び直しても発火させる。** `<input type="file">` は
						// 値が変わらないと `change` を出さないので、行番号を見て直した
						// 同じトレースを選び直したときに**黙って何も起きない**（NFR-FAIL-001）。
						event.target.value = "";
						if (file !== undefined) props.onLoad(file);
					}}
				/>
			</label>

			{props.error === null ? null : (
				<p className="jin-trace-error" data-testid="jin-trace-error">
					{props.error}
				</p>
			)}

			{replay === null ? (
				<p className="jin-hint">
					トレースを読み込むと、発火した要素が図に重なります。
				</p>
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
						<span>
							この紋で発火したイベントだけ{" "}
							{props.selectedPointer === null ? (
								"（要素を選んでください）"
							) : (
								<code data-testid="jin-trace-selected">
									{props.selectedPointer}
								</code>
							)}
						</span>
					</label>

					<ol className="jin-trace-rows" data-testid="jin-trace-rows">
						{shown.map((event) => (
							<li key={event.line}>
								<button
									type="button"
									data-testid="jin-trace-row"
									data-seq={String(seqOf(event) ?? "")}
									data-pointer={pointerOf(event) ?? ""}
									data-fired={fired(event, replay.upto) ? "1" : "0"}
									data-selected={event.line === selectedLine ? "1" : "0"}
									onClick={() => setSelectedLine(event.line)}
								>
									<span className="jin-trace-seq">{seqOf(event) ?? "?"}</span>
									<span className="jin-trace-kind">
										{stringOf(event, "kind") ?? "?"}
									</span>
									<span className="jin-trace-agent">
										{stringOf(event, "agent") ?? ""}
									</span>
									<span className="jin-trace-name">
										{stringOf(event, "name") ?? ""}
									</span>
								</button>
							</li>
						))}
					</ol>
					{shown.length === 0 ? (
						<p className="jin-hint" data-testid="jin-trace-empty">
							該当するイベントがありません。
						</p>
					) : null}

					{detail === null ? (
						<p className="jin-hint">イベントを選ぶと入出力が出ます。</p>
					) : (
						<dl className="jin-trace-detail" data-testid="jin-trace-detail">
							<dt>kind</dt>
							<dd data-testid="jin-detail-kind">
								{stringOf(detail, "kind") ?? ""}
							</dd>
							<dt>name</dt>
							<dd data-testid="jin-detail-name">
								{stringOf(detail, "name") ?? ""}
							</dd>
							<dt>agent</dt>
							<dd data-testid="jin-detail-agent">
								{stringOf(detail, "agent") ?? ""}
							</dd>
							<dt>pointer</dt>
							<dd data-testid="jin-detail-pointer">
								{pointerOf(detail) ?? "null"}
							</dd>
							<dt>input</dt>
							{/* **そのまま**出す。要約も切り詰めもしない（モデル入出力を見るための面である）。 */}
							<dd>
								<pre data-testid="jin-detail-input">
									{render(detail.row["input"])}
								</pre>
							</dd>
							<dt>output</dt>
							<dd>
								<pre data-testid="jin-detail-output">
									{render(detail.row["output"])}
								</pre>
							</dd>
						</dl>
					)}
				</>
			)}
		</section>
	);
}

/** `seq <= upto` なら発火済み（`docs/spec/layout.md` §7.4）。`seq` が読めない行は未発火扱い。 */
function fired(event: TraceEvent, upto: number): boolean {
	const seq = seqOf(event);
	return seq !== null && seq <= upto;
}

/** 値を**そのまま** JSON にする。`undefined`（欄が無い）だけは空文字にする。 */
function render(value: unknown): string {
	if (value === undefined) return "";
	return JSON.stringify(value, null, 2) ?? "";
}
