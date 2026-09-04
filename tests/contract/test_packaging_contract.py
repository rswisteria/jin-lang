"""パッケージ横断契約: 新しいパッケージを足したときに設定の直し忘れを落とす。

wiring review W-03 / W-05 と conventions review A-1 / A-2 への回答。

`pyproject.toml` はパッケージ名を複数箇所に持つ（`dependencies` / `tool.uv.sources` /
`tool.importlinter.root_packages` / layers 契約 / forbidden 契約）。**列挙を人手で保つ限り
必ずどこかが漏れる**ので、ディスク上の `packages/*/` を正としてすべての列挙を突き合わせる。

漏れたときの失敗は「テストが 1 件も収集されない」「契約が静かに緩む」のように
気づきにくい形で出るため、ここで**名指しの赤**に変える。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = REPO_ROOT / "packages"


def package_dirs() -> list[Path]:
    return sorted(p for p in PACKAGES_DIR.iterdir() if (p / "pyproject.toml").is_file())


def module_name(package_dir: Path) -> str:
    """`packages/jin-core` → `jin_core`。実際に `src/` に存在することも確かめる。"""
    name = package_dir.name.replace("-", "_")
    assert (package_dir / "src" / name).is_dir(), f"{package_dir}/src/{name} が無い"
    return name


def root_config() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


PACKAGE_IDS = [p.name for p in package_dirs()]


def test_at_least_one_package_exists() -> None:
    """列挙が空でも各テストが素通りしてしまわないようにする。"""
    assert len(package_dirs()) >= 2


# --------------------------------------------------------------------------------------
# W-03: testpaths の網羅
# --------------------------------------------------------------------------------------
#: テストを持たないことを**明示的に許した**パッケージ。
#: 空のまま保つこと。ここに載せるときは理由をコメントで残す。
#: `pytest.skip` で素通りさせると、W-03 で塞いだ「新パッケージのテストが CI で走らない」状態へ
#: 別経路（tests/ を作り忘れる）で到達できてしまう（wiring review N-02）。
PACKAGES_WITHOUT_TESTS: frozenset[str] = frozenset()


@pytest.mark.parametrize("package", package_dirs(), ids=PACKAGE_IDS)
def test_every_package_has_tests(package: Path) -> None:
    """N-02: `tests/` を持たないパッケージは skip ではなく**失敗**させる。"""
    if package.name in PACKAGES_WITHOUT_TESTS:
        pytest.skip(f"{package.name} は allowlist でテスト無しを明示的に許可している")
    assert (package / "tests").is_dir(), (
        f"{package.name} に tests/ が無い。テストを書くか、"
        "理由つきで PACKAGES_WITHOUT_TESTS へ明示的に載せること"
    )


def test_the_allowlist_is_empty() -> None:
    """N-02: 免除の門を**見える形**にしておく。

    `PACKAGES_WITHOUT_TESTS` に名前を足すと上の 3 本が `pytest.skip` で素通りする。
    それ自体が N-02 の指摘した「skip 素通り」の再来なので、足すときはこのテストも直させる。
    直すときは、なぜそのパッケージがテストを持たなくてよいのかをここに書くこと。
    """
    assert PACKAGES_WITHOUT_TESTS == frozenset(), (
        "テスト無しを許したパッケージがある。理由をこの docstring に明記してから"
        f"この assert を更新すること: {sorted(PACKAGES_WITHOUT_TESTS)}"
    )


def test_the_allowlist_has_no_dead_entries() -> None:
    """N-02: allowlist に残った死んだ名前を落とす（許可が実態から離れないように）。"""
    existing = {p.name for p in package_dirs()}
    assert PACKAGES_WITHOUT_TESTS <= existing, (
        f"存在しないパッケージが allowlist にある: {PACKAGES_WITHOUT_TESTS - existing}"
    )


@pytest.mark.parametrize("package", package_dirs(), ids=PACKAGE_IDS)
def test_every_package_test_directory_is_collected(package: Path) -> None:
    """W-03: `testpaths` にパッケージ名を列挙すると新しいテストが静かに収集されない。

    `packages/<name>/tests/` が `testpaths` のどれかに含まれることを確かめる。
    """
    tests_dir = package / "tests"
    if package.name in PACKAGES_WITHOUT_TESTS:
        pytest.skip(f"{package.name} は allowlist でテスト無しを明示的に許可している")
    assert tests_dir.is_dir(), (
        f"{package.name} に tests/ が無い（test_every_package_has_tests を参照）"
    )
    testpaths = [
        (REPO_ROOT / entry).resolve()
        for entry in root_config()["tool"]["pytest"]["ini_options"]["testpaths"]
    ]
    resolved = tests_dir.resolve()
    assert any(resolved == entry or entry in resolved.parents for entry in testpaths), (
        f"{tests_dir} が testpaths に含まれていない。pyproject.toml の "
        "[tool.pytest.ini_options].testpaths を直すこと"
    )


@pytest.mark.parametrize("package", package_dirs(), ids=PACKAGE_IDS)
def test_every_package_test_directory_is_a_package(package: Path) -> None:
    """conventions review A-1: `__init__.py` が無いと同名テストで collection 全体が止まる。"""
    tests_dir = package / "tests"
    if package.name in PACKAGES_WITHOUT_TESTS:
        pytest.skip(f"{package.name} は allowlist でテスト無しを明示的に許可している")
    assert tests_dir.is_dir(), (
        f"{package.name} に tests/ が無い（test_every_package_has_tests を参照）"
    )
    assert (tests_dir / "__init__.py").is_file(), (
        f"{tests_dir}/__init__.py が無い。別パッケージに同名のテストファイルができると "
        "`import file mismatch` でスイート全体が Interrupted になる"
    )


def test_import_mode_is_importlib() -> None:
    """A-1 の二重の網。`__init__.py` を消しても同名衝突で全滅しないようにする設定。"""
    addopts = root_config()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--import-mode=importlib" in addopts


# --------------------------------------------------------------------------------------
# W-03 / W-05: import-linter の網羅
# --------------------------------------------------------------------------------------
def importlinter_section() -> dict:
    return root_config()["tool"]["importlinter"]


@pytest.mark.parametrize("package", package_dirs(), ids=PACKAGE_IDS)
def test_every_package_is_a_root_package(package: Path) -> None:
    """W-03: `root_packages` に載っていないパッケージは契約の対象外になる。"""
    assert module_name(package) in importlinter_section()["root_packages"]


@pytest.mark.parametrize("package", package_dirs(), ids=PACKAGE_IDS)
def test_every_package_appears_in_the_layers_contract(package: Path) -> None:
    """W-05: 層に載せ忘れたパッケージは、どちら向きの依存も静かに許される。

    兄弟は `"jin_adk | jin_render"` のように 1 要素へ `|` 区切りで並べる。
    """
    layers = next(
        contract for contract in importlinter_section()["contracts"] if contract["type"] == "layers"
    )["layers"]
    declared = {name.strip() for layer in layers for name in layer.split("|")}
    assert module_name(package) in declared, (
        f"{module_name(package)} が layers 契約に無い。pyproject.toml の layers を直すこと"
    )


def test_resolver_isolation_contract_covers_every_package_but_the_cli() -> None:
    """security review S1: `ref` の import 実装は `jin_cli` にだけ置く。

    新しい root package（Phase 4 の `jin_lsp` など）を足したときに
    `source_modules` へ足し忘れると、ws で外に出るサーバから任意コード実行へ到達できてしまう。
    """
    section = importlinter_section()
    contract = next(
        c for c in section["contracts"] if "jin_cli.resolver" in c.get("forbidden_modules", [])
    )
    expected = set(section["root_packages"]) - {"jin_cli"}
    assert set(contract["source_modules"]) >= expected, (
        f"resolver 隔離契約の source_modules に {expected - set(contract['source_modules'])} が無い"
    )


def test_the_only_module_importing_importlib_is_the_cli_resolver() -> None:
    """S1 の生の検査（import-linter を差し替えても残る網）。

    このテストが守っているのは「``.jin`` の ``ref`` を解決するために任意モジュールを
    import する実装が ``jin_cli`` の resolver 1 箇所に閉じている」ことであって、
    「importlib を使う場所が 1 箇所しかない」ことではない。

    **Phase 2 で赤くなるのは想定どおり**: 要件書 §3.4 が ``jin run`` を「生成コードを
    一時ディレクトリに書き出して import」と定めているため、``jin_adk`` は importlib を
    使う。そのときは ``expected`` に ``packages/jin-adk/src/jin_adk/<module>.py`` を
    **足して通すのが正しい**。

    やってはいけない修正:

    - ``jin_adk`` の import を ``jin_cli`` 経由に回す（依存方向の逆転。
      ``jin-core ← jin-adk`` の一方向性を壊す）
    - このテストごと削除する / アサーションを ``>=`` に緩める

    ``jin_lsp`` と ``jin_core`` は Phase 4 以降も **足してはならない**。
    ws トランスポートから ``ref`` 解決へ到達させないという S1 の構造的な担保
    （ADR 参照 / import-linter の「ref の解決実装（任意コード実行）は jin_cli に閉じる」
    契約）が、この 2 つを追加した時点で崩れる。
    """
    offenders = []
    for package in package_dirs():
        module = module_name(package)
        for path in sorted((package / "src" / module).rglob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith(("import importlib", "from importlib")):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == ["packages/jin-cli/src/jin_cli/resolver.py"]


# --------------------------------------------------------------------------------------
# W-03: ワークスペース宣言の網羅
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("package", package_dirs(), ids=PACKAGE_IDS)
def test_every_package_is_declared_in_the_workspace(package: Path) -> None:
    config = root_config()
    name = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "name"
    ]
    assert name in config["project"]["dependencies"]
    assert name in config["tool"]["uv"]["sources"]


# --------------------------------------------------------------------------------------
# W-08: テスト側と CLI 側の `.jin` 探索規則が一致する
# --------------------------------------------------------------------------------------
def test_test_fixtures_and_cli_discover_the_same_files(tmp_path: Path) -> None:
    """W-08: `conftest` が `glob("*/*.jin")` だと深さ 3 以上の `.jin` を静かに落とす。

    深さ 1 / 2 / 3 を含むツリーを作り、テスト側の探索関数と CLI の収集が一致することを見る。
    実物の `examples/` は今のところ深さ 2 しか無いので、実物だけでは差が出ない。
    """
    from jin_cli.main import _collect

    from tests.conftest import discover_jin_files

    (tmp_path / "top.jin").write_text("{}", encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "mid.jin").write_text("{}", encoding="utf-8")
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "deep.jin").write_text("{}", encoding="utf-8")

    discovered = discover_jin_files(tmp_path)
    assert [p.name for p in discovered] == ["deep.jin", "mid.jin", "top.jin"]
    assert discovered == _collect([tmp_path])


# --------------------------------------------------------------------------------------
# CONV A-2 / CONV A-3: パッケージ追加時のチェックリストが CLAUDE.md にある
# --------------------------------------------------------------------------------------
def test_claude_md_has_the_package_addition_checklist() -> None:
    """conventions review A-2: パッケージ名が pyproject.toml の 5 箇所にハードコードされている。

    このテストが見るのは「チェックリストが書いてあるか」だけで、抜けの検出は
    上の各契約テストが行う。A-3（トリップワイヤの docstring）もここを指している。
    """
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "パッケージを足すときのチェックリスト" in text
    for item in [
        "[project].dependencies",
        "[tool.uv.sources]",
        "root_packages",
        "layers",
        "source_modules",
        "__init__.py",
    ]:
        assert item in text, f"チェックリストに {item} が無い"


def test_the_tripwire_points_at_the_checklist() -> None:
    """conventions review A-3: Phase 2 の実装者が「テストが 1 件も走らない」状態から始めないよう誘導する。"""
    source = (REPO_ROOT / "tests" / "contract" / "test_dependency_direction.py").read_text(
        encoding="utf-8"
    )
    assert "パッケージを足すときのチェックリスト" in source
    assert "test_packaging_contract.py" in source


# --------------------------------------------------------------------------------------
# W-05 残件: 兄弟パッケージの同居（design.yaml の契約を正本として読む）
# --------------------------------------------------------------------------------------
DESIGN_YAML = REPO_ROOT / "delivery" / "20260904-1445-jin" / "design.yaml"

#: design.yaml の 1 行ルールから拾う Python パッケージ名。
_PACKAGE_TOKEN = re.compile(r"jin-[a-z]+")


def dependency_rules() -> list[str]:
    """design.yaml `architecture.dependency_direction.rules` の行を返す。

    PyYAML を依存に足さずに済むよう、該当ブロックだけを行単位で読む
    （契約の正本は design.yaml のこの 8 行・ADR-004 / CLAUDE.md）。
    """
    lines = DESIGN_YAML.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "rules:")
    rules: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("- "):
            rules.append(stripped[2:])
            continue
        if stripped and not stripped.startswith("- "):
            break
    assert rules, "design.yaml から dependency_direction.rules を読めなかった"
    return rules


def forbidden_edges(rules: list[str]) -> set[tuple[str, str]]:
    """「X は … Y に依存しない」から禁止辺 (X, Y) を集める。

    `jin-core は他の jin-* パッケージに依存しない` の `jin-*` は具体名ではないので拾わない
    （`jin-[a-z]+` に `*` は一致しない）。
    """
    edges: set[tuple[str, str]] = set()
    for rule in rules:
        subject_part, _, _ = rule.partition(" は ")
        subject = _PACKAGE_TOKEN.search(subject_part)
        if subject is None:
            continue
        for clause in rule.split("。"):
            if "に依存しない" not in clause:
                continue
            head = clause.split("に依存しない", 1)[0]
            for target in _PACKAGE_TOKEN.findall(head):
                if target != subject.group(0):
                    edges.add((subject.group(0), target))
    return edges


def mutually_independent_pairs(rules: list[str]) -> set[frozenset[str]]:
    """双方向に「依存しない」と宣言されたペア（= 兄弟。層で上下を付けてはいけない）。"""
    edges = forbidden_edges(rules)
    pairs: set[frozenset[str]] = set()
    for source, target in edges:
        if (target, source) in edges:
            pairs.add(frozenset({source.replace("-", "_"), target.replace("-", "_")}))
    return pairs


def independence_violations(
    pairs: set[frozenset[str]], layers: list[str]
) -> list[tuple[frozenset[str], str]]:
    """兄弟ペアが `layers` の**同一要素**に `|` で並んでいないものを返す。

    `layers` の要素をフラットな集合に潰すと「登場するか」しか見えず、
    素朴な直列（`[jin_cli, jin_adk, jin_render, jin_core]`）でも全緑になる（wiring review W-05）。
    素朴な直列は `jin_render → jin_adk` だけを禁じ、`jin_adk → jin_render` を**静かに許す**。
    """
    element_of: dict[str, int] = {}
    for index, layer in enumerate(layers):
        for name in layer.split("|"):
            element_of[name.strip()] = index
    violations: list[tuple[frozenset[str], str]] = []
    for pair in sorted(pairs, key=sorted):
        indexes = {element_of[name] for name in pair if name in element_of}
        if len(indexes) < 2:
            continue  # 片方しか宣言に無い（まだ存在しないパッケージ）か、同居している
        violations.append(
            (pair, f"{sorted(pair)} が別々の layer 要素にある（'A | B' と 1 要素に並べること）")
        )
    return violations


def layers_contract() -> list[str]:
    return next(c for c in importlinter_section()["contracts"] if c["type"] == "layers")["layers"]


def test_design_yaml_declares_exactly_one_sibling_pair() -> None:
    """W-05: パーサの出力そのものを固定する（「空でない」だけだと壊れても気づけない）。

    design.yaml のルール 3 / 4 が jin-adk と jin-render を相互に「依存しない」と宣言している。
    """
    pairs = mutually_independent_pairs(dependency_rules())
    assert pairs == {frozenset({"jin_adk", "jin_render"})}, pairs


def test_layers_contract_keeps_sibling_packages_in_one_element() -> None:
    """W-05: 兄弟に上下を付けた層宣言を落とす（実契約に対する検査）。

    jin_adk / jin_render は Phase 2〜3 で追加される。追加時にこのテストが
    素朴な直列を拒む。
    """
    violations = independence_violations(
        mutually_independent_pairs(dependency_rules()), layers_contract()
    )
    assert violations == [], violations


def test_independence_check_rejects_a_naive_serial_layout() -> None:
    """W-05: 上の検査が**実際に落ちる**ことを、reviewer が実測した 2 つの層宣言で固定する。

    - `["jin_cli", "jin_lsp", "jin_adk | jin_render", "jin_core"]`
      → 両方向を BROKEN にする（`|` 構文は正しく効く・reviewer 実測）
    - `["jin_cli", "jin_adk", "jin_render", "jin_core"]`
      → `jin_adk → jin_render` を静かに許す
    """
    pairs = mutually_independent_pairs(dependency_rules())
    good = ["jin_cli", "jin_lsp", "jin_adk | jin_render", "jin_core"]
    naive = ["jin_cli", "jin_adk", "jin_render", "jin_core"]
    assert independence_violations(pairs, good) == []
    bad = independence_violations(pairs, naive)
    assert len(bad) == 1
    assert bad[0][0] == frozenset({"jin_adk", "jin_render"})


def test_forbidden_edges_ignore_the_wildcard_rule() -> None:
    """W-05: `jin-core は他の jin-* パッケージに依存しない` の `jin-*` を具体名と誤読しないこと。"""
    edges = forbidden_edges(["jin-core は他の jin-* パッケージに依存しない（最下層）"])
    assert edges == set(), edges
