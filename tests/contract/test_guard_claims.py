"""パッケージ横断契約: `guard:` / `hazard:` 記法の安全宣言が実コードと一致すること（R-2 / U-1 / E-B）。

Phase 1 では `packages/jin-cli/tests/test_cli.py` にあり、対象モジュールを手で列挙していた。
Phase 2 で `jin_adk` の 3 モジュールが加わり、jin-cli のパッケージテストが jin_adk を検査する形になって
ADR-003（パッケージテストはそのパッケージ単体）に反したので、ここへ移して **`packages/*/src` を走査し、
記法を含む全モジュールを自動で対象にする**（conventions review F-V-P2-004・列挙漏れの W-03 型も防ぐ）。

記法（`jin_cli/main.py` のモジュール docstring）:

    guard: <関数名> -> <その関数に在るべきトークン>     防御の所在
    hazard: <関数名> -> <その関数に在るべきトークン>    危険な操作の所在（防御ではない・F-S-P2-010）

両タグは同じ規則で照合する（名指しされた関数の**実コード**にトークンが**式として**在ること）。
意味の違いは読み手向け: `guard:` を見て「守られている」と読んでよいのは guard だけ。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "packages"
MAIN_PY = PACKAGES / "jin-cli" / "src" / "jin_cli" / "main.py"

#: `guard: <関数名> -> <トークン>` / `hazard: ...` の記法。
#: 散文の説明行（`guard: <関数名> -> ...`）は `<` で始まるので、この正規表現に当たらない。
CLAIM = re.compile(r"\b(guard|hazard):\s*([A-Za-z_][A-Za-z0-9_]*)\s*->\s*(\S+)")

#: 全モジュール合計で見つかるべき主張の最小件数。走査が壊れて 0 件になると検査が空虚になる。
#: Phase 2 修正ラウンド 1 時点の実測は 30 件超。半分を切ったら走査か記法が壊れている。
MINIMUM_TOTAL_CLAIMS = 15


def source_modules() -> list[Path]:
    return sorted(p for p in PACKAGES.glob("*/src/**/*.py"))


def modules_with_claims() -> list[Path]:
    return [p for p in source_modules() if CLAIM.search(p.read_text(encoding="utf-8"))]


def _function_code_without_docstring(tree: ast.Module, name: str) -> str | None:
    """関数の**実コード**を返す。docstring とコメントは含めない。

    `ast.unparse` はコメントを落とすので、docstring のノードだけ外せば
    「主張の文言そのものを見て通ってしまう」ことが無くなる。メソッドも名前で探す。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return "\n".join(ast.unparse(statement) for statement in body)
    return None


class GuardTokenTooLoose(Exception):
    """`guard:` のトークンが構造を持たず、部分一致でたまたま当たる形（security review U-1 / E-B）。"""


def _guard_satisfied(tree: ast.Module, function_name: str, token: str) -> bool:
    """関数の実コードに `token` が**式として**現れるか（U-1 / E-B）。

    素の部分文字列一致だと `guard: fmt -> os` や `guard: fmt -> path` が素通りする
    （`os` が `diagnostic` の中の "os" に当たる、など。reviewer が実測）。
    AST どうしで突き合わせ、さらに 2 つの縛りを入れる:

    1. トークンが裸の名前（`os` / `path`）なら**主張として認めない**。ガードは属性参照か
       呼び出しであるはず。単なる変数名は「そこに何かがある」以上のことを言っていない
    2. 一致したノードが外側の属性参照の**土台**（`a.b.c` の `a.b`）である場合は数えない。
       部分的な名指しで通してしまうため
    """
    code = _function_code_without_docstring(tree, function_name)
    if code is None:
        return False
    wanted = ast.parse(token, mode="eval").body
    if isinstance(wanted, ast.Name):
        raise GuardTokenTooLoose(
            f"guard: のトークン {token!r} が裸の名前。属性参照か呼び出しで書くこと"
        )
    body = ast.parse(code)
    bases = {id(node.value) for node in ast.walk(body) if isinstance(node, ast.Attribute)}
    target = ast.dump(wanted)
    return any(ast.dump(node) == target and id(node) not in bases for node in ast.walk(body))


def test_the_scan_finds_the_modules_that_carry_claims() -> None:
    """走査が壊れて対象が消えたら気づく（列挙をやめた代わりの網）。

    ファイルは**部分集合**で見る（新しく `guard:` を書いたモジュールが増えるのは正常）。
    一方**パッケージ名の集合は等号**で見る: 新しいパッケージが `guard:` を持つように
    なったのに期待集合へ足し忘れる、を検出する（CLAUDE.md のチェックリスト 8 項目目・
    F-V-P3-102。等号にする前は 8 項目目を消してもどのテストも落ちなかった）。
    """
    found = {p.relative_to(PACKAGES).as_posix() for p in modules_with_claims()}
    assert {
        "jin-cli/src/jin_cli/main.py",
        "jin-adk/src/jin_adk/build.py",
        "jin-adk/src/jin_adk/runtime.py",
        "jin-adk/src/jin_adk/codegen.py",
        "jin-render/src/jin_render/svg.py",
    } <= found, found

    expected_packages = {
        "jin-cli",
        "jin-adk",
        "jin-render",
    }
    assert {name.split("/", 1)[0] for name in found} == expected_packages, sorted(found)

    total = sum(len(CLAIM.findall(p.read_text(encoding="utf-8"))) for p in modules_with_claims())
    assert total >= MINIMUM_TOTAL_CLAIMS, total


@pytest.mark.parametrize(
    "path", modules_with_claims(), ids=lambda p: p.relative_to(PACKAGES).as_posix()
)
def test_guard_claims_point_at_real_guards(path: Path) -> None:
    """R-2: 「どこで symlink を弾いているか」という主張を docstring に書きっぱなしにしない。

    R-2 の欠陥は「`_collect` が弾いている」という**実装と乖離した安全宣言**だった。
    docstring を直すだけでは、次に誰かが同じ種類の嘘を書ける。
    `guard: <関数名> -> <トークン>` の名指し先に、そのトークンが**実コードとして**
    在ることをここで検査する。名指しが嘘なら（あるいは関数が消えたら）落ちる。
    `hazard:` も同じ規則（危険な操作が本当にそこに在ること）。
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    claims = CLAIM.findall(source)
    assert claims, path
    for tag, function_name, token in claims:
        assert _function_code_without_docstring(tree, function_name) is not None, (
            f"{tag}: が存在しない関数 {function_name} を名指ししている"
            "（関数を消したか改名したなら主張も直すこと）"
        )
        assert _guard_satisfied(tree, function_name, token), (
            f"{path.name}: {function_name} に {token} が無いのに {tag}: がそこを名指ししている。"
            "R-2 と同じ「実装と乖離した安全宣言」になっている"
        )


def test_hazard_tags_mark_the_dangerous_operations_not_defenses() -> None:
    """F-S-P2-010 E-C 型: 「危険の所在」は `guard:` ではなく `hazard:` で書く。"""
    tags: dict[str, set[str]] = {}
    for path in modules_with_claims():
        for tag, function_name, token in CLAIM.findall(path.read_text(encoding="utf-8")):
            tags.setdefault(token, set()).add(tag)
    assert tags["importlib.util.spec_from_file_location"] == {"hazard"}
    # DP-IMPL-JIN-P2-SYSPATH-01（再々判断）: sys.path に足すのが危険（hazard）、finally で
    # 取り除くのが防御（guard）。両方が同じ関数（_sys_path_window）に在ることを固定する
    assert tags["sys.path.append"] == {"hazard"}
    assert tags["sys.path.remove"] == {"guard"}
    for token, found in tags.items():
        if token.startswith("sys.path.") and token != "sys.path.remove":
            assert found == {"hazard"}, token
        assert len(found) == 1, f"{token} が guard と hazard の両方で使われている"


def test_guard_claim_check_looks_at_code_not_at_the_claim_itself() -> None:
    """R-2: 主張の文言そのものを見て通る検査だと、嘘を 1 件も検出できない。

    `guard: _write_in_place -> os.O_NOFOLLOW` という**文字列は docstring にも在る**ので、
    関数のソースを丸ごと見ると常に真になる。`_function_code_without_docstring` が
    docstring を落としていることをここで固定する。
    """
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    code = _function_code_without_docstring(tree, "_write_in_place")
    assert code is not None
    assert "guard:" not in code, "docstring が落ちていない（主張の自己参照で通ってしまう）"
    assert "os.O_NOFOLLOW" in code, "実コードのほうの O_NOFOLLOW が見えていない"

    # docstring にしかトークンが無い関数は「ガード無し」と判定されること。
    synthetic = ast.parse('def f():\n    """guard: f -> os.O_NOFOLLOW"""\n    return 1\n')
    assert "O_NOFOLLOW" not in (_function_code_without_docstring(synthetic, "f") or "")


# ---- U-1 / E-B: 緩いトークンが素通りしないこと -----------------------------------------
@pytest.fixture(scope="module")
def main_tree() -> ast.Module:
    return ast.parse(MAIN_PY.read_text(encoding="utf-8"))


@pytest.mark.parametrize("token", ["os", "path", "Path", "text"])
def test_a_bare_name_is_not_accepted_as_a_guard(main_tree: ast.Module, token: str) -> None:
    """U-1 / E-B: `guard: fmt -> os` のような裸の名前は主張として認めない。

    修正前は `token in code` の**素の部分文字列一致**だったので、`os` が `diagnostic` の
    中の "os" に当たって素通りしていた（reviewer が実測）。裸の名前は「そこに何かがある」
    以上のことを言っておらず、ガードの名指しとして意味を成さない。
    """
    with pytest.raises(GuardTokenTooLoose):
        _guard_satisfied(main_tree, "fmt", token)


@pytest.mark.parametrize(
    "token",
    [
        "os.path",  # `os.path.islink(...)` の土台。部分的な名指し
        "shutil.rmtree",  # 実在しない呼び出し
        "os.O_NOFOLLOW",  # `_write_in_place` には在るが `fmt` には無い
    ],
)
def test_a_token_absent_from_the_function_is_rejected(main_tree: ast.Module, token: str) -> None:
    """U-1 / E-B: 構造を持っていても、その関数に無いトークンは通さない。

    `os.path` は `os.path.islink(...)` の土台になっているだけで、それ自体はガードではない。
    外側の属性参照の土台になっているノードは数えない。
    """
    assert not _guard_satisfied(main_tree, "fmt", token)


@pytest.mark.parametrize(
    ("function_name", "token"),
    [
        ("fmt", "path.is_symlink"),
        ("_write_in_place", "os.O_NOFOLLOW"),
        ("_write_atomically", "os.replace"),
        ("_write_atomically", "Path(path).is_symlink"),
    ],
)
def test_a_real_guard_is_accepted(main_tree: ast.Module, function_name: str, token: str) -> None:
    """U-1 / E-B: 締めすぎて本物のガードまで落とさないこと（検査が空虚にならない側の確認）。"""
    assert _guard_satisfied(main_tree, function_name, token)


def test_the_substring_shortcut_would_have_let_a_loose_token_through(main_tree: ast.Module) -> None:
    """U-1 / E-B: 修正前の照合（素の部分文字列一致）なら通っていたことを示す。

    「直したつもりで実は元から通らなかった」を防ぐため、欠陥の存在自体をここで固定する。
    """
    code = _function_code_without_docstring(main_tree, "fmt")
    assert code is not None
    assert "os" in code, "部分文字列一致なら `guard: fmt -> os` が通っていた"
    assert "path" in code, "部分文字列一致なら `guard: fmt -> path` が通っていた"


def test_a_partial_attribute_name_is_not_accepted_as_a_guard() -> None:
    """U-1 / E-B: `a.b.c` の `a.b` だけを名指しした部分的な主張を通さない。

    合成入力で直接固定する（実コードで発火しない縛りは検証できていないのと同じ）。
    """
    tree = ast.parse("def f():\n    return os.path.islink(p)\n")
    assert _guard_satisfied(tree, "f", "os.path.islink")
    assert not _guard_satisfied(tree, "f", "os.path"), "土台だけの名指しが通った"


def test_a_method_can_be_named_by_a_claim() -> None:
    """`guard: _truncate -> os.ftruncate`（`jin_cli.main._LazyTruncateSink` のメソッド）のような名指しが通る。"""
    tree = ast.parse("class C:\n    def m(self):\n        return os.ftruncate(self.fd, 0)\n")
    assert _guard_satisfied(tree, "m", "os.ftruncate")
