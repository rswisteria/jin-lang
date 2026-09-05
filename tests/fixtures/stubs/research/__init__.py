"""examples/researcher/researcher.jin の `ref` が指す `research.*` の**テスト用スタブ**。

`research.tools` / `research.guards` は本リポジトリに実体が無い（要件書 §2.2 の例に登場するだけ）。
`jin run` の生成コードは `from research.tools import web_search` を**実際に import する**ので、
テストではこのディレクトリ（`tests/fixtures/stubs`）を `sys.path` / `PYTHONPATH` に載せて供給する。
本物の `jin run` は利用者の cwd / `PYTHONPATH` にある `research.*` を import する
（`docs/spec/adk-mapping.md` §6）。

**ネットワークに出ない・副作用を持たない**こと。ここに import されるだけで何かをするコードを書かない。
"""
