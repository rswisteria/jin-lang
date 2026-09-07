import type { JinModel } from "../rpc/protocol";
import type { Selection } from "../state/selection";
import { resolveSelection } from "../state/selection";
import { type FieldChange, fieldsForSelection, opsForChange } from "./dispatch";
import type { JsonSchema } from "./schemaForm";

/**
 * プロパティパネル（要件書 §7.1）。
 *
 * **欄は `schemas/jin.schema.json` から生成する。** このファイルに欄の名前は 1 つも無い。
 * 値は現在のモデルから pointer で引き、変更は `jin/applyOps` へ流す。
 */
export interface PropertyPanelProps {
  readonly schema: JsonSchema;
  readonly model: JinModel;
  readonly selection: Selection | null;
  readonly onChange: (ops: ReturnType<typeof opsForChange>) => void;
}

export function PropertyPanel(props: PropertyPanelProps): React.JSX.Element {
  const { schema, model, selection } = props;
  if (selection === null) {
    return <p className="jin-hint">図の要素をクリックすると、ここに欄が出ます。</p>;
  }
  const pointer = resolveSelection(model, selection);
  if (pointer === null) {
    return <p className="jin-hint">選択していた要素が見つかりません（削除されたか、名前が変わりました）。</p>;
  }
  const value = valueAt(model, pointer);
  const fields = fieldsForSelection(schema, selection, value);
  if (fields.length === 0) {
    return <p className="jin-hint">この要素に編集できる欄はありません（配列は図の操作で編集します）。</p>;
  }
  // `core` / `rune` の pointer はスカラを指す。欄が 1 つだけの定義なので、その欄の値として読む。
  const only = fields.length === 1 ? fields[0]?.key : undefined;
  const record: Record<string, unknown> =
    value !== null && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : only === undefined
        ? {}
        : { [only]: value };

  return (
    <form className="jin-form" data-testid="jin-form" onSubmit={(event) => event.preventDefault()}>
      <p className="jin-pointer" data-testid="jin-pointer">
        {pointer}
      </p>
      {fields.map((field) => {
        const id = `jin-field-${field.key}`;
        const current = record[field.key];
        const emit = (next: FieldChange["value"]): void => {
          props.onChange(opsForChange(model, selection, { key: field.key, value: next }));
        };
        return (
          <div className="jin-field" key={field.key}>
            <label htmlFor={id}>{field.label}</label>
            {field.type === "boolean" ? (
              <input
                id={id}
                type="checkbox"
                checked={current === true}
                disabled={field.readOnly}
                onChange={(event) => emit(event.currentTarget.checked)}
              />
            ) : field.type === "enum" && field.options !== null ? (
              <select
                id={id}
                defaultValue={typeof current === "string" ? current : ""}
                disabled={field.readOnly}
                onChange={(event) => emit(event.currentTarget.value)}
              >
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                type={field.type === "number" ? "number" : "text"}
                defaultValue={current === null || current === undefined ? "" : String(current)}
                readOnly={field.readOnly}
                {...(field.maxLength === null ? {} : { maxLength: field.maxLength })}
                onBlur={(event) => emit(event.currentTarget.value)}
              />
            )}
            {field.description === null ? null : (
              <span className="jin-desc">{field.description}</span>
            )}
          </div>
        );
      })}
    </form>
  );
}

function valueAt(model: JinModel, pointer: string): unknown {
  let node: unknown = model;
  for (const segment of pointer.split("/").slice(1)) {
    if (node === null || typeof node !== "object") return null;
    node = Array.isArray(node) ? node[Number(segment)] : (node as Record<string, unknown>)[segment];
  }
  return node ?? null;
}
