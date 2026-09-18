import type { FormField, JsonSchema } from "../form/schemaForm";
import type { JinApi } from "../rpc/jin";
import type {
	JinModel,
	JinOp,
	JinPointerRow,
	LspCompletionItem,
} from "../rpc/protocol";
import {
	defaultRowV2,
	type FieldChangeV2,
	fieldsForSelectionV2,
	opsForChangeV2,
} from "./dispatch";
import { ExprEditor, ExprListEditor } from "./ExprEditor";
import { lspPositionOf } from "./position";
import {
	resolveSelectionV2,
	type SelectionV2,
	stepCount,
	valueAt,
} from "./selection";

/**
 * Jin v2 のプロパティパネル（設計書 §8）。
 *
 * **欄は `schemas/jin-v2.schema.json` から生成する**（v1 と同じ）。このファイルに欄の名前は無い。
 * 式の欄（schema の `x-jin-expr`）だけを式エディタにし、候補は LSP の completion をそのまま使う。
 * 補完の位置は `jin/model` の `pointers` と現在のテキストから換算する（`position.ts`）。
 */
export interface PropertyPanelV2Props {
	readonly schema: JsonSchema;
	readonly model: JinModel;
	readonly pointers: readonly JinPointerRow[];
	/** サーバが最後に返したテキスト（`jin/open` / `jin/applyOps` / `jin/save`）。位置換算に使う。 */
	readonly text: string;
	readonly uri: string;
	readonly api: Pick<JinApi, "complete">;
	readonly selection: SelectionV2 | null;
	readonly onChange: (ops: readonly JinOp[]) => void;
}

export function PropertyPanelV2(
	props: PropertyPanelV2Props,
): React.JSX.Element {
	const { schema, model, selection } = props;
	if (selection === null) {
		return (
			<p className="jin-hint">図の要素をクリックすると、ここに欄が出ます。</p>
		);
	}
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) {
		return (
			<p className="jin-hint">
				選択していた要素が見つかりません（削除されたか、名前が変わりました）。
			</p>
		);
	}
	const count = stepCount(selection);
	if (count > 1) {
		// 範囲選択（Shift クリック・v2.1）にはフォームを出さない。範囲に当たる操作だけを案内する。
		return (
			<div className="jin-form" data-testid="jin-form">
				<p className="jin-pointer" data-testid="jin-pointer">
					{pointer}
				</p>
				<p className="jin-hint" data-testid="jin-range">
					{count} ステップを選んでいます。「if
					で包む」「手順に抽出」「削除」が範囲全体に当たります。
				</p>
			</div>
		);
	}
	const value = valueAt(model, pointer);
	const fields = fieldsForSelectionV2(schema, selection, value);
	if (fields.length === 0) {
		return (
			<p className="jin-hint">
				この要素に編集できる欄はありません（配列は図の操作で編集します）。
			</p>
		);
	}
	const only = fields.length === 1 ? fields[0]?.key : undefined;
	const record: Record<string, unknown> =
		value !== null && typeof value === "object" && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: only === undefined
				? {}
				: { [only]: value };

	const completer = (
		fieldPointer: string,
	): (() => Promise<readonly LspCompletionItem[]>) | null => {
		const position = lspPositionOf(props.pointers, props.text, fieldPointer);
		return position === null
			? null
			: () => props.api.complete(props.uri, position);
	};

	return (
		<form
			className="jin-form"
			data-testid="jin-form"
			onSubmit={(event) => event.preventDefault()}
		>
			<p className="jin-pointer" data-testid="jin-pointer">
				{pointer}
			</p>
			{fields.map((field) => {
				const id = `jin-field-${field.key}`;
				const current = record[field.key];
				const emit = (next: FieldChangeV2["value"]): void => {
					props.onChange(
						opsForChangeV2(model, selection, { key: field.key, value: next }),
					);
				};
				// 選択がオブジェクトを指すなら欄の pointer は `<選択>/<キー>`。`core` / `delegate` のように
				// スカラを指す pointer（`record` は合成した 1 欄の器）では選択の pointer そのもの。
				// 欄が 1 つしか無いオブジェクト（`finish` / `break` …）も前者に入る。
				const fieldPointer =
					value !== null && typeof value === "object" && !Array.isArray(value)
						? `${pointer}/${field.key}`
						: pointer;
				return (
					<div className="jin-field" key={`${pointer}:${field.key}`}>
						<label htmlFor={id}>{field.label}</label>
						{field.type === "rowList" && field.columns !== null ? (
							<RowListEditor
								id={id}
								columns={field.columns}
								rows={
									Array.isArray(current)
										? current.filter(
												(row): row is Record<string, unknown> =>
													row !== null &&
													typeof row === "object" &&
													!Array.isArray(row),
											)
										: []
								}
								onCommit={(rows) => emit(rows)}
								onAdd={(rows) =>
									emit([...rows, defaultRowV2(selection, field.key, rows)])
								}
							/>
						) : field.type === "exprList" ? (
							<ExprListEditor
								id={id}
								values={
									Array.isArray(current)
										? current.map((item) => String(item))
										: []
								}
								completeAt={(index) => completer(`${fieldPointer}/${index}`)}
								onCommit={(values) => emit(values)}
							/>
						) : field.expr ? (
							<ExprEditor
								id={id}
								value={
									current === null || current === undefined
										? ""
										: String(current)
								}
								disabled={field.readOnly}
								complete={completer(fieldPointer)}
								onCommit={(next) => emit(next)}
							/>
						) : field.type === "boolean" ? (
							<input
								id={id}
								type="checkbox"
								checked={current === true}
								disabled={field.readOnly}
								onChange={(event) => emit(event.currentTarget.checked)}
							/>
						) : field.type === "enum" && field.options !== null ? (
							<select
								id={id}
								defaultValue={typeof current === "string" ? current : ""}
								disabled={field.readOnly}
								onChange={(event) => emit(event.currentTarget.value)}
							>
								{field.options.map((option) => (
									<option key={option} value={option}>
										{option}
									</option>
								))}
							</select>
						) : (
							<input
								id={id}
								type={field.type === "number" ? "number" : "text"}
								defaultValue={
									current === null || current === undefined
										? ""
										: String(current)
								}
								readOnly={field.readOnly}
								{...(field.maxLength === null
									? {}
									: { maxLength: field.maxLength })}
								onBlur={(event) => {
									const raw = event.currentTarget.value;
									if (field.type !== "number") {
										if (raw !== String(current ?? "")) emit(raw);
										return;
									}
									// 数値の欄（stage の width など）は数として送る（文字列だと schema 違反になる）。
									if (raw === "") emit(null);
									else if (Number(raw) !== current) emit(Number(raw));
								}}
							/>
						)}
						{field.description === null ? null : (
							<span className="jin-desc">{field.description}</span>
						)}
					</div>
				);
			})}
		</form>
	);
}

interface RowListEditorProps {
	readonly id: string;
	readonly columns: readonly FormField[];
	readonly rows: readonly Record<string, unknown>[];
	readonly onCommit: (rows: readonly Record<string, unknown>[]) => void;
	readonly onAdd: (rows: readonly Record<string, unknown>[]) => void;
}

/**
 * 行の表（`rowList`・v2.1）。**列は schema から**（`FormField.columns`）で、この関数に欄の名前は無い。
 * 行を足す / 消す / 列を書き換えるたびに行の配列ごと `onCommit` へ渡し、オペレーションへの
 * 換算（`rename` か `setRiteSignature` か）は `dispatch.ts` が行う。
 */
function RowListEditor(props: RowListEditorProps): React.JSX.Element {
	const replace = (index: number, key: string, value: unknown): void => {
		const rows = props.rows.map((row, i) =>
			i === index ? { ...row, [key]: value } : row,
		);
		props.onCommit(rows);
	};
	return (
		<div className="jin-row-list" data-testid="jin-row-list">
			{props.rows.map((row, index) => (
				<div
					className="jin-row"
					data-testid="jin-row"
					key={`${String(index)}:${String(row["name"] ?? "")}`}
				>
					{props.columns.map((column) => {
						const cellId = `${props.id}-${String(index)}-${column.key}`;
						const cell = row[column.key];
						const text = cell === null || cell === undefined ? "" : String(cell);
						return column.type === "enum" && column.options !== null ? (
							<select
								id={cellId}
								key={column.key}
								aria-label={column.label}
								defaultValue={text}
								onChange={(event) =>
									replace(index, column.key, event.currentTarget.value)
								}
							>
								{column.options.map((option) => (
									<option key={option} value={option}>
										{option}
									</option>
								))}
							</select>
						) : column.type === "boolean" ? (
							<input
								id={cellId}
								key={column.key}
								type="checkbox"
								aria-label={column.label}
								checked={cell === true}
								onChange={(event) =>
									replace(index, column.key, event.currentTarget.checked)
								}
							/>
						) : (
							<input
								id={cellId}
								key={column.key}
								type={column.type === "number" ? "number" : "text"}
								aria-label={column.label}
								placeholder={column.label}
								defaultValue={text}
								onBlur={(event) => {
									const raw = event.currentTarget.value;
									if (raw === text) return;
									replace(
										index,
										column.key,
										column.type === "number" ? Number(raw) : raw,
									);
								}}
							/>
						);
					})}
					<button
						type="button"
						data-testid="jin-row-remove"
						aria-label="この行を消す"
						onClick={() =>
							props.onCommit(props.rows.filter((_, i) => i !== index))
						}
					>
						−
					</button>
				</div>
			))}
			<button
				type="button"
				data-testid="jin-row-add"
				onClick={() => props.onAdd(props.rows)}
			>
				行を足す
			</button>
		</div>
	);
}
