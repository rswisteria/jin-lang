"""場面グラフ(`.jinscene.json`)— 認識器と構文解析器の間の唯一の契約。

形は `docs/superpowers/specs/2026-10-03-jin-glyph-design.md` §3.2、正典は `docs/spec/v2/glyph.md` §5。
schema は `schemas/jin-scene.schema.json`(`scripts/generate_schema.py` が生成する。手で編集しない)。
座標は画像の画素(左上が原点)。
"""

from __future__ import annotations

from typing import Any, Literal

from jin_core.schema_export import SCHEMA_DIALECT, serialize
from jin_core.v2.glyph import GLYPH_IDS
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCENE_SCHEMA_PATH = "schemas/jin-scene.schema.json"
SCENE_SCHEMA_ID = "https://xtone.internal/jin/schemas/jin-scene.schema.json"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Cell(_Strict):
    """銘帯の 1 升。`t == "glyph"` なら `v` は紋の id(`jin_core.v2.glyph.GLYPH_IDS`)。"""

    t: Literal["latin", "glyph"]
    v: str
    unsure: list[str] = []
    box: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def _glyph_is_known(self) -> Cell:
        if self.t == "glyph" and self.v not in GLYPH_IDS:
            raise ValueError(f"未知の紋 id です: {self.v!r}")
        return self


class Band(_Strict):
    owner: str
    cells: list[Cell]


class Figure(_Strict):
    id: str
    kind: str
    at: tuple[float, float]
    ring: str | None = None
    angle: float | None = None


class Line(_Strict):
    from_: str = Field(alias="from")
    to: str
    style: Literal["solid", "dashed"]


class ImageInfo(_Strict):
    sha256: str
    width: int
    height: int


class JinScene(_Strict):
    jinscene: Literal[1]
    sheet: Literal["S", "M", "free"]
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
    "Cell",
    "Figure",
    "ImageInfo",
    "JinScene",
    "Line",
    "build_scene_schema",
    "render_scene_schema",
]
