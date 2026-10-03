import type { ReadResult } from "./client";

export interface ImportPanelProps {
	readonly result: ReadResult;
	/** 落とした写真の object URL（ブラウザの手元にある写真をそのまま見せる。サーバから配り直さない）。 */
	readonly photoUrl: string;
	readonly onClose: () => void;
}

function percent(value: number, whole: number): string {
	return `${String(Math.round((value / whole) * 10000) / 100)}%`;
}

/**
 * 取り込んだ写真を下敷きにして、診断を写真の座標（場面グラフの `box`）に重ねる（陣書き S5・設計書 §4.3）。
 *
 * **HTML の層で描く**（`<img>` と % で置いた枠）。エディタは魔法陣の SVG に 1 本も線を足さない
 * （`createElementNS` の禁止）。写真とレンダラの図は幾何が違う（手描きの型紙と決定的レイアウト）ので、
 * 図の背後に敷かず脇に並べる。取り込み後の正本は `.jin` で、写真は見比べるための下敷き。
 */
export function ImportPanel({
	result,
	photoUrl,
	onClose,
}: ImportPanelProps): React.JSX.Element {
	const { width, height } = result.image;
	const placed = result.diagnostics.filter((d) => d.box !== null);
	return (
		<section className="jin-import" data-testid="jin-import-panel">
			<h2>
				取り込んだ写真: {result.photo}
				<button type="button" data-testid="jin-import-close" onClick={onClose}>
					閉じる
				</button>
			</h2>
			<p className="jin-hint" data-testid="jin-import-summary">
				{result.jin === null
					? `陣を組めませんでした（絵の文法の誤り）。${result.scene} を直して、同じ写真をもう一度取り込んでください（読み直しは API を呼びません）。`
					: `${decodeURIComponent(result.jin.split("/").at(-1) ?? "")} を書いて開きました（場面グラフは ${result.scene}）。これからの正本は .jin です。`}
			</p>
			<div className="jin-import-photo">
				<img data-testid="jin-import-photo" src={photoUrl} alt={result.photo} />
				{width > 0 && height > 0
					? placed.map((d, i) => {
							const [x0, y0, x1, y1] = d.box ?? [0, 0, 0, 0];
							return (
								<div
									key={`${d.pointer}-${String(i)}`}
									className={`jin-import-box jin-severity-${d.severity}`}
									data-testid="jin-import-box"
									data-code={d.code}
									data-severity={d.severity}
									title={`${d.code}: ${d.message}`}
									style={{
										left: percent(x0, width),
										top: percent(y0, height),
										width: percent(x1 - x0, width),
										height: percent(y1 - y0, height),
									}}
								/>
							);
						})
					: null}
			</div>
			{result.diagnostics.length === 0 ? null : (
				<ul className="jin-diagnostics">
					{result.diagnostics.map((d, i) => (
						<li
							key={`${d.pointer}-${String(i)}`}
							className={`jin-severity-${d.severity}`}
							data-testid="jin-import-diagnostic"
						>
							{d.code}: {d.message}
							{d.hint === null ? null : ` — ${d.hint}`}
						</li>
					))}
				</ul>
			)}
		</section>
	);
}
