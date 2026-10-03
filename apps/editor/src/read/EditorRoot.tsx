import { useCallback, useEffect, useRef, useState } from "react";

import { App, type AppProps } from "../App";
import { ImportPanel } from "./ImportPanel";
import {
	isImageName,
	type ReadResult,
	readImage,
	uriInLocation,
} from "./client";

export type EditorRootProps = Omit<
	AppProps,
	"uri" | "importControl" | "underlay"
> & {
	/** 起動時に開くファイル（URL の `?uri=`）。 */
	readonly initialUri: string;
};

interface Imported {
	readonly result: ReadResult;
	readonly photoUrl: string;
}

/**
 * 開いているファイルを状態に持ち、写真の取り込み（`POST /read`・陣書き S5）で書かれた `.jin` を開き直す。
 *
 * 開き直しは `App` を `key={uri}` で作り直すだけ（`jin/open` は `jin editor` の root の中なら
 * どの `.jin` でも開ける。取り込みはその root に書く）。`history.replaceState` で URL の `uri` も差し替えるので、
 * 再読み込みしても取り込んだ `.jin` が開く。写真はブラウザの手元の object URL で見せる（サーバから配り直さない）。
 */
export function EditorRoot({
	initialUri,
	...props
}: EditorRootProps): React.JSX.Element {
	const [uri, setUri] = useState(initialUri);
	const [imported, setImported] = useState<Imported | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const input = useRef<HTMLInputElement>(null);
	const busyRef = useRef(false);

	const replacePhoto = useCallback((next: Imported | null) => {
		setImported((previous) => {
			if (previous !== null && previous.photoUrl !== next?.photoUrl)
				URL.revokeObjectURL(previous.photoUrl);
			return next;
		});
	}, []);

	const take = useCallback(
		async (file: File) => {
			if (busyRef.current) return;
			if (!isImageName(file.name)) {
				setError(
					`取り込めるのは写真（.jpg / .jpeg / .webp）か完全陣（.png）だけです: ${file.name}`,
				);
				return;
			}
			busyRef.current = true;
			setBusy(true);
			setError(null);
			try {
				const outcome = await readImage({
					origin: props.runOrigin,
					token: props.token,
					file,
				});
				if (outcome.kind === "error") {
					setError(outcome.message);
					return;
				}
				replacePhoto({
					result: outcome.result,
					photoUrl: URL.createObjectURL(file),
				});
				const opened = outcome.result.jin;
				if (opened !== null) {
					setUri(opened);
					window.history.replaceState(
						null,
						"",
						uriInLocation(window.location.href, opened),
					);
				}
			} catch (caught: unknown) {
				setError(caught instanceof Error ? caught.message : String(caught));
			} finally {
				busyRef.current = false;
				setBusy(false);
			}
		},
		[props.runOrigin, props.token, replacePhoto],
	);

	// 「写真を落とす」: ページのどこに落としても取り込む（画像のファイルだけ。他は既定の動作のまま）。
	useEffect(() => {
		const hasFiles = (event: DragEvent): boolean =>
			event.dataTransfer?.types.includes("Files") ?? false;
		const over = (event: DragEvent): void => {
			if (hasFiles(event)) event.preventDefault();
		};
		const drop = (event: DragEvent): void => {
			const file = event.dataTransfer?.files[0];
			if (file === undefined || !isImageName(file.name)) return;
			event.preventDefault();
			void take(file);
		};
		window.addEventListener("dragover", over);
		window.addEventListener("drop", drop);
		return () => {
			window.removeEventListener("dragover", over);
			window.removeEventListener("drop", drop);
		};
	}, [take]);

	const control = (
		<>
			<button
				type="button"
				data-testid="jin-import"
				disabled={busy}
				title="型紙に手で描いた陣の写真を取り込む（写真は Anthropic の API に送って読み取ります）"
				onClick={() => input.current?.click()}
			>
				{busy ? "読み取り中…" : "写真を取り込む"}
			</button>
			<input
				ref={input}
				type="file"
				hidden
				data-testid="jin-import-file"
				accept=".jpg,.jpeg,.webp,.png"
				onChange={(event) => {
					const file = event.currentTarget.files?.[0];
					event.currentTarget.value = "";
					if (file !== undefined) void take(file);
				}}
			/>
			{error === null ? null : (
				<span className="jin-import-error" data-testid="jin-import-error">
					{error}
				</span>
			)}
		</>
	);

	return (
		<App
			key={uri}
			{...props}
			uri={uri}
			importControl={control}
			underlay={
				imported === null ? null : (
					<ImportPanel
						result={imported.result}
						photoUrl={imported.photoUrl}
						onClose={() => replacePhoto(null)}
					/>
				)
			}
		/>
	);
}
