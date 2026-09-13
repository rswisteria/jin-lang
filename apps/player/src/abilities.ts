/**
 * `schemas/abilities.json` から引くキー名と op 名（abilities.md §3 / §7）。
 *
 * プレイヤーが読む生成物は **これ 1 つだけ**（runtime.md §10）。キー名や op 名の
 * リテラルをソースに書かず、ここから引く（カタログが増えたときにプレイヤーだけが
 * 古いままにならないため。`tests/contract/test_player_contract.py` が走査する）。
 */
import abilities from "../../../schemas/abilities.json";

interface Member {
	readonly name: string;
}
interface Namespace {
	readonly name: string;
	readonly members: readonly Member[];
}
interface Catalog {
	readonly namespaces: readonly Namespace[];
	readonly keys: readonly string[];
}

const catalog: Catalog = abilities;

function members(namespace: string): readonly string[] {
	const found = catalog.namespaces.find((n) => n.name === namespace);
	if (found === undefined) {
		throw new Error(`abilities.json に名前空間 ${namespace} がありません`);
	}
	return found.members.map((m) => m.name);
}

/** プレイヤーが集めるキー（`KeyboardEvent.code` と同じ綴り）。それ以外のキーは無視する。 */
export const KEY_NAMES: ReadonlySet<string> = new Set(catalog.keys);

/** 表示リストに現れる op（`canvas` の effect と `ui` の 2 つ）。 */
export const CANVAS_OPS: readonly string[] = members("canvas");
export const UI_OPS: readonly string[] = members("ui");
/** 音リストに現れる op。 */
export const AUDIO_OPS: readonly string[] = members("audio");

/** `canvas` / `ui` の op 名を名前で引く（`op("rect")` のように使い、リテラルの綴りを分散させない）。 */
export function op(name: string): string {
	if (
		!CANVAS_OPS.includes(name) &&
		!UI_OPS.includes(name) &&
		!AUDIO_OPS.includes(name)
	) {
		throw new Error(`abilities.json に op ${name} がありません`);
	}
	return name;
}

/** 入力を購読するか（runtime.md §9: `namespaces` に無い入力は集めない）。 */
export function subscriptions(namespaces: readonly string[]): {
	keys: boolean;
	pointer: boolean;
} {
	const input = namespaces.includes("input");
	// `ui.button` はポインタの離しを見る（abilities.md §4）ので `ui` だけでもポインタは集める。
	const ui = namespaces.includes("ui");
	return { keys: input, pointer: input || ui };
}
