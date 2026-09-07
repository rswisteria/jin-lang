import type { JinDiagnostic } from "../rpc/protocol";

/** 診断の一覧。バッジのクリックと同じ内容をテキストでも出す（バッジは SVG に依存する）。 */
export function DiagnosticList({
  diagnostics,
  onPick,
}: {
  readonly diagnostics: readonly JinDiagnostic[];
  readonly onPick: (diagnostic: JinDiagnostic) => void;
}): React.JSX.Element {
  if (diagnostics.length === 0) {
    return <p className="jin-hint" data-testid="jin-diagnostics">診断はありません。</p>;
  }
  return (
    <ul className="jin-diagnostics" data-testid="jin-diagnostics">
      {diagnostics.map((diagnostic, index) => (
        <li key={`${diagnostic.code}-${diagnostic.pointer}-${index}`}>
          <button type="button" onClick={() => onPick(diagnostic)}>
            <span className={`jin-severity jin-severity-${diagnostic.severity}`}>
              {diagnostic.code}
            </span>{" "}
            {diagnostic.message}
          </button>
        </li>
      ))}
    </ul>
  );
}
