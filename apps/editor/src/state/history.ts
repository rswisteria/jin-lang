import type { JinOp } from "../rpc/protocol";

/**
 * undo / redo（要件書 §7.1 / §6.3）。
 *
 * **スタックに積むのはサーバが返した逆オペレーション列だけ**である。
 * モデルの写しを積むと「エディタは独自のモデル状態を持たない」（要件書 §10 #10）に反する。
 * 逆を当てると元の正準形へバイト単位で戻ることは `jin_core.ops` 側で 19 件検証済みなので、
 * ここでは順序の管理だけを行う。
 */
export interface HistoryEntry {
  /** ユーザーが当てた順オペレーション列（redo で使う）。 */
  readonly forward: readonly JinOp[];
  /** サーバが返した逆オペレーション列（undo で使う）。 */
  readonly inverse: readonly JinOp[];
}

export interface History {
  readonly undo: readonly HistoryEntry[];
  readonly redo: readonly HistoryEntry[];
}

export const EMPTY_HISTORY: History = { undo: [], redo: [] };

/** 新しい編集を積む。**redo は捨てる**（分岐した歴史を持たない）。 */
export function push(history: History, entry: HistoryEntry): History {
  return { undo: [...history.undo, entry], redo: [] };
}

export interface Step {
  readonly ops: readonly JinOp[];
  readonly history: History;
}

/**
 * undo 1 歩。当てるべきオペレーション列と、次の履歴を返す。
 *
 * サーバが返す逆列は「先頭から順に当てると元に戻る」形（`apply_ops` の原子性）なので、
 * ここで並べ替えない。
 */
export function undo(history: History): Step | null {
  const entry = history.undo.at(-1);
  if (entry === undefined) return null;
  return {
    ops: entry.inverse,
    history: { undo: history.undo.slice(0, -1), redo: [...history.redo, entry] },
  };
}

/** redo 1 歩。undo で退避した順オペレーション列を当て直す。 */
export function redo(history: History): Step | null {
  const entry = history.redo.at(-1);
  if (entry === undefined) return null;
  return {
    ops: entry.forward,
    history: { undo: [...history.undo, entry], redo: history.redo.slice(0, -1) },
  };
}
