import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DebugPanel } from "./debug/DebugPanel";
import { appendRow, appendRows, loadTrace, type Replay } from "./debug/replay";
import { PropertyPanel } from "./form/PropertyPanel";
import type { JsonSchema } from "./form/schemaForm";
import { resolveRef } from "./form/schemaForm";
import type { JinApi, RenderOptions } from "./rpc/jin";
import type {
	JinDiagnostic,
	JinGenerated,
	JinOp,
	JinRenderSvgResult,
} from "./rpc/protocol";
import { type PlayerControl, RunPanel } from "./run/RunPanel";
import { runAgent } from "./run/client";
import {
	EMPTY_HISTORY,
	type History,
	push as pushHistory,
	redo as redoStep,
	undo as undoStep,
} from "./state/history";
import {
	followRename,
	type Selection,
	resolveSelection,
	selectionFromPointer,
} from "./state/selection";
import { assertNever, hasDrawing, type ViewState } from "./state/viewState";
import { SvgCanvas } from "./svg/SvgCanvas";
import type { JinTarget } from "./svg/hitTest";
import { rowsOf, type TraceRow } from "./trace/parse";
import { DiagnosticList } from "./ui/DiagnosticList";
import { StatusBar } from "./ui/StatusBar";
import {
	addHostSigil,
	addRite,
	addState,
	addStep,
	extractSelectedStep,
	moveOps,
	removeSelected,
	toggleStateOut,
	wrapSelectedStep,
} from "./v2/actions";
import { PropertyPanelV2 } from "./v2/PropertyPanelV2";
import {
	followRenameV2,
	resolveSelectionV2,
	type SelectionV2,
	selectionFromPointerV2,
} from "./v2/selection";

/**
 * 編集モード（要件書 §7.1）。
 *
 * **ファイルが唯一の状態**である（要件書 §10 #10）。ここが持つ `ViewState` は
 * 直近のサーバ応答の写しであって、ローカルで書き換えることは一度も無い:
 * 変更はすべて `jin/applyOps` を往復し、返ってきたモデルと SVG で置き換える。
 *
 * デバッグモード（要件書 §7.2）も**同じ面**である（DP-COMMON-18: SSR 無しの単一ページ・
 * ページ内でモードを切り替える）。同じ SVG・同じ選択・同じ LSP 接続を共有し、
 * 違いは `jin/renderSvg` に `trace` と `upto` が付くことと、脇のパネルの中身だけである。
 *
 * **Jin v2（`version: 2`）も同じ面で開く**（設計書 §8・Phase 5）。版は `jin/model` の応答の
 * `version` だけで決め、v2 なら schema（`jin-v2.schema.json`）・選択（`v2/selection.ts`）・
 * オペレーション（`v2/dispatch.ts` / `v2/actions.ts`）・脇のパネル（式エディタ・実行パネル）を
 * v2 のものに切り替える。v1 の経路は 1 行も変えない。
 */
/** 面はひとつ、モードはページ内の切り替え（DP-COMMON-18・要件書 §7.1 / §7.2）。 */
export type Mode = "edit" | "debug";

/** v1 と v2 の選択を 1 つの state で持つ。v2 は `v2: true` の印で見分ける。 */
export type AnySelection = Selection | SelectionV2;

export function isV2Selection(
	selection: AnySelection,
): selection is SelectionV2 {
	return "v2" in selection && selection.v2 === true;
}

export interface AppProps {
	readonly api: JinApi;
	readonly uri: string;
	readonly schema: JsonSchema;
	/** Jin v2 の schema（`schemas/jin-v2.schema.json`）。v2 のフォーム生成にだけ使う。 */
	readonly schemaV2: JsonSchema;
	/** ホスト能力の名前空間（`schemas/abilities.json`）。道具を足すパレットにだけ使う。 */
	readonly namespaces: readonly string[];
	/**
	 * 実行エンドポイント（Issue #34）の origin。**このページを配っているのと同じところ**。
	 * 別の場所を指せるようにしない（`main.tsx` が `window.location.origin` を渡す）。
	 */
	readonly runOrigin: string;
	/** 起動トークン。`X-Jin-Token` ヘッダに載せる（body や query に置かない）。 */
	readonly token: string;
}

/** 実行パネルが走っている間、オーバーレイを描き直す間隔（ms）。 */
export const LIVE_REFRESH_MS = 1000;

/** 実行パネルから溜めるトレース行の上限。超えたら古い行を落とす（`jin/renderSvg` の送信量の上限）。 */
export const MAX_LIVE_ROWS = 4000;

export function App({
	api,
	uri,
	schema,
	schemaV2,
	namespaces,
	runOrigin,
	token,
}: AppProps): React.JSX.Element {
	const [state, setState] = useState<ViewState>({
		kind: "disconnected",
		reason: null,
	});
	const [selection, setSelection] = useState<AnySelection | null>(null);
	const [focus, setFocus] = useState<string | null>(null);
	const [history, setHistory] = useState<History>(EMPTY_HISTORY);
	// 診断は `jin/open` / `jin/applyOps` / `jin/save` の応答に載る（要件書 §5 の座標系のまま・
	// pointer 付き）。`publishDiagnostics` は LSP 座標（0 始まり・UTF-16）で来るので混ぜない。
	const [diagnostics, setDiagnostics] = useState<readonly JinDiagnostic[]>([]);
	const [notice, setNotice] = useState<string | null>(null);
	// モードはページ内の切り替え（DP-COMMON-18）。ルーティングを持たない。
	const [mode, setMode] = useState<Mode>("edit");
	// **トレースは `ViewState` の外**（`debug/replay.ts` の注記）。編集で置き換わらない。
	const [replay, setReplay] = useState<Replay | null>(null);
	const [traceError, setTraceError] = useState<string | null>(null);
	// **実行状態も `ViewState` の外**（DP-COMMON-19 の 5 状態を増やさない）。
	// トレースと同じ理由で、実行の有無は「LSP との関係」と直交する。
	const [running, setRunning] = useState(false);
	const [runError, setRunError] = useState<string | null>(null);
	const [runSummary, setRunSummary] = useState<string | null>(null);
	// サーバが最後に返したテキスト（`jin/open` / `jin/applyOps` / `jin/save`）。v2 の式エディタが
	// 補完の位置を `pointers` から換算するのに使う。**モデルの写しであって独自の状態ではない。**
	const [text, setText] = useState("");
	// v2 の JIL と manifest（`jin/model` / `jin/applyOps` の応答）。実行パネルへ渡す。
	const [generated, setGenerated] = useState<JinGenerated | null>(null);
	// v2 のパレット（ステップの種別 / 道具の名前空間）。
	const [stepKind, setStepKind] = useState("set");
	const [host, setHost] = useState(namespaces[0] ?? "");

	/**
	 * モデルと SVG を取り直して表示状態を作る。**SVG はキャッシュしない**（DP-COMMON-07）。
	 *
	 * トレースは引数で渡す（`state` に閉じ込めない）。`jin/renderSvg` が
	 * **トレース行の契約違反**（`jin_render.overlay.read_trace`）で拒んだときは、
	 * `.jin` 自体は壊れていないので**図は出したまま**トレースだけを外す。
	 * 黙って外さず、何が使えなかったのかを画面に残す（NFR-FAIL-001）。
	 */
	const refresh = useCallback(
		async (
			nextFocus: string | null,
			found: readonly JinDiagnostic[],
			current: Replay | null,
		): Promise<void> => {
			try {
				const model = await api.model(uri);
				let drawing: JinRenderSvgResult;
				try {
					drawing = await api.renderSvg(uri, renderOptions(nextFocus, current));
				} catch (error) {
					if (current === null) throw error;
					setReplay(null);
					setTraceError(`このトレースは重ねられません: ${messageOf(error)}`);
					drawing = await api.renderSvg(uri, renderOptions(nextFocus, null));
				}
				if (model.model["version"] === 2) {
					setGenerated({
						jil: model.jil ?? null,
						manifest: model.manifest ?? null,
						jilError: model.jilError ?? null,
					});
				}
				setState({
					kind: model.stale || drawing.stale ? "stale" : "ready",
					uri,
					model: model.model,
					pointers: model.pointers,
					svg: drawing.svg,
					diagnostics: found,
				});
			} catch (error) {
				setState({ kind: "unavailable", uri, message: messageOf(error) });
			}
		},
		[api, uri],
	);

	useEffect(() => {
		let cancelled = false;
		setState({ kind: "loading", uri });
		void (async () => {
			try {
				const opened = await api.open(uri);
				if (cancelled) return;
				setText(opened.text);
				setDiagnostics(opened.diagnostics);
				await refresh(null, opened.diagnostics, null);
			} catch (error) {
				if (!cancelled)
					setState({ kind: "unavailable", uri, message: messageOf(error) });
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [api, uri, refresh]);

	const model = hasDrawing(state) ? state.model : null;
	const isV2 = model !== null && model["version"] === 2;
	const selectedPointer = useMemo(
		() =>
			model === null || selection === null
				? null
				: isV2Selection(selection)
					? resolveSelectionV2(model, selection)
					: resolveSelection(model, selection),
		[model, selection],
	);
	const selectionV2 =
		selection !== null && isV2Selection(selection) ? selection : null;

	/** オペレーションを送る唯一の入口。履歴に積むかどうかだけが呼び出し側の裁量。 */
	const send = useCallback(
		async (
			ops: readonly JinOp[],
			options?: { readonly record?: boolean },
		): Promise<void> => {
			if (ops.length === 0 || model === null) return;
			setNotice(null);
			try {
				const result = await api.applyOps(uri, ops);
				if (!result.ok) {
					setNotice(`${result.error.code}: ${result.error.message}`);
					return;
				}
				if (options?.record !== false) {
					setHistory((current) =>
						pushHistory(current, { forward: ops, inverse: result.inverses }),
					);
				}
				// rename は選択中の要素の名前を変えるので、3 つ組を新名へ追随させる
				// （DP-COMMON-16 の cons が名指ししていた箇所）。
				setSelection((current) =>
					current !== null && isV2Selection(current)
						? ops.reduce(
								(acc, op) => followRenameV2(acc, op, model),
								current as SelectionV2 | null,
							)
						: ops.reduce(
								(acc, op) => followRename(acc, op, model),
								current as Selection | null,
							),
				);
				setText(result.text);
				setDiagnostics(result.diagnostics);
				if (result.warnings !== undefined && result.warnings.length > 0) {
					setNotice(
						`rename が追随できなかった式があります: ${result.warnings.join(", ")}`,
					);
				}
				// 編集してもトレースは**保持**する（読み込んだトレースはモデルから導出できない
				// UI 意図であり、`applyOps` の応答で捨てるとスクラブ位置ごと失われる）。
				// **残存**: 編集で配列が並び替わると、古いトレースの pointer が別の要素を指しうる。
				await refresh(focus, result.diagnostics, replay);
			} catch (error) {
				setNotice(messageOf(error));
			}
		},
		[api, uri, model, focus, refresh, replay],
	);

	const save = useCallback(async (): Promise<void> => {
		try {
			// `text` を渡さない = サーバが持つモデルの正準形を書く
			// （`jin fmt` の出力とバイト一致・要件書 成功条件 5）。
			const result = await api.save(uri);
			setText(result.text);
			setDiagnostics(result.diagnostics);
			setNotice(`保存しました: ${result.path}`);
		} catch (error) {
			setNotice(messageOf(error));
		}
	}, [api, uri]);

	const step = useCallback(
		async (direction: "undo" | "redo"): Promise<void> => {
			const next = direction === "undo" ? undoStep(history) : redoStep(history);
			if (next === null) return;
			setHistory(next.history);
			await send(next.ops, { record: false });
		},
		[history, send],
	);

	/** JSONL を読み込んで再生位置を最後に置く（要件書 §7.2 の 1 項目め）。 */
	const openTrace = useCallback(
		async (file: File): Promise<void> => {
			const result = await loadTrace(file);
			if (!result.ok) {
				setReplay(null);
				setTraceError(result.message);
				await refresh(focus, diagnostics, null);
				return;
			}
			setTraceError(null);
			setReplay(result.replay);
			await refresh(focus, diagnostics, result.replay);
		},
		[focus, diagnostics, refresh],
	);

	/**
	 * 実行（Issue #34・要件書 §7.2 のライブ実行）。
	 *
	 * 届いた行を 1 つずつ `Replay` に積み、そのたびに `jin/renderSvg` を呼び直す。
	 * **既知のコスト**: 往復がトレースの行数だけ起きる。`--model fake` の実行は数行〜
	 * 十数行なので実用上問題にならない。デバウンスを入れると「同じ `upto` なら同じ SVG」
	 * （machine 2）の検査と、どの行まで描いたかの見え方が変わるので、
	 * **入れるなら判断ポイントとして起票してから**にする。
	 */
	const startRun = useCallback(
		async (prompt: string, model: string | null): Promise<void> => {
			setRunning(true);
			setRunError(null);
			setRunSummary(null);
			const name = `実行: ${prompt}`;
			let live: Replay | null = null;
			try {
				for await (const event of runAgent({
					origin: runOrigin,
					token,
					prompt,
					model,
				})) {
					if (event.kind === "row") {
						live = appendRow(live, event.row, name);
						setReplay(live);
						setTraceError(null);
						await refresh(focus, diagnostics, live);
					} else if (event.kind === "done") {
						// **exit が 0 でなくても図は消さない。** `.jin` は壊れていないので、
						// 理由だけ出して、届いた分のオーバーレイはそのまま残す。
						if (event.exit === 0) setRunSummary(lastLine(event.stderr));
						else
							setRunError(
								`実行が失敗しました（exit ${String(event.exit)}）: ${lastLine(event.stderr)}`,
							);
					} else {
						setRunError(event.message);
					}
				}
			} catch (error) {
				setRunError(`実行できません: ${messageOf(error)}`);
			} finally {
				setRunning(false);
			}
		},
		[runOrigin, token, focus, diagnostics, refresh],
	);

	/**
	 * 実行パネル（v2）からのトレース。**tick ごとに配列で届く**ので `appendRows` でまとめて積み、
	 * 描き直しは `LIVE_REFRESH_MS` に 1 回に間引く（60 tick/s × 十数行を毎回 `jin/renderSvg` に
	 * 送ると ws のペイロードが万行になる）。行数は `MAX_LIVE_ROWS` で頭打ちにし、超えたら
	 * 古い行を落として理由を出す。一時停止 / 1 tick / 最初から のときは即座に描き直す。
	 */
	const liveReplay = useRef<Replay | null>(null);
	const liveTimer = useRef<number | null>(null);
	const flushLive = useCallback((): void => {
		if (liveTimer.current !== null) {
			window.clearTimeout(liveTimer.current);
			liveTimer.current = null;
		}
		void refresh(focus, diagnostics, liveReplay.current);
	}, [refresh, focus, diagnostics]);
	const onTrace = useCallback(
		(rows: readonly TraceRow[]): void => {
			const appended = appendRows(liveReplay.current, rows, "実行パネル");
			const trimmed =
				appended.events.length > MAX_LIVE_ROWS
					? {
							...appended,
							events: appended.events.slice(-MAX_LIVE_ROWS),
						}
					: appended;
			if (trimmed !== appended) {
				setTraceError(
					`トレースが ${String(MAX_LIVE_ROWS)} 行を超えたので古い行を落としています`,
				);
			}
			liveReplay.current = trimmed;
			setReplay(trimmed);
			if (liveTimer.current === null) {
				liveTimer.current = window.setTimeout(flushLive, LIVE_REFRESH_MS);
			}
		},
		[flushLive],
	);
	const onControl = useCallback(
		(action: PlayerControl): void => {
			if (action === "reboot") {
				liveReplay.current = null;
				setReplay(null);
				setTraceError(null);
			}
			if (action !== "start") flushLive();
		},
		[flushLive],
	);
	useEffect(
		() => () => {
			if (liveTimer.current !== null) window.clearTimeout(liveTimer.current);
		},
		[],
	);

	/**
	 * スクラバ。**各位置で `jin/renderSvg` を呼び直す**（要件書 §7.2）。
	 * オーバーレイをクライアントで作らないので、同じ `upto` なら同じ SVG になる。
	 */
	const scrub = useCallback(
		(upto: number): void => {
			if (replay === null || upto === replay.upto) return;
			const next: Replay = { ...replay, upto };
			liveReplay.current = next;
			setReplay(next);
			void refresh(focus, diagnostics, next);
		},
		[replay, focus, diagnostics, refresh],
	);

	const changeFocus = useCallback(
		(next: string | null): void => {
			setFocus(next);
			void refresh(next, diagnostics, replay);
		},
		[refresh, diagnostics, replay],
	);

	/** v2 の pick: `data-jin` の pointer をそのまま要素として解決する（referent 規則は使わない）。 */
	const pickV2 = useCallback(
		(target: JinTarget, current: NonNullable<typeof model>): void => {
			setSelection(selectionFromPointerV2(current, target.pointer));
		},
		[],
	);

	/**
	 * v2 のダブルクリック（`docs/spec/v2/ops.md` §5）:
	 * 手順の小陣 → `focus` を `陣名/手順名` に、記憶の四角 → `setState`（`out` の切り替え）、
	 * 陣 / 参照（`data-jin-ref`）→ その陣に focus。
	 */
	const openV2 = useCallback(
		(target: JinTarget, current: NonNullable<typeof model>): void => {
			if (target.ref !== null) {
				const referenced = selectionFromPointerV2(current, target.ref);
				if (referenced !== null && "circle" in referenced) {
					changeFocus(focus === referenced.circle ? null : referenced.circle);
				}
				return;
			}
			const picked = selectionFromPointerV2(current, target.pointer);
			if (picked === null) return;
			if (picked.kind === "rite") {
				const next = `${picked.circle}/${picked.name}`;
				changeFocus(focus === next ? picked.circle : next);
			} else if (picked.kind === "state") {
				void send(toggleStateOut(current, picked));
			} else if ("circle" in picked) {
				changeFocus(focus === picked.circle ? null : picked.circle);
			}
		},
		[changeFocus, focus, send],
	);

	const focusRite = useMemo(() => {
		if (focus === null) return null;
		const [circle, rite] = focus.split("/");
		return circle !== undefined && rite !== undefined ? { circle, rite } : null;
	}, [focus]);

	/** ステップの `do` の値（schema の判別共用体の枝から。名前を書き写さない）。 */
	const stepKinds = useMemo(() => {
		const steps = resolveRef(schemaV2, "#/$defs/Rite")?.properties?.["steps"];
		return Object.keys(steps?.items?.discriminator?.mapping ?? {});
	}, [schemaV2]);

	const body = ((): React.JSX.Element => {
		switch (state.kind) {
			case "disconnected":
			case "loading":
			case "unavailable":
				return <p className="jin-hint">{/* 状態はステータスバーが伝える */}</p>;
			case "ready":
			case "stale":
				return (
					<div className="jin-body">
						<SvgCanvas
							svg={state.svg}
							selectedPointer={selectedPointer}
							diagnostics={state.diagnostics}
							onPick={(target) => {
								if (isV2) {
									pickV2(target, state.model);
									return;
								}
								const pointer = target.ref ?? target.pointer;
								setSelection(selectionFromPointer(state.model, pointer));
							}}
							onOpen={(target) => {
								if (isV2) {
									openV2(target, state.model);
									return;
								}
								// 入れ子の小陣をダブルクリックで focus を切り替える（要件書 §7.1）。
								const pointer = target.ref ?? target.pointer;
								const picked = selectionFromPointer(state.model, pointer);
								if (picked === null) return;
								changeFocus(focus === picked.circle ? null : picked.circle);
							}}
							onMove={(from, to) => {
								if (isV2) {
									void send(moveOps(from, to));
									return;
								}
								// ドラッグで紋を環上で並べ替える → moveTool（要件書 §7.1）。
								// 落とした先の紋の添字を目的地にする。**角度はエディタが計算しない**。
								const index = Number(to.pointer.split("/").at(-1));
								if (!Number.isInteger(index)) return;
								void send([{ op: "moveTool", pointer: from.pointer, index }]);
							}}
							onDiagnostic={(diagnostic) =>
								showDiagnostic(
									diagnostic,
									setNotice,
									setSelection,
									state.model,
									isV2,
								)
							}
						/>
						<aside className="jin-side">
							{mode === "edit" ? (
								isV2 ? (
									<PropertyPanelV2
										schema={schemaV2}
										model={state.model}
										pointers={state.pointers}
										text={text}
										uri={uri}
										api={api}
										selection={selectionV2}
										onChange={(ops) => void send(ops)}
									/>
								) : (
									<PropertyPanel
										schema={schema}
										model={state.model}
										selection={
											selection !== null && !isV2Selection(selection)
												? selection
												: null
										}
										onChange={(ops) => void send(ops)}
									/>
								)
							) : isV2 ? (
								<RunPanel
									generated={generated}
									replay={replay}
									selectedPointer={selectedPointer}
									traceError={traceError}
									onTrace={onTrace}
									onControl={onControl}
									onUpto={scrub}
								/>
							) : (
								<DebugPanel
									replay={replay}
									selectedPointer={selectedPointer}
									error={traceError}
									onLoad={(file) => void openTrace(file)}
									onUpto={scrub}
									running={running}
									runError={runError}
									runSummary={runSummary}
									onRun={(prompt, model) => void startRun(prompt, model)}
								/>
							)}
							<DiagnosticList
								diagnostics={state.diagnostics}
								onPick={(diagnostic) =>
									showDiagnostic(
										diagnostic,
										setNotice,
										setSelection,
										state.model,
										isV2,
									)
								}
							/>
						</aside>
					</div>
				);
		}
		return assertNever(state);
	})();

	const circleOf =
		selection !== null && "circle" in selection ? selection.circle : null;

	return (
		<main className="jin-app" data-version={isV2 ? "2" : "1"}>
			<header className="jin-toolbar">
				<button
					type="button"
					data-testid="jin-mode-edit"
					data-active={mode === "edit" ? "1" : "0"}
					onClick={() => setMode("edit")}
				>
					編集
				</button>
				<button
					type="button"
					data-testid="jin-mode-debug"
					data-active={mode === "debug" ? "1" : "0"}
					onClick={() => setMode("debug")}
				>
					{isV2 ? "実行" : "デバッグ"}
				</button>
				<span className="jin-sep" />
				<button
					type="button"
					data-testid="jin-save"
					onClick={() => void save()}
				>
					保存
				</button>
				<button
					type="button"
					data-testid="jin-undo"
					disabled={history.undo.length === 0}
					onClick={() => void step("undo")}
				>
					元に戻す
				</button>
				<button
					type="button"
					data-testid="jin-redo"
					disabled={history.redo.length === 0}
					onClick={() => void step("redo")}
				>
					やり直す
				</button>
				<span className="jin-sep" />
				{isV2 ? (
					<>
						<button
							type="button"
							data-testid="jin-add-rite"
							disabled={model === null || circleOf === null}
							onClick={() => {
								if (model === null || circleOf === null) return;
								void send(addRite(model, circleOf));
							}}
						>
							手順を追加
						</button>
						<select
							data-testid="jin-step-kind"
							value={stepKind}
							onChange={(event) => setStepKind(event.currentTarget.value)}
						>
							{stepKinds.map((kind) => (
								<option key={kind} value={kind}>
									{kind}
								</option>
							))}
						</select>
						<button
							type="button"
							data-testid="jin-add-step"
							disabled={
								model === null ||
								(selectionV2?.kind !== "step" &&
									selectionV2?.kind !== "rite" &&
									focusRite === null)
							}
							onClick={() => {
								if (model === null) return;
								void send(addStep(model, selectionV2, focusRite, stepKind));
							}}
						>
							ステップを追加
						</button>
						<button
							type="button"
							data-testid="jin-add-state"
							disabled={model === null || circleOf === null}
							onClick={() => {
								if (model === null || circleOf === null) return;
								void send(addState(model, circleOf));
							}}
						>
							記憶を追加
						</button>
						<select
							data-testid="jin-host"
							value={host}
							onChange={(event) => setHost(event.currentTarget.value)}
						>
							{namespaces.map((name) => (
								<option key={name} value={name}>
									{name}
								</option>
							))}
						</select>
						<button
							type="button"
							data-testid="jin-add-sigil"
							disabled={model === null || circleOf === null || host === ""}
							onClick={() => {
								if (model === null || circleOf === null) return;
								void send(addHostSigil(model, circleOf, host));
							}}
						>
							道具を追加
						</button>
						<button
							type="button"
							data-testid="jin-wrap-step"
							disabled={model === null || selectionV2?.kind !== "step"}
							onClick={() => {
								if (model === null || selectionV2 === null) return;
								void send(wrapSelectedStep(model, selectionV2));
							}}
						>
							if で包む
						</button>
						<button
							type="button"
							data-testid="jin-extract-step"
							disabled={model === null || selectionV2?.kind !== "step"}
							onClick={() => {
								if (model === null || selectionV2 === null) return;
								void send(extractSelectedStep(model, selectionV2));
							}}
						>
							手順に抽出
						</button>
						<button
							type="button"
							data-testid="jin-remove"
							disabled={
								model === null ||
								selectionV2 === null ||
								removeSelected(model, selectionV2).length === 0
							}
							onClick={() => {
								if (model === null || selectionV2 === null) return;
								void send(removeSelected(model, selectionV2));
							}}
						>
							削除
						</button>
					</>
				) : (
					<>
						<button
							type="button"
							data-testid="jin-add-tool"
							disabled={model === null || circleOf === null}
							onClick={() => {
								if (model === null || circleOf === null) return;
								void send(addToList(model, circleOf, "tools"));
							}}
						>
							紋を追加
						</button>
						<button
							type="button"
							data-testid="jin-add-state"
							disabled={model === null || circleOf === null}
							onClick={() => {
								if (model === null || circleOf === null) return;
								void send(addToList(model, circleOf, "state"));
							}}
						>
							記憶を追加
						</button>
						<button
							type="button"
							data-testid="jin-add-delegate"
							disabled={model === null || circleOf === null}
							onClick={() => {
								if (model === null || circleOf === null) return;
								void send(addToList(model, circleOf, "delegate"));
							}}
						>
							委譲を追加
						</button>
					</>
				)}
				{focus === null ? null : (
					<button
						type="button"
						data-testid="jin-focus-clear"
						onClick={() => changeFocus(null)}
					>
						focus を外す（{focus}）
					</button>
				)}
			</header>
			<StatusBar state={state} />
			{notice === null ? null : (
				<p className="jin-notice" data-testid="jin-notice">
					{notice}
				</p>
			)}
			{body}
		</main>
	);
}

/**
 * `jin/renderSvg` の引数。**`upto` は `trace` と一緒でなければ渡さない**
 * （`docs/spec/layout.md` §7.4「`trace` 無しで `upto` だけを渡したら拒む」）。
 */
function renderOptions(
	focus: string | null,
	replay: Replay | null,
): RenderOptions {
	if (replay === null) return { focus: focus ?? undefined };
	return {
		focus: focus ?? undefined,
		trace: rowsOf(replay.events),
		upto: replay.upto,
	};
}

function showDiagnostic(
	diagnostic: JinDiagnostic,
	setNotice: (value: string) => void,
	setSelection: (value: AnySelection | null) => void,
	model: Parameters<typeof selectionFromPointer>[0],
	isV2: boolean,
): void {
	setNotice(
		diagnostic.hint === undefined
			? `${diagnostic.code}: ${diagnostic.message}`
			: `${diagnostic.code}: ${diagnostic.message} — ${diagnostic.hint}`,
	);
	setSelection(
		isV2
			? selectionFromPointerV2(model, diagnostic.pointer)
			: selectionFromPointer(model, diagnostic.pointer),
	);
}

/**
 * 環の空き位置への追加（要件書 §7.1「環の空き位置をクリック → addTool / addState」）。
 *
 * 新しい要素は**スキーマ上必須の欄だけ**を埋め、値は空にする。ここで
 * `ref` に架空のモジュール名を入れると、ユーザーが書いていない参照を捏造することになる。
 * 空のまま作れば `jin check` が未解決参照として診断を出し、次に何をすべきかが図に出る。
 */
function addToList(
	model: Parameters<typeof resolveSelection>[0],
	circleName: string,
	field: "tools" | "state" | "delegate",
): readonly JinOp[] {
	const pointer = resolveSelection(model, {
		circle: circleName,
		kind: "circle",
	});
	if (pointer === null) return [];
	const circle = (model["circles"] as Record<string, unknown>[] | undefined)?.[
		Number(pointer.split("/").at(-1))
	];
	const list = circle?.[field];
	const index = Array.isArray(list) ? list.length : 0;
	const used = new Set(
		Array.isArray(list)
			? list.map((item) =>
					typeof item === "string"
						? item
						: String((item as { name?: unknown }).name ?? ""),
				)
			: [],
	);
	// **参照先を捏造しない**（DP-IMPL-JIN-P5-ADD-DEFAULTS-01）。tool の `ref` と同じく
	// delegate も空で作り、プロパティパネルで書いてもらう。`jin check` が未解決参照として
	// 診断を出すので、次に何をすべきかが図の上に出る。
	const name = freshName(field === "state" ? "state" : "tool", used);
	const value =
		field === "delegate"
			? ""
			: field === "state"
				? { name, type: "" }
				: { name, kind: "tool", ref: "" };
	return [
		{
			op:
				field === "state"
					? "addState"
					: field === "tools"
						? "addTool"
						: "addDelegate",
			pointer: `${pointer}/${field}`,
			index,
			value,
		},
	];
}

function freshName(base: string, used: ReadonlySet<string>): string {
	for (let i = 1; ; i += 1) {
		const candidate = `${base}${i}`;
		if (!used.has(candidate)) return candidate;
	}
}

/**
 * stderr の**最後の中身のある行**。`jin run` は最後に「N イベント（session: …）」を出す。
 * 失敗したときは理由の行がそこに来る。
 */
function lastLine(text: string): string {
	const lines = text.split("\n").filter((line) => line.trim() !== "");
	return lines.length === 0 ? "" : (lines[lines.length - 1] ?? "");
}

function messageOf(error: unknown): string {
	if (error instanceof Error) return error.message;
	if (error !== null && typeof error === "object" && "message" in error) {
		return String((error as { message: unknown }).message);
	}
	return String(error);
}
