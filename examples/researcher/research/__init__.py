"""examples/researcher/researcher.jin の `ref` が指す先。

`.jin` の `tools[].ref` / `boundary.guards[].ref` は `module.path:callable` 形式で、
**Jin はモジュールの中身を持たない**。examples を `jin run` / `adk run` で実際に
動かせるようにするため、参照先をここに置く（要件書 §11 Phase 2 の完了条件
「examples 両方が adk run で動く」）。

`jin run` は `.jin` が置かれたディレクトリを `sys.path` に足すので、
`examples/researcher/` から見て `research` パッケージがここに見える。

**ネットワークに出ない**（NFR-TEST-001）。実際に検索や公開をするのではなく、
形（引数・返り値・コールバックのシグネチャ）だけを本物に合わせた雛形である。
"""
