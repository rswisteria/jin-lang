/**
 * プロパティパネルのフォームを **`schemas/jin.schema.json` から生成**する
 * （要件書 §7.1「フォームは JSON Schema から生成する（手書きのフォーム定義を持たない）」）。
 *
 * このファイルには**欄の一覧が 1 つも書かれていない**。欄・型・必須・最大長・選択肢は
 * すべて schema から読む。`test/schemaForm.test.ts` が schema に架空のキーを足すと
 * 欄が増えることを確かめる（「定義が無い」の grep より強い証拠）。
 *
 * ラベルは schema の `title` と `description` だけを使う。日本語のラベルを別途持つと、
 * それ自体が手書きのフォーム定義になる。
 */

export interface JsonSchema {
  readonly $defs?: Readonly<Record<string, JsonSchema>>;
  readonly $ref?: string;
  readonly type?: string | readonly string[];
  readonly title?: string;
  readonly description?: string;
  readonly properties?: Readonly<Record<string, JsonSchema>>;
  readonly required?: readonly string[];
  readonly enum?: readonly unknown[];
  readonly const?: unknown;
  readonly anyOf?: readonly JsonSchema[];
  readonly oneOf?: readonly JsonSchema[];
  readonly items?: JsonSchema;
  readonly maxLength?: number;
  readonly discriminator?: { readonly propertyName: string; readonly mapping: Record<string, string> };
}

export type FieldType = "string" | "boolean" | "number" | "enum";

export interface FormField {
  readonly key: string;
  readonly label: string;
  readonly description: string | null;
  readonly type: FieldType;
  readonly required: boolean;
  /** `const` の欄（tool の `kind` など）。値は変えられない。 */
  readonly readOnly: boolean;
  readonly maxLength: number | null;
  readonly options: readonly string[] | null;
  /** null を許す欄か（`anyOf: [X, null]`）。空欄にすると null を送る。 */
  readonly nullable: boolean;
}

/** `#/$defs/State` のような内部参照を解く。外部参照は解かない（この schema に無い）。 */
export function resolveRef(root: JsonSchema, ref: string): JsonSchema | null {
  const path = ref.split("/");
  if (path[0] !== "#") return null;
  let node: unknown = root;
  for (const segment of path.slice(1)) {
    if (node === null || typeof node !== "object") return null;
    node = (node as Record<string, unknown>)[segment];
  }
  return node !== null && typeof node === "object" ? (node as JsonSchema) : null;
}

interface Unwrapped {
  readonly schema: JsonSchema;
  readonly nullable: boolean;
}

/** `anyOf: [X, {type: null}]` を X に開き、`$ref` を辿る。 */
export function unwrap(root: JsonSchema, schema: JsonSchema): Unwrapped {
  if (schema.$ref !== undefined) {
    const target = resolveRef(root, schema.$ref);
    return target === null ? { schema, nullable: false } : unwrap(root, target);
  }
  const branches = schema.anyOf ?? schema.oneOf;
  if (branches === undefined) return { schema, nullable: false };
  const nullable = branches.some((branch) => branch.type === "null");
  const rest = branches.filter((branch) => branch.type !== "null");
  if (rest.length !== 1 || rest[0] === undefined) return { schema, nullable };
  const inner = unwrap(root, rest[0]);
  return { schema: inner.schema, nullable: nullable || inner.nullable };
}

function fieldTypeOf(schema: JsonSchema): FieldType | null {
  if (schema.enum !== undefined) return "enum";
  if (schema.const !== undefined) return "string";
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  switch (type) {
    case "string":
      return "string";
    case "boolean":
      return "boolean";
    case "integer":
    case "number":
      return "number";
    default:
      // 配列・オブジェクト・解けない型はフォームに出さない。
      // 配列（tools / state / delegate）は SVG 側の操作で編集する（要件書 §7.1）。
      return null;
  }
}

/**
 * オブジェクト定義 → スカラ欄の並び。**順序は schema の `properties` の順**で決定的。
 */
export function fieldsOf(root: JsonSchema, objectSchema: JsonSchema): readonly FormField[] {
  const properties = objectSchema.properties ?? {};
  const required = new Set(objectSchema.required ?? []);
  const fields: FormField[] = [];
  for (const [key, raw] of Object.entries(properties)) {
    const { schema, nullable } = unwrap(root, raw);
    const type = fieldTypeOf(schema);
    if (type === null) continue;
    fields.push({
      key,
      label: schema.title ?? raw.title ?? key,
      description: schema.description ?? raw.description ?? null,
      type,
      required: required.has(key),
      readOnly: schema.const !== undefined,
      maxLength: schema.maxLength ?? null,
      options: schema.enum === undefined ? null : schema.enum.map((value) => String(value)),
      nullable,
    });
  }
  return fields;
}

/** 判別共用体（tools）の枝を、値の判別キーで選ぶ。 */
export function branchFor(root: JsonSchema, arraySchema: JsonSchema, value: unknown): JsonSchema | null {
  const items = arraySchema.items;
  if (items === undefined) return null;
  const discriminator = items.discriminator;
  if (discriminator === undefined) return unwrap(root, items).schema;
  const key =
    value !== null && typeof value === "object"
      ? (value as Record<string, unknown>)[discriminator.propertyName]
      : undefined;
  const ref = typeof key === "string" ? discriminator.mapping[key] : undefined;
  return ref === undefined ? null : resolveRef(root, ref);
}
