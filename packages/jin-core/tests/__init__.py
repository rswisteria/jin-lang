"""パッケージ内テストのパッケージ宣言。

**これが無いと、別パッケージに同名のテストファイル（例: `test_model.py`）が現れた瞬間に
`import file mismatch` でスイート全体が `Interrupted` になる**（conventions review A-1）。
新しい `packages/<name>/tests/` を作るときは必ず同じものを置くこと。
"""
