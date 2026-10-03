# Claude 認識器の応答の fixture(陣書き S4)

`fib-S.synthetic/` は、型紙 S に fib を書いた写真(`tests/glyph_photo.py` の `synthetic_photo` が手本から作る)
に対する Messages API の応答(生の JSON)。`00-align.json` が位置合わせ、`01-cells.json` 以降が升の読み(60 升ずつ)。

**本物の API の録画ではない。** 2026-10-03 の実装時に API キーが無かったので、正解(`jin_render.v2.sheet_layout.fill_sheet`)から
`glyph_photo.synthetic_responses` で合成した。形は Messages API の応答(空の thinking ブロック + 構造化出力の text ブロック・
`stop_reason` / `stop_details` / `usage`)に合わせてあり、テストは `httpx2.MockTransport` で返して SDK の `beta.messages.parse` の
経路をそのまま通す。護符の位置は正解から 0.25 升ずらし、順番も入れ替えてある(認識器の詰め直しと並べ替えを通すため)。

- 生成器とずれたら `UPDATE_RECORDINGS=1 uv run pytest packages/jin-glyph/tests/test_recognize.py -k recorded` で書き直す
- 本物の写真で API を叩いて応答を残すのは `scripts/glyph_recognize_eval.py --record <dir>`(手動・要 API キー・CI では回さない)
