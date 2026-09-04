"""`jin-adk` のテストが共有する fixture。

## なぜ `tests/` の**外**に置くのか（踏んだ罠。Phase 3 以降も同じ）

`packages/jin-adk/tests/conftest.py` に置くと、**スイート全体が collection error で止まる**。

```
ValueError: Plugin already registered under a different name:
  packages/jin-adk/tests/conftest.py=<module 'tests.conftest' from 'tests/conftest.py'>
```

`packages/*/tests/__init__.py` は必須（conventions review A-1）なので、
`packages/jin-adk/tests/` の Python 上の名前は `tests` になる。リポジトリ直下の
`tests/` も同じ `tests` なので、`consider_namespace_packages = true` の下では
どちらの `conftest.py` も `tests.conftest` に解決され、2 つ目の登録で落ちる。

`packages/jin-adk/` には `__init__.py` が無いので、ここに置いた `conftest.py` は
素の `conftest` として登録され、衝突しない。**この配置は
`tests/contract/test_packaging_contract.py::test_no_package_puts_conftest_inside_its_tests_package`
が機械で固定する**（`tests/` の中へ戻すと名指しで落ちる）。

同じ理由で、テストモジュールから `from .conftest import ...` のような相対 import も
してはいけない（`tests` パッケージがどちらを指すかが収集順で変わる）。
共有したいものは**すべて fixture として渡す**。

## `.pyc` の罠（Phase 0+1 の申し送り §8-3）

生成モジュールを一時ディレクトリへ書いて import するので、同名モジュールの
バイトコードが残ると**前回の内容で実行される**（無効化判定が「mtime 秒 + サイズ」
なので、同じ秒に同じサイズのものを書くと素通りする）。書かせないようにする。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from jin_core.check import check_file
from jin_core.model import JinFile

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"

#: examples の `.jin`。パラメータ化の ID にファイル名（拡張子なし）を使う。
EXAMPLE_PATHS = sorted(EXAMPLES.rglob("*.jin"))
EXAMPLE_IDS = [path.stem for path in EXAMPLE_PATHS]


@pytest.fixture(autouse=True, scope="session")
def _no_bytecode() -> None:
    """生成モジュールの `.pyc` を作らせない（上の docstring の理由）。"""
    sys.dont_write_bytecode = True


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(params=EXAMPLE_PATHS, ids=EXAMPLE_IDS)
def example_path(request: pytest.FixtureRequest) -> Path:
    return request.param


@pytest.fixture
def load_jin() -> Callable[[Path], JinFile]:
    """`.jin` を意味モデルにする。診断が通らないものはテストの前提が壊れている。"""

    def load(path: Path) -> JinFile:
        result = check_file(path)
        assert result.model is not None, f"{path} がモデルにならない: {result.diagnostics}"
        return result.model

    return load


@pytest.fixture
def example_model(example_path: Path, load_jin: Callable[[Path], JinFile]) -> JinFile:
    return load_jin(example_path)


@pytest.fixture
def write_jin() -> Callable[[Path, str, dict], Path]:
    """テスト用の `.jin` を書いて、そのパスを返す。"""

    def write(directory: Path, name: str, payload: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    return write


@pytest.fixture
def minimal_jin() -> Callable[..., dict]:
    """最小の `.jin`。必要なところだけ差し替えて使う。"""

    def minimal(**overrides: object) -> dict:
        payload: dict = {
            "$schema": "https://xtone.internal/jin/schemas/jin.schema.json",
            "version": 1,
            "root": "Root",
            "circles": [
                {
                    "name": "Root",
                    "core": "gemini-2.5-flash",
                    "instruction": {"rune": "こんにちは"},
                }
            ],
        }
        payload.update(overrides)
        return payload

    return minimal
