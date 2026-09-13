import { useEffect, useRef, useState } from "react";

import type { LspCompletionItem } from "../rpc/protocol";

/**
 * 式エディタ（設計書 §8「式の欄だけ式エディタ（1 行 + 補完）」）。
 *
 * **式を構文解析しない・型を決めない**（`jin_core.v2.expr` を再実装しない）。ここでするのは
 * (1) 1 行の入力、(2) LSP の `textDocument/completion` が返した候補を**カーソル直前のトークン**で
 * 絞って出す、(3) 選んだ候補でトークンを置き換える、(4) 離れたときに値を確定する、の 4 つだけ。
 * 候補は `名前空間.メンバ` のような点付きのラベルを含む（`jin_lsp.features.v2` の注記）ので、
 * トークンにも `.` を含める（`input.` と打てば `input.key` … だけが残る）。
 */
export interface ExprEditorProps {
	readonly id: string;
	readonly value: string;
	readonly disabled?: boolean;
	/** 候補を取る。位置が引けない欄（まだ文書に無い行）では `null`。 */
	readonly complete: (() => Promise<readonly LspCompletionItem[]>) | null;
	readonly onCommit: (value: string) => void;
	readonly testId?: string;
}

/** カーソル直前のトークン（識別子と `.`）。 */
export function tokenBefore(text: string, caret: number): string {
	const match = /[A-Za-z_][A-Za-z0-9_.]*$/.exec(text.slice(0, caret));
	return match === null ? "" : match[0];
}

/** 候補の絞り込み。**前方一致**（サーバは全候補を返し、絞るのはクライアント）。 */
export function filterCandidates(
	items: readonly LspCompletionItem[],
	token: string,
	limit = 12,
): readonly LspCompletionItem[] {
	if (token === "") return [];
	return items
		.filter((item) => item.label.startsWith(token) && item.label !== token)
		.slice(0, limit);
}

/** トークンをラベルで置き換えた新しいテキストと、置き換え後のカーソル位置。 */
export function applyCandidate(
	text: string,
	caret: number,
	token: string,
	label: string,
): { readonly text: string; readonly caret: number } {
	const start = caret - token.length;
	return {
		text: text.slice(0, start) + label + text.slice(caret),
		caret: start + label.length,
	};
}

export function ExprEditor(props: ExprEditorProps): React.JSX.Element {
	const [draft, setDraft] = useState(props.value);
	const [candidates, setCandidates] = useState<readonly LspCompletionItem[]>(
		[],
	);
	const [shown, setShown] = useState<readonly LspCompletionItem[]>([]);
	const [active, setActive] = useState(0);
	const input = useRef<HTMLInputElement>(null);
	const fetched = useRef(false);
	// 確定した打ちかけ。確定後にまだ打ち直していない間だけ非 null。
	const committed = useRef<string | null>(null);

	// undo / redo や別の欄の確定でサーバの値が変わったら draft を差し替える。
	// 入力中（フォーカスあり）は打ちかけの式を守る（確定は blur / Enter で行う）。
	// ただし **Enter で確定した直後**はフォーカスが残ったままサーバが正準形（`a+1` → `a + 1`・
	// expr.md §8）を返してくるので、打ち直していなければ差し替える。差し替えないと欄は `a+1` の
	// まま見え、blur でもう一度同じ式を確定してしまう（同値の `jin/applyOps` が undo に積まれる）。
	useEffect(() => {
		if (
			document.activeElement !== input.current ||
			committed.current !== null
		) {
			setDraft(props.value);
		}
		committed.current = null;
	}, [props.value]);

	const refresh = (
		text: string,
		caret: number,
		pool: readonly LspCompletionItem[],
	): void => {
		setShown(filterCandidates(pool, tokenBefore(text, caret)));
		setActive(0);
	};

	const load = async (): Promise<void> => {
		if (fetched.current || props.complete === null) return;
		fetched.current = true;
		try {
			const items = await props.complete();
			setCandidates(items);
		} catch {
			// 候補が取れなくても入力は続けられる（補完は補助であって前提ではない）。
			setCandidates([]);
		}
	};

	const accept = (item: LspCompletionItem): void => {
		const node = input.current;
		const caret = node?.selectionStart ?? draft.length;
		const next = applyCandidate(
			draft,
			caret,
			tokenBefore(draft, caret),
			item.label,
		);
		setDraft(next.text);
		setShown([]);
		requestAnimationFrame(() => {
			node?.setSelectionRange(next.caret, next.caret);
			node?.focus();
		});
	};

	const commit = (): void => {
		setShown([]);
		if (draft !== props.value) {
			committed.current = draft;
			props.onCommit(draft);
		}
	};

	return (
		<div className="jin-expr">
			<input
				ref={input}
				id={props.id}
				type="text"
				className="jin-expr-input"
				data-testid={props.testId ?? "jin-expr-input"}
				value={draft}
				disabled={props.disabled ?? false}
				autoComplete="off"
				spellCheck={false}
				onFocus={() => void load()}
				onChange={(event) => {
					const text = event.currentTarget.value;
					committed.current = null;
					setDraft(text);
					refresh(
						text,
						event.currentTarget.selectionStart ?? text.length,
						candidates,
					);
				}}
				onKeyDown={(event) => {
					if (shown.length === 0) {
						if (event.key === "Enter") {
							event.preventDefault();
							commit();
						}
						return;
					}
					if (event.key === "ArrowDown") {
						event.preventDefault();
						setActive((current) => (current + 1) % shown.length);
					} else if (event.key === "ArrowUp") {
						event.preventDefault();
						setActive((current) => (current - 1 + shown.length) % shown.length);
					} else if (event.key === "Enter" || event.key === "Tab") {
						const item = shown[active];
						if (item !== undefined) {
							event.preventDefault();
							accept(item);
						}
					} else if (event.key === "Escape") {
						setShown([]);
					}
				}}
				onBlur={commit}
			/>
			{shown.length === 0 ? null : (
				<ul
					className="jin-expr-candidates"
					data-testid="jin-expr-candidates"
					role="listbox"
				>
					{shown.map((item, index) => (
						<li
							key={item.label}
							role="option"
							aria-selected={index === active}
							data-testid="jin-expr-candidate"
							data-active={index === active ? "1" : "0"}
							// `mousedown` で入力の blur（= 確定）を止めてから選ぶ。
							onMouseDown={(event) => {
								event.preventDefault();
								accept(item);
							}}
						>
							<span className="jin-expr-label">{item.label}</span>
							{item.detail === undefined ? null : (
								<span className="jin-expr-detail">{item.detail}</span>
							)}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

/** 式の列（`cast.args` / `emit.args`）。行ごとに式エディタ + 追加 / 削除。 */
export interface ExprListEditorProps {
	readonly id: string;
	readonly values: readonly string[];
	readonly completeAt: (
		index: number,
	) => (() => Promise<readonly LspCompletionItem[]>) | null;
	readonly onCommit: (values: readonly string[]) => void;
}

export function ExprListEditor(props: ExprListEditorProps): React.JSX.Element {
	return (
		<div className="jin-expr-list" data-testid="jin-expr-list">
			{props.values.map((value, index) => (
				<div className="jin-expr-row" key={`${index}:${value}`}>
					<ExprEditor
						id={`${props.id}-${index}`}
						value={value}
						complete={props.completeAt(index)}
						testId="jin-expr-item"
						onCommit={(next) => {
							const values = [...props.values];
							values[index] = next;
							props.onCommit(values);
						}}
					/>
					<button
						type="button"
						data-testid="jin-expr-remove"
						aria-label="この引数を消す"
						onClick={() =>
							props.onCommit(props.values.filter((_, i) => i !== index))
						}
					>
						−
					</button>
				</div>
			))}
			<button
				type="button"
				data-testid="jin-expr-add"
				onClick={() => props.onCommit([...props.values, ""])}
			>
				引数を足す
			</button>
		</div>
	);
}
