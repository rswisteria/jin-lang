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
  /**
   * Jin v2 の**式の欄の印**（`jin_core.v2.model.Expr`。`schemas/jin-v2.schema.json` にだけ現れる）。
   * 式エディタを出すかどうかはこの印だけで決める（欄の名前を書き写さない・設計書 §8）。
   */
  readonly "x-jin-expr"?: boolean;
  /**
   * Jin v2.1 の**行の表の印**（`jin_core.v2.model.INLINE_SCHEMA_MARK`。`Rite.params` にだけ付く）。
   * 配列は原則として図の操作で編集するが、この印のある「平らなオブジェクトの配列」だけは
   * 図に載らないので、行ごとの欄を持つ表にする（欄の名前を書き写さない）。
   */
  readonly "x-jin-inline"?: boolean;
}

/**
 * `exprList` は **式の列**（`cast.args` / `emit.args`。`items` に `x-jin-expr` が付いた配列）。
 * 配列は原則としてフォームに出さない（図の操作で編集する）が、式の列だけは図に載らないので
 * 行ごとの式エディタとして例外扱いにする。
 */
/**
 * `rowList` は **行の表**（`x-jin-inline` の付いた、スカラ欄だけのオブジェクトの配列。`Rite.params`）。
 * 列は要素の schema から `fieldsOf` で生成する（`columns`）。
 */
export type FieldType = "string" | "boolean" | "number" | "enum" | "exprList" | "rowList";

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
  /** 式の欄（`x-jin-expr`）。`exprList` は要素が式。 */
  readonly expr: boolean;
  /** `rowList` の列（要素の schema のスカラ欄）。他の型では null。 */
  readonly columns: readonly FormField[] | null;
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

function fieldTypeOf(root: JsonSchema, schema: JsonSchema): FieldType | null {
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
    case "array":
      // 式の列（v2 の `args`）と、印のある行の表（v2.1 の `params`）だけは欄にする。
      // 他の配列は図の操作で編集する。
      if (schema.items === undefined) return null;
      if (isExpr(root, schema.items)) return "exprList";
      return schema["x-jin-inline"] === true && rowColumns(root, schema.items) !== null
        ? "rowList"
        : null;
    default:
      // 配列・オブジェクト・解けない型はフォームに出さない。
      // 配列（tools / state / delegate）は SVG 側の操作で編集する（要件書 §7.1）。
      return null;
  }
}

/**
 * 行の表の列。要素が**スカラ欄だけのオブジェクト**（配列・オブジェクト・式の列を含まない）なら
 * その欄の並び、そうでなければ null（列が決まらないので表にしない）。
 */
export function rowColumns(root: JsonSchema, items: JsonSchema): readonly FormField[] | null {
  const item = unwrap(root, items).schema;
  const properties = item.properties;
  if (item.type !== "object" || properties === undefined) return null;
  const columns = fieldsOf(root, item);
  const scalar = columns.every((column) => column.type !== "exprList" && column.type !== "rowList");
  return scalar && columns.length === Object.keys(properties).length ? columns : null;
}

/** `x-jin-expr` が付いているか（`anyOf` / `$ref` の内側も見る）。 */
export function isExpr(root: JsonSchema, schema: JsonSchema): boolean {
  if (schema["x-jin-expr"] === true) return true;
  return unwrap(root, schema).schema["x-jin-expr"] === true;
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
    const type = fieldTypeOf(root, schema);
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
      expr: type === "exprList" || isExpr(root, schema),
      columns: type === "rowList" && schema.items !== undefined ? rowColumns(root, schema.items) : null,
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
