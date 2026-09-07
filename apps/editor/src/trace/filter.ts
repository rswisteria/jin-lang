/**
 * 「この紋で発火したイベントだけ」の絞り込み（要件書 §7.2 の 3 項目め）。
 *
 * **overlay の強調規則と同じ判定を使う**（`docs/spec/layout.md` §7.1 の規則 1 /
 * `jin_render.overlay.is_ancestor_or_same`）。図で光る要素と一覧に残る行が
 * 食い違うと、フィルタが「別の意味の一致」を持つことになる。
 *
 * 選んだ要素の pointer が、行の pointer と**同じかその祖先**なら残す。
 * `/circles/1` を選んだら `/circles/1/core` の行は残り、
 * **`/circles/10/core` の行は残らない**（`/` 区切りの段一致であって前方一致ではない）。
 */

import { pointerOf, type TraceEvent } from "./parse";

/**
 * `candidate` が `pointer` と同じか、その**祖先**か。
 *
 * `jin_render.overlay.is_ancestor_or_same` の写しである。
 * ルート `""`（= 文書全体）は祖先に数えない（強調は描いた要素にだけ付く）。
 */
export function isAncestorOrSame(candidate: string, pointer: string): boolean {
  if (candidate === pointer) return true;
  if (candidate === "") return false;
  return (
    candidate.length < pointer.length &&
    pointer.startsWith(candidate) &&
    pointer[candidate.length] === "/"
  );
}

/**
 * 選んだ pointer で発火した行だけ。
 *
 * `pointer: null` の行は落ちる（どの要素も強調しない行なので「この紋で発火した」に入らない）。
 * `selected` が `null` のときは**絞り込まない**（フィルタが掛かっていない状態）。
 *
 * **referent 規則（`docs/spec/layout.md` §7.1 の規則 2）はここでは使わない。**
 * `summon` の紋を選ぶと、その `data-jin` は参照**側**の pointer なので、
 * 参照先 circle の行（`/circles/4/core` など）は残らない。図の上ではその紋が
 * `data-jin-ref` で強調されるのに一覧には出ない、というずれが残る。
 * `data-jin-ref` を見て参照先の配下も残すと「一致」が 2 種類になり、
 * フィルタの意味が「pointer 一致」（要件書 §7.2）でなくなるので採らない。
 */
export function eventsFiredAt(
  events: readonly TraceEvent[],
  selected: string | null,
): readonly TraceEvent[] {
  if (selected === null) return events;
  return events.filter((event) => {
    const pointer = pointerOf(event);
    return pointer !== null && isAncestorOrSame(selected, pointer);
  });
}
