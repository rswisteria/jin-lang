import type { JsonSchema } from "../form/schemaForm";
import { branchFor, fieldsOf, resolveRef, unwrap } from "../form/schemaForm";
import type { JinModel, JinOp } from "../rpc/protocol";
import { resolveSelectionV2, type SelectionV2, valueAt } from "./selection";

/**
 * Jin v2 の「どの欄をどのオペレーションで書くか」の対応表（`docs/spec/v2/ops.md` §2 の 32 件）。
 *
 * v1 の `form/dispatch.ts` と同じ規律で、**これはフォーム定義ではない**（欄の一覧は
 * `schemaForm.ts` が `schemas/jin-v2.schema.json` から作る）。ここにあるのは書き込み経路だけである。
 * オペレーションで直接届かない欄は既存オペレーションの合成で書く（sigil の `host` / `circle` /
 * `rite` は `removeSigil` + `addSigil`、陣の `description` は `removeCircle` + `addCircle`、
 * `on` の `event` は `removeOn` + `setOn`、ステップの `do` は `removeStep` + `addStep`）。
 * `apply_ops` は「1 つでも失敗したら何も適用しない」ので、2 件を 1 回で送れば原子性が保たれる。
 *
 * **v1 の 19 件とは別集合**である。`tests/contract/test_editor_contract.py` は v1 のファイル
 * （`form/dispatch.ts` / `App.tsx`）が v1 の 19 件だけを、このディレクトリが v2 の 32 件だけを
 * 使うことをそれぞれ固定する。
 */

type Rec = Readonly<Record<string, unknown>>;

function isRecord(value: unknown): value is Rec {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** 選択の種類 → schema 上の定義（フォームを作る足場）。 */
export function schemaForV2(
	root: JsonSchema,
	selection: SelectionV2,
	value: unknown,
): JsonSchema | null {
	const circle = resolveRef(root, "#/$defs/Circle");
	if (circle === null) return null;
	switch (selection.kind) {
		case "stage":
			return resolveRef(root, "#/$defs/Stage");
		case "form":
			return resolveRef(root, "#/$defs/Form");
		case "circle": {
			// 陣のスカラ欄に、流れ（`flow`）を持つ陣なら Flow のスカラ欄（`kind` / `exit`）を並べる。
			// 配列とオブジェクトは `fieldsOf` が落とすので、名前を選んで書き写す必要は無い。
			const flow = resolveRef(root, "#/$defs/Flow");
			const hasFlow = isRecord(value) && isRecord(value["flow"]);
			return hasFlow && flow !== null
				? {
						type: "object",
						properties: { ...circle.properties, ...flow.properties },
						required: [],
					}
				: circle;
		}
		case "core": {
			const core = circle.properties?.["core"];
			return core === undefined
				? null
				: { type: "object", properties: { core }, required: [] };
		}
		case "state":
			return resolveRef(root, "#/$defs/State");
		case "sigil": {
			const sigils = circle.properties?.["sigils"];
			return sigils === undefined ? null : branchFor(root, sigils, value);
		}
		case "rite":
			return resolveRef(root, "#/$defs/Rite");
		case "on":
			return resolveRef(root, "#/$defs/OnHandler");
		case "guard":
			return resolveRef(root, "#/$defs/Guard");
		case "delegate": {
			const items = circle.properties?.["delegate"]?.items;
			return items === undefined
				? null
				: { type: "object", properties: { delegate: items }, required: [] };
		}
		case "flow-edge": {
			const items = resolveRef(root, "#/$defs/Flow")?.properties?.["steps"]
				?.items;
			return items === undefined
				? null
				: { type: "object", properties: { steps: items }, required: [] };
		}
		case "step": {
			// 範囲選択（count > 1）にはフォームを出さない（どの 1 つの欄を書くかが決まらない）。
			if ((selection.count ?? 1) > 1) return null;
			const steps = resolveRef(root, "#/$defs/Rite")?.properties?.["steps"];
			return steps === undefined ? null : branchFor(root, steps, value);
		}
	}
}

export interface FieldChangeV2 {
	readonly key: string;
	/** 空欄は `null`。式の列は文字列の配列。 */
	readonly value: string | boolean | number | null | readonly string[];
}

/** ステップの `do` を変えるときの最小の中身。**参照先を捏造しない**（陣名は自陣）。 */
export function defaultStep(kind: string, circleName: string): Rec {
	switch (kind) {
		case "set":
			return { do: "set", target: "", expr: "" };
		case "let":
			return { do: "let", name: "value", expr: "" };
		case "cast":
			return { do: "cast", target: "", args: [] };
		case "if":
			return { do: "if", cond: "", then: [] };
		case "loop":
			return { do: "loop", kind: "count", times: "1", steps: [] };
		case "wait":
			return { do: "wait", ticks: "1" };
		case "emit":
			return { do: "emit", circle: circleName, message: "message", args: [] };
		case "transfer":
			return { do: "transfer", circle: circleName };
		default:
			// break / return / finish は引数を持たない。未知の do はそのまま送り、サーバの検査に任せる。
			return { do: kind };
	}
}

/**
 * 欄の変更 → オペレーション列。書けない欄には**空配列**を返す（黙って握り潰さない）。
 * 引数のキーは `jin_core.v2.ops` の実装に合わせて **`value`（と `index` / `to`）**である。
 */
export function opsForChangeV2(
	model: JinModel,
	selection: SelectionV2,
	change: FieldChangeV2,
): readonly JinOp[] {
	const pointer = resolveSelectionV2(model, selection);
	if (pointer === null) return [];
	const value = change.value === "" ? null : change.value;
	const rename = (): readonly JinOp[] =>
		typeof change.value === "string" && change.value !== ""
			? [{ op: "rename", pointer, value: change.value }]
			: [];
	const parent = pointer.split("/").slice(0, -1).join("/");
	const index = Number(pointer.split("/").at(-1));
	const current = valueAt(model, pointer);

	switch (selection.kind) {
		case "stage":
			return [{ op: "setStage", pointer, value: { [change.key]: value } }];
		case "form":
			return change.key === "name" ? rename() : [];
		case "circle": {
			if (change.key === "name") return rename();
			if (change.key === "core") return [{ op: "setCore", pointer, value }];
			if (change.key === "kind" || change.key === "exit") {
				return [{ op: "setFlow", pointer, value: { [change.key]: value } }];
			}
			if (change.key === "description") {
				// `setDescription` は v2 に無い。**33 個目を作らず**、削除と再追加の合成で書く。
				if (!isRecord(current)) return [];
				return [
					{ op: "removeCircle", pointer },
					{
						op: "addCircle",
						pointer: parent,
						index,
						value: { ...current, description: value },
					},
				];
			}
			return [];
		}
		case "core":
			return [{ op: "setCore", pointer: parent, value }];
		case "state":
			if (change.key === "name") return rename();
			return [
				{ op: "setState", pointer, value: { [change.key]: change.value } },
			];
		case "sigil": {
			if (change.key === "name") return rename();
			// `host` / `circle` / `rite` / `kind` を書き換えるオペレーションは無い。削除と再追加の合成。
			if (!isRecord(current)) return [];
			return [
				{ op: "removeSigil", pointer },
				{
					op: "addSigil",
					pointer: parent,
					index,
					value: { ...current, [change.key]: change.value },
				},
			];
		}
		case "rite":
			if (change.key === "name") return rename();
			return [
				{ op: "setRiteSignature", pointer, value: { [change.key]: value } },
			];
		case "on": {
			if (!isRecord(current)) return [];
			const next = { ...current, [change.key]: change.value };
			if (change.key === "rite")
				return [{ op: "setOn", pointer: parent, value: next }];
			// event を変えると別の枠になる（`setOn` は同じ event を置換する）。古い枠を消してから置く。
			return [
				{ op: "removeOn", pointer },
				{ op: "setOn", pointer: parent, index, value: next },
			];
		}
		case "guard":
			if (!isRecord(current)) return [];
			return [
				{ op: "setGuard", pointer, value: { ...current, [change.key]: value } },
			];
		case "delegate":
			if (typeof change.value !== "string" || change.value === "") return [];
			return [
				{ op: "removeDelegate", pointer },
				{ op: "addDelegate", pointer: parent, index, value: change.value },
			];
		case "flow-edge": {
			if (typeof change.value !== "string" || change.value === "") return [];
			const circlePointer = pointer.split("/").slice(0, 3).join("/");
			const flow = valueAt(model, `${circlePointer}/flow`);
			const steps =
				isRecord(flow) && Array.isArray(flow["steps"])
					? [...flow["steps"]]
					: [];
			steps[index] = change.value;
			return [{ op: "setFlow", pointer: circlePointer, value: { steps } }];
		}
		case "step": {
			if (change.key === "do") {
				if (typeof change.value !== "string") return [];
				return [
					{ op: "removeStep", pointer },
					{
						op: "addStep",
						pointer: parent,
						index,
						value: defaultStep(change.value, selection.circle),
					},
				];
			}
			if (change.key === "name") return rename();
			return [{ op: "setStep", pointer, value: { [change.key]: value } }];
		}
	}
}

/** 選択に対応するフォームの欄。schema が引けなければ空。 */
export function fieldsForSelectionV2(
	root: JsonSchema,
	selection: SelectionV2,
	value: unknown,
): ReturnType<typeof fieldsOf> {
	const schema = schemaForV2(root, selection, value);
	if (schema === null) return [];
	return fieldsOf(root, unwrap(root, schema).schema);
}
