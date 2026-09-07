import { useEffect, useRef } from "react";

import type { JinDiagnostic } from "../rpc/protocol";
import { elementsFor, type JinTarget, targetOf } from "./hitTest";

/**
 * `jin/renderSvg` が返した SVG をそのまま埋める（要件書 §7.1）。
 *
 * **エディタは 1 本の線も描かない。** ここでするのは
 * (1) 選択のハイライト（属性の差し替え）、(2) 診断バッジの重ね置き、
 * (3) `data-jin` によるヒットテストの 3 つだけである。
 */
export interface SvgCanvasProps {
  readonly svg: string;
  readonly selectedPointer: string | null;
  readonly diagnostics: readonly JinDiagnostic[];
  readonly onPick: (target: JinTarget) => void;
  readonly onOpen: (target: JinTarget) => void;
  readonly onMove: (from: JinTarget, to: JinTarget) => void;
  readonly onDiagnostic: (diagnostic: JinDiagnostic) => void;
}

const OVERLAY_ID = "jin-editor-overlay";
const HIGHLIGHT = "#c2410c";

export function SvgCanvas(props: SvgCanvasProps): React.JSX.Element {
  const host = useRef<HTMLDivElement>(null);
  const dragging = useRef<JinTarget | null>(null);

  // SVG の差し替え。React に管理させず innerHTML で入れる（属性名が SVG 固有で、
  // JSX へ写すと `data-jin-*` 以外の綴りが変わる危険がある）。
  useEffect(() => {
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
    if (props.selectedPointer !== null) {
      for (const element of elementsFor(svg, props.selectedPointer)) {
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
  }, [props.svg, props.selectedPointer, props.diagnostics]);

  return (
    <div
      ref={host}
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
        if (target !== null) props.onPick(target);
      }}
      onDoubleClick={(event) => {
        const target = targetOf(event.target as Element);
        if (target !== null) props.onOpen(target);
      }}
      onPointerDown={(event) => {
        const target = targetOf(event.target as Element);
        dragging.current = target !== null && target.kind === "tool" ? target : null;
      }}
      onPointerUp={(event) => {
        const from = dragging.current;
        dragging.current = null;
        if (from === null) return;
        const to = targetOf(event.target as Element);
        if (to !== null && to.kind === "tool" && to.pointer !== from.pointer) {
          props.onMove(from, to);
        }
      }}
    />
  );
}

/**
 * 診断バッジ。位置は**描かれた要素の `getBBox()`** から取る。
 *
 * レイアウト規則を再実装しないための唯一の方法である（要件書 §0）。
 * `getBBox` を持たない環境（jsdom）では何も置かない — バッジの有無で
 * ユニットテストを書かず、Playwright のスモークで見る。
 */
function buildBadges(svg: SVGSVGElement, diagnostics: readonly JinDiagnostic[]): SVGGElement | null {
  if (diagnostics.length === 0) return null;
  const ns = "http://www.w3.org/2000/svg";
  const group = document.createElementNS(ns, "g");
  group.setAttribute("id", OVERLAY_ID);
  let placed = 0;
  for (const diagnostic of diagnostics) {
    const anchor = elementsFor(svg, diagnostic.pointer)[0];
    if (anchor === undefined || typeof (anchor as SVGGraphicsElement).getBBox !== "function") {
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
    badge.setAttribute("fill", diagnostic.severity === "error" ? "#dc2626" : "#d97706");
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
