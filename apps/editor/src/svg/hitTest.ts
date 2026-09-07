/**
 * `data-jin` によるヒットテスト（要件書 §7.1 / `docs/spec/layout.md` §3）。
 *
 * **エディタはレイアウトを知らない。** 座標も半径も角度も持たず、
 * `jin/renderSvg` が返した SVG の属性だけを読む。
 * 位置が要るとき（診断バッジ）は描かれた要素の `getBBox()` を使い、
 * レイアウト規則を再実装しない（レンダラは Python 1 本・要件書 §0）。
 */

/** `data-jin-kind` の 9 種。**10 種目を作らない**（`docs/spec/layout.md` §3）。 */
export const JIN_KINDS = [
  "circle",
  "core",
  "rune",
  "tool",
  "state",
  "flow-edge",
  "guard",
  "await",
  "delegate",
] as const;

export type JinKind = (typeof JIN_KINDS)[number];

export interface JinTarget {
  readonly pointer: string;
  readonly kind: JinKind | null;
  /** 参照を表す要素なら参照先の circle の pointer（`docs/spec/layout.md` §7 の referent 規則）。 */
  readonly ref: string | null;
}

function kindOf(element: Element): JinKind | null {
  const value = element.getAttribute("data-jin-kind");
  return (JIN_KINDS as readonly string[]).includes(value ?? "") ? (value as JinKind) : null;
}

/** クリックされた要素から、最も近い `data-jin` 付きの祖先を探す。 */
export function targetOf(element: Element | null): JinTarget | null {
  let node: Element | null = element;
  while (node !== null) {
    const pointer = node.getAttribute("data-jin");
    if (pointer !== null) {
      return { pointer, kind: kindOf(node), ref: node.getAttribute("data-jin-ref") };
    }
    node = node.parentElement;
  }
  return null;
}

/**
 * ある pointer を描いている要素すべて。
 *
 * **同じ pointer を持つ要素は複数あってよい**（`docs/spec/layout.md` §3。
 * 環と核と紋が同じ circle を指す）。ハイライトは全部に当てる。
 */
export function elementsFor(root: ParentNode, pointer: string): readonly Element[] {
  const escaped = cssEscape(pointer);
  return [
    ...root.querySelectorAll(`[data-jin="${escaped}"], [data-jin-ref="${escaped}"]`),
  ];
}

function cssEscape(value: string): string {
  return value.replace(/["\\]/g, "\\$&");
}
