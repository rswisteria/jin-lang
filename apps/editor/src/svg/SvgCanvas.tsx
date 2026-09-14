import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { ValueLabel } from "../debug/values";
import type { JinDiagnostic } from "../rpc/protocol";
import {
	DRAGGABLE_KINDS,
	elementsFor,
	type JinTarget,
	targetOf,
} from "./hitTest";

/**
 * `jin/renderSvg` が返した SVG をそのまま埋める（要件書 §7.1）。
 *
 * **エディタは 1 本の線も描かない。** ここでするのは
 * (1) 選択のハイライト（属性の差し替え）、(2) 診断バッジの重ね置き、
 * (3) `data-jin` によるヒットテスト、(4) 記憶環の値と `assert` のラベル（**HTML**）の
 * 重ね置き（Jin v2 Phase 6）の 4 つだけである。
 *
 * ラベルは SVG の中に作らない（`<text>` を作れば陣を描いていることになる）。SVG の外の
 * HTML 層に置き、位置は**描かれた要素の `getBoundingClientRect()`** から取る（診断バッジの
 * `getBBox()` と同じ理由: レイアウト規則を再実装しない）。
 */
export interface SvgCanvasProps {
	readonly svg: string;
	/** ハイライトする pointer（v2 のステップの範囲選択では複数・無ければ空）。 */
	readonly selectedPointers: readonly string[];
	readonly diagnostics: readonly JinDiagnostic[];
	/** 図に重ねるラベル（pointer の要素の右上に置く）。無ければ空。 */
	readonly labels: readonly ValueLabel[];
	/** `extend` は Shift を押したままのクリック（v2 のステップの範囲選択）。 */
	readonly onPick: (target: JinTarget, extend: boolean) => void;
	readonly onOpen: (target: JinTarget) => void;
	readonly onMove: (from: JinTarget, to: JinTarget) => void;
	readonly onDiagnostic: (diagnostic: JinDiagnostic) => void;
}

const OVERLAY_ID = "jin-editor-overlay";
const HIGHLIGHT = "#c2410c";

interface PlacedLabel extends ValueLabel {
	readonly left: number;
	readonly top: number;
}

export function SvgCanvas(props: SvgCanvasProps): React.JSX.Element {
	const outer = useRef<HTMLDivElement>(null);
	const host = useRef<HTMLDivElement>(null);
	const dragging = useRef<JinTarget | null>(null);
	const [placed, setPlaced] = useState<readonly PlacedLabel[]>([]);

	// SVG の差し替え。React に管理させず innerHTML で入れる（属性名が SVG 固有で、
	// JSX へ写すと `data-jin-*` 以外の綴りが変わる危険がある）。
	// **layout effect にする**: 下のラベルの位置決めも layout effect で、宣言順に走る。
	// 普通の effect にすると、SVG が変わったコミットでラベルが**古い図**の矩形で置かれ、
	// focus を変えたときに消えるべき値のラベルが前の図の座標に浮いたまま残る。
	useLayoutEffect(() => {
		const node = host.current;
		if (node === null) return;
		node.innerHTML = props.svg;
	}, [props.svg]);

	// 選択のハイライトと診断バッジ。SVG が変わるたび / 選択が変わるたびに引き直す。
	useEffect(() => {
		const node = host.current;
		if (node === null) return;
		const svg = node.querySelector("svg");
		if (svg === null) return;

		for (const element of svg.querySelectorAll("[data-jin-selected]")) {
			element.removeAttribute("data-jin-selected");
			const stroke = element.getAttribute("data-jin-stroke-was");
			if (stroke !== null) {
				element.setAttribute("stroke", stroke);
				element.removeAttribute("data-jin-stroke-was");
			}
		}
		for (const pointer of props.selectedPointers) {
			for (const element of elementsFor(svg, pointer)) {
				if (element.hasAttribute("data-jin-selected")) continue;
				element.setAttribute("data-jin-selected", "1");
				const stroke = element.getAttribute("stroke");
				if (stroke !== null) {
					element.setAttribute("data-jin-stroke-was", stroke);
					element.setAttribute("stroke", HIGHLIGHT);
				}
			}
		}

		svg.querySelector(`#${OVERLAY_ID}`)?.remove();
		const badges = buildBadges(svg, props.diagnostics);
		if (badges !== null) svg.append(badges);
	}, [props.svg, props.selectedPointers, props.diagnostics]);

	// ラベルの位置。SVG / ラベル / 窓の幅が変わるたびに、描かれた要素の矩形から取り直す。
	const labels = props.labels;
	useLayoutEffect(() => {
		const place = (): void => {
			const root = outer.current;
			const node = host.current;
			if (root === null || node === null) return;
			setPlaced(placeLabels(root, node, labels));
		};
		place();
		window.addEventListener("resize", place);
		return () => window.removeEventListener("resize", place);
	}, [props.svg, labels]);

	return (
		<div
			ref={outer}
			className="jin-canvas"
			data-testid="jin-canvas"
			onClick={(event) => {
				const badge = (event.target as Element).closest("[data-jin-badge]");
				if (badge !== null) {
					const code = badge.getAttribute("data-jin-badge");
					const found = props.diagnostics.find((d) => d.code === code);
					if (found !== undefined) {
						props.onDiagnostic(found);
						return;
					}
				}
				const target = targetOf(event.target as Element);
				if (target !== null) props.onPick(target, event.shiftKey);
			}}
			onDoubleClick={(event) => {
				const target = targetOf(event.target as Element);
				if (target !== null) props.onOpen(target);
			}}
			onPointerDown={(event) => {
				const target = targetOf(event.target as Element);
				dragging.current =
					target !== null &&
					target.kind !== null &&
					DRAGGABLE_KINDS.includes(target.kind)
						? target
						: null;
			}}
			onPointerUp={(event) => {
				const from = dragging.current;
				dragging.current = null;
				if (from === null) return;
				const to = targetOf(event.target as Element);
				// 別の要素の上に落としたら渡す。何をするか（並べ替え / 列を跨ぐ移動 / 陣を結ぶ）は
				// 呼び出し側が落とし先の種別で決める（同じ要素の上なら、ただのクリック）。
				if (to !== null && to.pointer !== from.pointer) {
					props.onMove(from, to);
				}
			}}
		>
			<div ref={host} className="jin-canvas-svg" />
			{placed.length === 0 ? null : (
				<div className="jin-labels" data-testid="jin-labels">
					{placed.map((label) => (
						<span
							key={`${label.tone}:${label.pointer}`}
							className="jin-label"
							data-testid="jin-label"
							data-jin-label={label.pointer}
							data-tone={label.tone}
							style={{
								left: `${String(label.left)}px`,
								top: `${String(label.top)}px`,
							}}
						>
							{label.text}
						</span>
					))}
				</div>
			)}
		</div>
	);
}

/**
 * ラベルの位置: pointer の要素（`data-jin`。参照側 `data-jin-ref` は使わない）の矩形の右上を、
 * スクロール入れ物（`.jin-canvas`）の座標にする。要素が無い / 矩形が取れない（jsdom）ものは置かない。
 */
function placeLabels(
	root: HTMLElement,
	host: HTMLElement,
	labels: readonly ValueLabel[],
): readonly PlacedLabel[] {
	const svg = host.querySelector("svg");
	if (svg === null || labels.length === 0) return [];
	const base = root.getBoundingClientRect();
	const out: PlacedLabel[] = [];
	for (const label of labels) {
		const anchor = elementsFor(svg, label.pointer).find(
			(element) => element.getAttribute("data-jin") === label.pointer,
		);
		if (anchor === undefined) continue;
		const box = anchor.getBoundingClientRect();
		if (box.width === 0 && box.height === 0) continue;
		out.push({
			...label,
			left: box.right - base.left + root.scrollLeft,
			top: box.top - base.top + root.scrollTop,
		});
	}
	return out;
}

/**
 * 診断バッジ。位置は**描かれた要素の `getBBox()`** から取る。
 *
 * レイアウト規則を再実装しないための唯一の方法である（要件書 §0）。
 * `getBBox` を持たない環境（jsdom）では何も置かない — バッジの有無で
 * ユニットテストを書かず、Playwright のスモークで見る。
 */
function buildBadges(
	svg: SVGSVGElement,
	diagnostics: readonly JinDiagnostic[],
): SVGGElement | null {
	if (diagnostics.length === 0) return null;
	const ns = "http://www.w3.org/2000/svg";
	const group = document.createElementNS(ns, "g");
	group.setAttribute("id", OVERLAY_ID);
	let placed = 0;
	for (const diagnostic of diagnostics) {
		const anchor = elementsFor(svg, diagnostic.pointer)[0];
		if (
			anchor === undefined ||
			typeof (anchor as SVGGraphicsElement).getBBox !== "function"
		) {
			continue;
		}
		let box: DOMRect;
		try {
			box = (anchor as SVGGraphicsElement).getBBox();
		} catch {
			continue;
		}
		const badge = document.createElementNS(ns, "circle");
		badge.setAttribute("cx", String(box.x + box.width));
		badge.setAttribute("cy", String(box.y));
		badge.setAttribute("r", "6");
		badge.setAttribute(
			"fill",
			diagnostic.severity === "error" ? "#dc2626" : "#d97706",
		);
		badge.setAttribute("data-jin-badge", diagnostic.code);
		badge.setAttribute("style", "cursor: pointer");
		const title = document.createElementNS(ns, "title");
		title.textContent = `${diagnostic.code}: ${diagnostic.message}`;
		badge.append(title);
		group.append(badge);
		placed += 1;
	}
	return placed === 0 ? null : group;
}
