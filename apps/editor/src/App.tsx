import { useCallback, useEffect, useMemo, useState } from "react";

import { PropertyPanel } from "./form/PropertyPanel";
import type { JsonSchema } from "./form/schemaForm";
import type { JinApi } from "./rpc/jin";
import type { JinDiagnostic, JinOp } from "./rpc/protocol";
import {
  EMPTY_HISTORY,
  type History,
  push as pushHistory,
  redo as redoStep,
  undo as undoStep,
} from "./state/history";
import { followRename, type Selection, resolveSelection, selectionFromPointer } from "./state/selection";
import { assertNever, hasDrawing, type ViewState } from "./state/viewState";
import { SvgCanvas } from "./svg/SvgCanvas";
import { DiagnosticList } from "./ui/DiagnosticList";
import { StatusBar } from "./ui/StatusBar";

/**
 * 編集モード（要件書 §7.1）。
 *
 * **ファイルが唯一の状態**である（要件書 §10 #10）。ここが持つ `ViewState` は
 * 直近のサーバ応答の写しであって、ローカルで書き換えることは一度も無い:
 * 変更はすべて `jin/applyOps` を往復し、返ってきたモデルと SVG で置き換える。
 * デバッグモード（トレースリプレイ）は Phase 6。
 */
export interface AppProps {
  readonly api: JinApi;
  readonly uri: string;
  readonly schema: JsonSchema;
}

export function App({ api, uri, schema }: AppProps): React.JSX.Element {
  const [state, setState] = useState<ViewState>({ kind: "disconnected", reason: null });
  const [selection, setSelection] = useState<Selection | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [history, setHistory] = useState<History>(EMPTY_HISTORY);
  // 診断は `jin/open` / `jin/applyOps` / `jin/save` の応答に載る（要件書 §5 の座標系のまま・
  // pointer 付き）。`publishDiagnostics` は LSP 座標（0 始まり・UTF-16）で来るので混ぜない。
  const [diagnostics, setDiagnostics] = useState<readonly JinDiagnostic[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  /** モデルと SVG を取り直して表示状態を作る。**SVG はキャッシュしない**（DP-COMMON-07）。 */
  const refresh = useCallback(
    async (nextFocus: string | null, found: readonly JinDiagnostic[]): Promise<void> => {
      try {
        const model = await api.model(uri);
        const drawing = await api.renderSvg(uri, { focus: nextFocus ?? undefined });
        setState({
          kind: model.stale || drawing.stale ? "stale" : "ready",
          uri,
          model: model.model,
          pointers: model.pointers,
          svg: drawing.svg,
          diagnostics: found,
        });
      } catch (error) {
        setState({ kind: "unavailable", uri, message: messageOf(error) });
      }
    },
    [api, uri],
  );

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading", uri });
    void (async () => {
      try {
        const opened = await api.open(uri);
        if (cancelled) return;
        setDiagnostics(opened.diagnostics);
        await refresh(null, opened.diagnostics);
      } catch (error) {
        if (!cancelled) setState({ kind: "unavailable", uri, message: messageOf(error) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, uri, refresh]);

  const model = hasDrawing(state) ? state.model : null;
  const selectedPointer = useMemo(
    () => (model === null || selection === null ? null : resolveSelection(model, selection)),
    [model, selection],
  );

  /** オペレーションを送る唯一の入口。履歴に積むかどうかだけが呼び出し側の裁量。 */
  const send = useCallback(
    async (ops: readonly JinOp[], options?: { readonly record?: boolean }): Promise<void> => {
      if (ops.length === 0 || model === null) return;
      setNotice(null);
      try {
        const result = await api.applyOps(uri, ops);
        if (!result.ok) {
          setNotice(`${result.error.code}: ${result.error.message}`);
          return;
        }
        if (options?.record !== false) {
          setHistory((current) => pushHistory(current, { forward: ops, inverse: result.inverses }));
        }
        // rename は選択中の要素の名前を変えるので、3 つ組を新名へ追随させる
        // （DP-COMMON-16 の cons が名指ししていた箇所）。
        setSelection((current) =>
          ops.reduce((acc, op) => followRename(acc, op, model), current),
        );
        setDiagnostics(result.diagnostics);
        await refresh(focus, result.diagnostics);
      } catch (error) {
        setNotice(messageOf(error));
      }
    },
    [api, uri, model, focus, refresh],
  );

  const save = useCallback(async (): Promise<void> => {
    try {
      // `text` を渡さない = サーバが持つモデルの正準形を書く
      // （`jin fmt` の出力とバイト一致・要件書 成功条件 5）。
      const result = await api.save(uri);
      setDiagnostics(result.diagnostics);
      setNotice(`保存しました: ${result.path}`);
    } catch (error) {
      setNotice(messageOf(error));
    }
  }, [api, uri]);

  const step = useCallback(
    async (direction: "undo" | "redo"): Promise<void> => {
      const next = direction === "undo" ? undoStep(history) : redoStep(history);
      if (next === null) return;
      setHistory(next.history);
      await send(next.ops, { record: false });
    },
    [history, send],
  );

  const body = ((): React.JSX.Element => {
    switch (state.kind) {
      case "disconnected":
      case "loading":
      case "unavailable":
        return <p className="jin-hint">{/* 状態はステータスバーが伝える */}</p>;
      case "ready":
      case "stale":
        return (
          <div className="jin-body">
            <SvgCanvas
              svg={state.svg}
              selectedPointer={selectedPointer}
              diagnostics={state.diagnostics}
              onPick={(target) => {
                const pointer = target.ref ?? target.pointer;
                setSelection(selectionFromPointer(state.model, pointer));
              }}
              onOpen={(target) => {
                // 入れ子の小陣をダブルクリックで focus を切り替える（要件書 §7.1）。
                const pointer = target.ref ?? target.pointer;
                const picked = selectionFromPointer(state.model, pointer);
                if (picked === null) return;
                const next = focus === picked.circle ? null : picked.circle;
                setFocus(next);
                void refresh(next, diagnostics);
              }}
              onMove={(from, to) => {
                // ドラッグで紋を環上で並べ替える → moveTool（要件書 §7.1）。
                // 落とした先の紋の添字を目的地にする。**角度はエディタが計算しない**。
                const index = Number(to.pointer.split("/").at(-1));
                if (!Number.isInteger(index)) return;
                void send([{ op: "moveTool", pointer: from.pointer, index }]);
              }}
              onDiagnostic={(diagnostic) => showDiagnostic(diagnostic, setNotice, setSelection, state.model)}
            />
            <aside className="jin-side">
              <PropertyPanel
                schema={schema}
                model={state.model}
                selection={selection}
                onChange={(ops) => void send(ops)}
              />
              <DiagnosticList
                diagnostics={state.diagnostics}
                onPick={(diagnostic) =>
                  showDiagnostic(diagnostic, setNotice, setSelection, state.model)
                }
              />
            </aside>
          </div>
        );
    }
    return assertNever(state);
  })();

  const circleOf = selection?.circle ?? null;

  return (
    <main className="jin-app">
      <header className="jin-toolbar">
        <button type="button" data-testid="jin-save" onClick={() => void save()}>
          保存
        </button>
        <button
          type="button"
          data-testid="jin-undo"
          disabled={history.undo.length === 0}
          onClick={() => void step("undo")}
        >
          元に戻す
        </button>
        <button
          type="button"
          data-testid="jin-redo"
          disabled={history.redo.length === 0}
          onClick={() => void step("redo")}
        >
          やり直す
        </button>
        <span className="jin-sep" />
        <button
          type="button"
          data-testid="jin-add-tool"
          disabled={model === null || circleOf === null}
          onClick={() => {
            if (model === null || circleOf === null) return;
            void send(addToList(model, circleOf, "tools"));
          }}
        >
          紋を追加
        </button>
        <button
          type="button"
          data-testid="jin-add-state"
          disabled={model === null || circleOf === null}
          onClick={() => {
            if (model === null || circleOf === null) return;
            void send(addToList(model, circleOf, "state"));
          }}
        >
          記憶を追加
        </button>
        <button
          type="button"
          data-testid="jin-add-delegate"
          disabled={model === null || circleOf === null}
          onClick={() => {
            if (model === null || circleOf === null) return;
            void send(addToList(model, circleOf, "delegate"));
          }}
        >
          委譲を追加
        </button>
        {focus === null ? null : (
          <button
            type="button"
            data-testid="jin-focus-clear"
            onClick={() => {
              setFocus(null);
              void refresh(null, diagnostics);
            }}
          >
            focus を外す（{focus}）
          </button>
        )}
      </header>
      <StatusBar state={state} />
      {notice === null ? null : (
        <p className="jin-notice" data-testid="jin-notice">
          {notice}
        </p>
      )}
      {body}
    </main>
  );
}

function showDiagnostic(
  diagnostic: JinDiagnostic,
  setNotice: (value: string) => void,
  setSelection: (value: Selection | null) => void,
  model: Parameters<typeof selectionFromPointer>[0],
): void {
  setNotice(
    diagnostic.hint === undefined
      ? `${diagnostic.code}: ${diagnostic.message}`
      : `${diagnostic.code}: ${diagnostic.message} — ${diagnostic.hint}`,
  );
  setSelection(selectionFromPointer(model, diagnostic.pointer));
}

/**
 * 環の空き位置への追加（要件書 §7.1「環の空き位置をクリック → addTool / addState」）。
 *
 * 新しい要素は**スキーマ上必須の欄だけ**を埋め、値は空にする。ここで
 * `ref` に架空のモジュール名を入れると、ユーザーが書いていない参照を捏造することになる。
 * 空のまま作れば `jin check` が未解決参照として診断を出し、次に何をすべきかが図に出る。
 */
function addToList(
  model: Parameters<typeof resolveSelection>[0],
  circleName: string,
  field: "tools" | "state" | "delegate",
): readonly JinOp[] {
  const pointer = resolveSelection(model, { circle: circleName, kind: "circle" });
  if (pointer === null) return [];
  const circle = (model["circles"] as Record<string, unknown>[] | undefined)?.[
    Number(pointer.split("/").at(-1))
  ];
  const list = circle?.[field];
  const index = Array.isArray(list) ? list.length : 0;
  const used = new Set(
    Array.isArray(list)
      ? list.map((item) =>
          typeof item === "string" ? item : String((item as { name?: unknown }).name ?? ""),
        )
      : [],
  );
  const name = freshName(field === "state" ? "state" : field === "tools" ? "tool" : "circle", used);
  const value =
    field === "delegate" ? name : field === "state" ? { name, type: "" } : { name, kind: "tool", ref: "" };
  return [{ op: field === "state" ? "addState" : field === "tools" ? "addTool" : "addDelegate", pointer: `${pointer}/${field}`, index, value }];
}

function freshName(base: string, used: ReadonlySet<string>): string {
  for (let i = 1; ; i += 1) {
    const candidate = `${base}${i}`;
    if (!used.has(candidate)) return candidate;
  }
}

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (error !== null && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}
