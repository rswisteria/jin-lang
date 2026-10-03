# Claude 認識器の API の実測(陣書き S4)

2026-10-03。`jin_glyph.recognize` が使う `anthropic` SDK の呼び方を、記憶ではなく手元の版で確かめた記録。
**API の往復は未実測**(実装時に API キーも `ant auth` のプロファイルも無かった)。下の「未実測」を、キーが揃ったら
`scripts/glyph_recognize_eval.py --record` で埋める。

## 版

- `anthropic` **1.11.0**(`uv add --package jin-glyph anthropic` で入った版。HTTP は `httpx2` 2.13.1)
- Python 3.14.7(uv の venv)

## 実測したこと(手元の SDK の型と挙動)

| 項目 | 結果 | 確かめ方 |
|---|---|---|
| `client.beta.messages.parse` の引数 | `fallbacks` / `output_format` / `output_config` / `betas` / `thinking` / `cache_control` を受ける | `inspect.signature(anthropic.resources.beta.messages.Messages.parse)` |
| `fallbacks` の型 | `Union[Iterable[BetaFallbackParam], Literal["default"]]` | `anthropic/types/beta/beta_fallbacks_param.py` |
| `fallbacks: "default"` の beta | `server-side-fallback-2026-07-01`(配列の形は `-2026-06-01`。取り違えると 400) | claude-api スキルの model-migration.md |
| `output_format=<Pydantic>` | 戻りは `ParsedBetaMessage[T]`。`parsed_output` は content の最初の text ブロックの検証済みの値(無ければ None) | `anthropic/types/beta/parsed_beta_message.py` |
| 構造化出力の要求の形 | `output_config.format.type == "json_schema"`(SDK が Pydantic から作る)。`effort` は同じ `output_config` に並ぶ | MockTransport で受けた本文(`test_the_requests_use_opus_with_default_fallbacks_and_structured_output`) |
| `system` に画像を置けるか | **置けない**(`Union[str, Iterable[BetaTextBlockParam]]`)。字形表の画像は最初の user の先頭に `cache_control` 付きで置く | `anthropic/types/beta/message_create_params.py` |
| 認証情報が無いとき | 構築は通り、**送る前に** `TypeError("Could not resolve authentication method…")`。`AnthropicError` ではない | `env -u ANTHROPIC_API_KEY uv run jin check x.jpg` |
| テストでの差し替え | `anthropic.Anthropic(api_key=…, max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(h)))`。`DefaultHttpxClient` は `httpx2.Client` | `anthropic/_base_client.py` |
| 401 の応答 | `anthropic.AuthenticationError` | MockTransport で 401 を返すテスト |
| numpy | 入っていない(射影変換の 8 元連立は純 Python で解く) | `site-packages` の一覧 |

## 決めた値

- モデル `claude-opus-5-5`・`fallbacks: "default"`・`output_config.effort: "medium"`(Opus 5.5 の既定と同じ値を明示)・thinking は省略(5.5 は常に adaptive)
- `max_tokens` 16000(非ストリーミングの目安。升 60 個の読みは数千トークン)
- `stop_reason` は `refusal`(`stop_details.category` を文に出す)と `max_tokens` を失敗にする
- 位置合わせの写真は長辺 1568 px の JPEG。座標は**幅・高さに対する比**で受ける(API 側でさらに縮められても狂わない)。
  受けた位置は護符の中の塗りの重心で詰め直す(Claude の座標は升の数分の 1 ずれうる前提)

## 未実測(キーが揃ったら埋める)

- 本物の応答で `parsed_output` が取れること(thinking ブロックが先に来る形を含む)・`usage.cache_read_input_tokens` で字形表の
  キャッシュが効くこと(字形表 + system が最小のキャッシュ長に届くか)
- 位置合わせの座標の精度(護符の詰め直しの窓 ±1 升に入るか)・升の読みの正解率(S0 の合格線 2%)
- 1 要求に升の画像 60 枚 + 字形表を載せて受け付けられること(画像の枚数の上限)
