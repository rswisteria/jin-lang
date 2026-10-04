"""場面グラフ(`.jinscene.json`)— 認識器と構文解析器の間の唯一の契約。

形は `docs/superpowers/specs/2026-10-03-jin-glyph-design.md` §3.2、正典は `docs/spec/v2/glyph.md` §5。
schema は `schemas/jin-scene.schema.json`(`scripts/generate_schema.py` が生成する。手で編集しない)。
座標は画像の画素(左上が原点)。
"""

from __future__ import annotations

from typing import Any, Literal

from jin_core.schema_export import SCHEMA_DIALECT, serialize
from jin_core.v2.glyph import GLYPH_IDS, START_MARK, STRUCT_MARKS
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

SCENE_SCHEMA_PATH = "schemas/jin-scene.schema.json"
SCENE_SCHEMA_ID = "https://xtone.internal/jin/schemas/jin-scene.schema.json"
#: `t == "struct"` の升の値(構造の印と銘環の始まりの印・S3)
_STRUCT_IDS = frozenset(m.id for m in STRUCT_MARKS) | {START_MARK}


class _Strict(BaseModel):
    """知らない欄を拒む。文字列と整数の欄は `StrictStr` / `StrictInt` で型を変換しない(`"width": "4032"` を通さない・
    #119。モデル全体を strict にすると JSON から読んだ dict の座標の配列が tuple でないと拒まれる)。
    `from` は別名でだけ受ける(`from_` は通さない)。"""

    model_config = ConfigDict(extra="forbid")


class Cell(_Strict):
    """銘帯の 1 升。`t == "glyph"` なら `v` は紋の id(`jin_core.v2.glyph.GLYPH_IDS`)、
    `t == "latin"` なら `v` はちょうど 1 字(1 コードポイント。名前や数は升ごとに 1 字ずつ並ぶ)。"""

    t: Literal["latin", "glyph", "struct"]
    v: StrictStr
    unsure: list[StrictStr] = []
    box: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def _glyph_is_known(self) -> Cell:
        if self.t == "glyph" and self.v not in GLYPH_IDS:
            raise ValueError(f"未知の紋 id です: {self.v!r}")
        if self.t == "struct" and self.v not in _STRUCT_IDS:
            raise ValueError(f"未知の構造の印です: {self.v!r}")
        if self.t == "latin" and len(self.v) != 1:
            raise ValueError(f"ラテン層の升は 1 字(1 コードポイント)です: {self.v!r}")
        return self


class Band(_Strict):
    owner: StrictStr
    cells: list[Cell]


class Figure(_Strict):
    id: StrictStr
    kind: StrictStr
    at: tuple[float, float]
    ring: StrictStr | None = None
    angle: float | None = None


class Line(_Strict):
    from_: StrictStr = Field(alias="from")
    to: StrictStr
    style: Literal["solid", "dashed"]


class ImageInfo(_Strict):
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    width: StrictInt = Field(ge=1)
    height: StrictInt = Field(ge=1)


class JinScene(_Strict):
    jinscene: Literal[1]
    sheet: Literal["S", "M", "free", "full"]  # full = Jin が描いた完全陣(S3 の決定的デコーダ)
    image: ImageInfo
    figures: list[Figure]
    bands: list[Band]
    lines: list[Line] = []

    @field_validator("figures")
    @classmethod
    def _figure_ids_are_unique(cls, figures: list[Figure]) -> list[Figure]:
        seen: set[str] = set()
        for f in figures:
            if f.id in seen:
                raise ValueError(f"図形の id が重複しています: {f.id!r}")
            seen.add(f.id)
        return figures

    @model_validator(mode="after")
    def _references_resolve(self) -> JinScene:
        """線の両端と図形の `ring` は図形の id を指す。銘帯の `owner` は構文解析器が JIN305 で知らせる
        (読み取りの誤りとして利用者に返す)ので、ここでは見ない。"""
        ids = {f.id for f in self.figures}
        for f in self.figures:
            if f.ring is not None and f.ring not in ids:
                raise ValueError(f"図形 {f.id!r} の ring {f.ring!r} が図形にありません")
        for line in self.lines:
            for end in (line.from_, line.to):
                if end not in ids:
                    raise ValueError(f"線の端 {end!r} が図形にありません")
        return self


Box = tuple[float, float, float, float]


def box_of(scene: JinScene, pointer: str) -> Box | None:
    """場面グラフの pointer → 写真の上の矩形(画素)。エディタが診断を写真に重ねるのに使う(陣書き S5・設計書 §3.5)。

    `/bands/i/cells/j…` はその升の `box`、`/bands/i` は升の `box` を全部囲む矩形。それ以外(図形・額縁・
    `box` の無い升・範囲外)は None(位置を推測で埋めない)。
    """
    parts = pointer.split("/")[1:]
    if len(parts) < 2 or parts[0] != "bands" or not parts[1].isdigit():
        return None
    bi = int(parts[1])
    if bi >= len(scene.bands):
        return None
    cells = scene.bands[bi].cells
    if len(parts) == 2:
        boxes = [c.box for c in cells if c.box is not None]
        if not boxes:
            return None
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
    if parts[2] != "cells" or len(parts) < 4 or not parts[3].isdigit():
        return None
    ci = int(parts[3])
    return cells[ci].box if ci < len(cells) else None


def build_scene_schema() -> dict[str, Any]:
    schema = JinScene.model_json_schema(by_alias=True, mode="validation")
    ordered: dict[str, Any] = {"$schema": SCHEMA_DIALECT, "$id": SCENE_SCHEMA_ID}
    ordered.update(schema)
    return ordered


def render_scene_schema() -> str:
    return serialize(build_scene_schema())


__all__ = [
    "SCENE_SCHEMA_ID",
    "SCENE_SCHEMA_PATH",
    "Band",
    "Box",
    "Cell",
    "Figure",
    "ImageInfo",
    "JinScene",
    "Line",
    "box_of",
    "build_scene_schema",
    "render_scene_schema",
]
