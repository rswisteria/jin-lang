# k6x8（`canvas.text` の ASCII 以外の字形の原本）

`apps/player/src/glyphs.ts` はこのディレクトリの `k6x8_gothic.bdf` から
`uv run python scripts/generate_glyphs.py` で生成する（手で編集しない）。
正典は `docs/spec/v2/abilities.md` §2 と設計書 §11 #49。

| 項目 | 値 |
|---|---|
| 書体 | k6x8ゴシック（6×8 ドット・JIS 第一・第二水準） |
| 作者 | 門真 なむ（Num Kadoma）・Copyright (C) 2000-2023 Num Kadoma |
| 版 | 2023-10-19 |
| 出典 | https://littlelimit.net/k6x8.htm の `k6x8_bdf_2023-10-19.zip`（sha256 `12a30719acfd52da071cc98733c0fb758acb46f2523b499b8e315a7d772d0465`） |
| 原本 | `k6x8_gothic.bdf`（zip の中身を改変せずに置いた。sha256 `b9029fa0dd93738c23e55b79ffb1f4445f51a57d09f2f9436b2c4d5ee6fe0590`） |
| ライセンス | `k6x8.txt`（zip 同梱の原文）の「ライセンス」節 |

ライセンス（`k6x8.txt` より）:

> These fonts are free software.
> Unlimited permission is granted to use, copy, and distribute them, with or without modification, either commercially or noncommercially.
> THESE FONTS ARE PROVIDED "AS IS" WITHOUT WARRANTY.

版を上げるときは zip を取り直してこの表の digest を書き換え、生成スクリプトの `BDF_SHA256` も直す
（`tests/contract/test_player_contract.py` が README・生成物・原本の digest を突き合わせる）。
