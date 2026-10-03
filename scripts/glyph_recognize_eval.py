"""Claude 認識器の手動評価(陣書き S4・設計書 §5「撮影の評価セット」・S0 の合格線)。**本物の API を叩く。CI では回さない。**

型紙に手で描いた陣の写真を `jin_glyph.recognize.recognize_photo` で読み、正解の `.jin` と比べて
「手直しの升数」(持ち主ごとの銘帯の升の列の編集距離の和)と、その升数に対する割合を出す(合格線は 2%・設計書 §9 #17)。

    uv run python scripts/glyph_recognize_eval.py --photo fib.jpg --expect examples-v2/fib/fib.jin
    uv run python scripts/glyph_recognize_eval.py --photo fib.jpg --expect examples-v2/fib/fib.jin --record /tmp/rec

- `--record DIR` は Messages API の生の応答を `DIR/00-align.json`・`01-cells.json`… に書く(`tests/fixtures/recognize/` と同じ形。
  本物の録画に差し替えるときに使う)
- `--scene OUT` は読んだ場面グラフを書く(手で直して `jin check OUT` に掛けられる)
- 認証は SDK の既定の解決順(`ANTHROPIC_API_KEY` ほか)。写真と升の画像を Anthropic の API に送る
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anthropic
import httpx2
from jin_core.canonical import dumps
from jin_core.check import check_file
from jin_core.v2.glyph import START_MARK
from jin_core.v2.model import JinFileV2
from jin_glyph.parse import parse_scene
from jin_glyph.recognize import Recognizer, recognize_photo
from jin_render.v2.inscribe import circle_ring, frame_band, rite_ring


def expected_bands(model: JinFileV2) -> dict[str, list[tuple[str, str]]]:
    """持ち主の id → 正解の銘帯の升(場面グラフと同じく、環は頭に始まりの印・継ぎの紋なし)。"""
    names = [c.name for c in model.circles]
    root = names.index(model.root) if model.root in names else 0
    order = [root] + [ci for ci in range(len(model.circles)) if ci != root]
    start = [("struct", START_MARK)]
    out = {"frame": [(c.t, c.v) for c in frame_band(model)]}
    for k, ci in enumerate(order):
        out[f"c{k}"] = start + [(c.t, c.v) for c in circle_ring(model, ci)]
        for j in range(len(model.circles[ci].rites)):
            out[f"r{k}_{j}"] = start + [(c.t, c.v) for c in rite_ring(model, ci, j)]
    return out


def edit_distance(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, start=1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def recording_client(directory: Path) -> anthropic.Anthropic:
    directory.mkdir(parents=True, exist_ok=True)
    count = [0]

    def save(response: httpx2.Response) -> None:
        response.read()
        name = "align" if count[0] == 0 else "cells"
        path = directory / f"{count[0]:02d}-{name}.json"
        body = json.loads(response.content)
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        count[0] += 1

    return anthropic.Anthropic(
        http_client=anthropic.DefaultHttpxClient(event_hooks={"response": [save]})
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--expect", type=Path, required=True, help="正解の .jin")
    parser.add_argument("--record", type=Path, help="生の応答を書くディレクトリ")
    parser.add_argument("--scene", type=Path, help="読んだ場面グラフの書き先")
    args = parser.parse_args()

    model = check_file(args.expect).model
    if not isinstance(model, JinFileV2):
        print(f"{args.expect}: v2 の .jin ではありません", file=sys.stderr)
        return 2
    client = recording_client(args.record) if args.record else None
    scene = recognize_photo(args.photo.read_bytes(), recognizer=Recognizer(client=client))
    if args.scene:
        payload = scene.model_dump(mode="json", by_alias=True, exclude_defaults=True)
        args.scene.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    want = expected_bands(model)
    got = {band.owner: [(c.t, c.v) for c in band.cells] for band in scene.bands}
    total = sum(len(cells) for cells in want.values())
    fixes = 0
    for owner in sorted(set(want) | set(got)):
        distance = edit_distance(want.get(owner, []), got.get(owner, []))
        fixes += distance
        print(
            f"{owner}: 正解 {len(want.get(owner, []))} 升・読み {len(got.get(owner, []))} 升・手直し {distance}"
        )
    unsure = sum(1 for band in scene.bands for c in band.cells if c.unsure)
    print(
        f"手直し {fixes} / {total} 升 = {100.0 * fixes / max(total, 1):.2f}%(合格線 2%)・迷い {unsure} 升"
    )
    parsed, diagnostics = parse_scene(scene, file=str(args.scene or "scene"))
    for d in diagnostics:
        print(f"  {d.severity} {d.code} {d.pointer}: {d.message}")
    same = parsed is not None and dumps(parsed) == dumps(model)
    print("往復:", "正解の .jin とバイト一致" if same else "一致しない")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
