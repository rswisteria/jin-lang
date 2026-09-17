"""鑑賞ページ（Jin v2.1・`apps/stage`）の防御を 1 つずつ壊し、赤くなることを実測する。

`phase6-mutations/mutate_p6.py` と同じ流儀（隔離コピー・`node_modules` は symlink・
判定は `returncode != 0` + 失敗の印）。補助関数もそちらから引き写している。
pnpm は `apps/stage` と `apps/editor` の両方で回すので、検査は `("pnpm", (アプリ, スクリプト))` で持つ。

**e2e（Playwright）は回さない。** 理由は Phase 6 と同じで、隔離コピーには `dist` が無く、
エディタの e2e はコピー側の root で `uv run jin editor` を起こすため `.venv` の再作成に落ちる。
したがって「書き出したファイルが読み戻せる」「エディタの鑑賞モードに行が届く」は
**この表では守られていない**（Playwright だけが見張っている）。

同じ理由で `tests/contract/test_stage_contract.py::test_the_svg_fixture_is_what_the_renderer_draws_today`
も外す（コピー側で `uv run jin render` を起こす）。このスクリプトはレンダラを壊さないので失うものは無い。

実行: `uv run python delivery/20260904-1445-jin/stage-mutations/mutate_stage.py`
      `MUTATE_ONLY=NAME1,NAME2 uv run python ...` で一部だけ回す
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN_TIMEOUT_SECONDS = 600

COPY_ITEMS = [
    "packages",
    "tests",
    "examples",
    "examples-v2",
    "plugins",
    "scripts",
    "docs",
    "schemas",
    "delivery",
    "apps",
    "jin-requirements.md",
    "pyproject.toml",
    ".python-version",
    ".github",
]

#: `node_modules` を実ツリーから symlink するアプリ。
PNPM_APPS = ("apps/stage", "apps/editor")

LAYERS = "apps/stage/src/layers.ts"
SCENE = "apps/stage/src/scene.ts"
EFFECTS = "apps/stage/src/effects.ts"
NAMES = "apps/stage/src/names.ts"
MESSAGES = "apps/stage/src/messages.ts"
GLOW = "apps/stage/src/render/glowView.ts"
EXPORTER = "apps/stage/src/exporter.ts"
PANEL = "apps/editor/src/stage/StagePanel.tsx"
EDITOR_PY = "packages/jin-cli/src/jin_cli/editor.py"

T_STAGE_CONTRACT = "tests/contract/test_stage_contract.py"
T_STAGE_SPEC = "tests/spec/test_stage_spec_consistency.py"
T_EDITOR_PY = "packages/jin-cli/tests/test_editor.py"

#: コピー側で `uv run` を起こすテスト（上の docstring）。
DESELECT = [f"{T_STAGE_CONTRACT}::test_the_svg_fixture_is_what_the_renderer_draws_today"]

#: (名前, 対象ファイル, before, after, 検査)
#: 検査は ("py", [pytest 引数]) か ("pnpm", (アプリのディレクトリ, スクリプト名))
MUTATIONS: list[tuple[str, str, str, str, tuple[str, object]]] = [
    (
        # 座標を stage 側で決め始める（viewBox を見ずに 400 px を単位にする）。
        # paddle の viewBox（1000）ではたまたま同じ値なので、別の大きさの viewBox を見るテストだけが拾う。
        "SCENE-computes-its-own-unit",
        SCENE,
        "const scale = width / 2 / HALF_EXTENT;",
        "const scale = 400;",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 層の表が stage.md から離れる。
        "LAYERS-drift-from-the-spec",
        LAYERS,
        "\tsigil: 3,\n",
        "\tsigil: 2,\n",
        ("py", [T_STAGE_CONTRACT]),
    ),
    (
        # 慣れの規則を外す（毎 tick 光りっぱなし）。
        "EFFECTS-no-habituation",
        EFFECTS,
        "count >= HABIT_AFTER",
        "count >= Number.POSITIVE_INFINITY",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 高さに陣の単位を掛けない（入れ子の小陣が幅と同じ高さの塔になる・最終レビュー #1）。
        "LAYERS-height-ignores-unit",
        LAYERS,
        "return (LAYER_HEIGHTS[layer] ?? 0) * unit;",
        "return (LAYER_HEIGHTS[layer] ?? 0) * 1;",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 陣全体の演出（crown / crack）が行の pointer（ステップ）のまま光らせる（最終レビュー #2）。
        "EFFECTS-whole-circle-uses-the-raw-pointer",
        EFFECTS,
        "const target = glowTarget(spec.effect, targets.primary);",
        "const target = targets.primary;",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 値が変わらない set も強く光る。
        "EFFECTS-set-ignores-unchanged-values",
        EFFECTS,
        "if (values.get(valueKey) === value) strength = HUM;",
        "if (values.get(valueKey) === value) strength = 1;",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 段一致ではなく前方一致で祖先を探す。
        "NAMES-prefix-instead-of-segments",
        NAMES,
        "\t\tif (pointers.has(current)) return current;\n",
        "\t\tfor (const p of pointers) if (current.startsWith(p)) return p;\n",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 絵が実時間を読む（決定性が崩れる）。
        "GLOW-reads-the-clock",
        GLOW,
        "const seconds = tick / fps;",
        "const seconds = performance.now() / 1000;",
        ("py", [T_STAGE_CONTRACT]),
    ),
    (
        # stage 側だけに語を足す。
        "VOCAB-stage-only-word",
        MESSAGES,
        'export const STAGE_FILE = "stage.file";',
        'export const STAGE_FILE = "stage.file";\nexport const STAGE_PING = "stage.ping";',
        ("py", [T_STAGE_CONTRACT]),
    ),
    (
        # エディタ側で 3D を描き始める。
        "PANEL-draws",
        PANEL,
        'export const STAGE_PATH = "./stage/";',
        (
            'export const STAGE_PATH = "./stage/";\n'
            'export const probe = () => document.createElement("canvas").getContext("webgl2");'
        ),
        ("py", [T_STAGE_CONTRACT]),
    ),
    (
        # 中止しても書き出したものを渡す（ループの中と、描き終えた後の 2 か所の確認をどちらも外す）。
        "EXPORTER-ignores-abort",
        EXPORTER,
        (
            "\t\tfor (let n = 0; n < total; n++) {\n"
            "\t\t\tif (job.signal.aborted) {\n"
            "\t\t\t\tawait job.encoder.cancel();\n"
            "\t\t\t\treturn null;\n"
            "\t\t\t}\n"
            "\t\t\tjob.draw(tickAtFrame(range, n));\n"
            "\t\t\tawait job.encoder.add(n / VIDEO_FPS, 1 / VIDEO_FPS);\n"
            "\t\t\tjob.onProgress(n + 1, total);\n"
            "\t\t}\n"
            "\t\tif (job.signal.aborted) {\n"
            "\t\t\tawait job.encoder.cancel();\n"
            "\t\t\treturn null;\n"
            "\t\t}\n"
        ),
        (
            "\t\tfor (let n = 0; n < total; n++) {\n"
            "\t\t\tjob.draw(tickAtFrame(range, n));\n"
            "\t\t\tawait job.encoder.add(n / VIDEO_FPS, 1 / VIDEO_FPS);\n"
            "\t\t\tjob.onProgress(n + 1, total);\n"
            "\t\t}\n"
        ),
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # 仕上げ（finish）の最中に押された中止を見ず、出来たファイルを渡す（最終レビュー #3）。
        "EXPORTER-delivers-after-finish",
        EXPORTER,
        "\t\tif (job.signal.aborted) return null;\n\t\treturn bytes;",
        "\t\treturn bytes;",
        ("pnpm", ("apps/stage", "test")),
    ),
    (
        # `/stage/` だけ正規化を外す（写した先で素の結合をする）。`/play/` は元のまま通すので、
        # 拾うのは `/stage/` のテストでなければならない（`-k stage`）。
        "EDITOR-stage-escapes",
        EDITOR_PY,
        "            original = self.directory\n",
        (
            "            if prefix == STAGE_PREFIX:\n"
            '                return str(mount) + "/" + rest\n'
            "            original = self.directory\n"
        ),
        ("py", [T_EDITOR_PY, "-k", "stage"]),
    ),
]


def _copy_tree(dest: pathlib.Path) -> None:
    for item in COPY_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(
                src,
                dest / item,
                ignore=shutil.ignore_patterns(
                    "__pycache__", ".pytest_cache", "node_modules", "dist", "test-results"
                ),
            )
        else:
            shutil.copy2(src, dest / item)
    for app in PNPM_APPS:
        real_modules = ROOT / app / "node_modules"
        if real_modules.is_dir():
            (dest / app / "node_modules").symlink_to(real_modules)


def _purge_pycache(root: pathlib.Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _env(copy: pathlib.Path) -> dict[str, str]:
    src_dirs = [str(p) for p in sorted(copy.glob("packages/*/src"))]
    existing = os.environ.get("PYTHONPATH")
    path = os.pathsep.join(src_dirs + ([existing] if existing else []))
    tmp = copy / "tmp"
    tmp.mkdir(exist_ok=True)
    return dict(os.environ, PYTHONPATH=path, PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(tmp))


def _run_pytest(copy: pathlib.Path, target: list[str]) -> subprocess.CompletedProcess[str]:
    _purge_pycache(copy)
    deselect = [arg for test in DESELECT for arg in ("--deselect", test)]
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=--import-mode=importlib",
            *deselect,
            *target,
        ],
        cwd=copy,
        capture_output=True,
        text=True,
        env=_env(copy),
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
    )


def _run_pnpm(copy: pathlib.Path, app: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pnpm", "run", script],
        cwd=copy / app,
        capture_output=True,
        text=True,
        env=dict(os.environ, CI="1"),
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
    )


def _run(copy: pathlib.Path, check: tuple[str, object]) -> subprocess.CompletedProcess[str]:
    kind, argument = check
    if kind == "py":
        assert isinstance(argument, list)
        return _run_pytest(copy, argument)
    assert isinstance(argument, tuple)
    app, script = argument
    return _run_pnpm(copy, app, script)


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return ANSI.sub("", text)


def _summary(result: subprocess.CompletedProcess[str]) -> str:
    interesting = ("passed", "failed", "error", "Tests ", "problem")
    lines = [
        ln.strip() for ln in _plain(result.stdout).splitlines() if any(w in ln for w in interesting)
    ]
    if lines:
        return lines[-1][:110]
    tail = _plain(result.stderr).strip().splitlines()
    return tail[-1][:110] if tail else "(no summary)"


def _killers(result: subprocess.CompletedProcess[str]) -> list[str]:
    """赤くしたテストの名前（pytest の `FAILED …` と vitest の `FAIL …`）。"""
    names: list[str] = []
    for line in _plain(result.stdout + result.stderr).splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED "):
            names.append(stripped.removeprefix("FAILED ").split(" - ")[0])
        elif stripped.startswith("FAIL ") and stripped not in names:
            names.append(stripped.removeprefix("FAIL "))
    return names


def _is_red(result: subprocess.CompletedProcess[str]) -> bool:
    """失敗していること。**exit 5（0 件選択）や収集エラーは赤に数えない。**"""
    if result.returncode in (0, 5):
        return False
    blob = result.stdout + result.stderr
    return any(
        word in blob for word in ("failed", "error TS", "problem", "✘", "Failed Tests", "error")
    )


def _is_green(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0


def main() -> int:
    only = {n for n in os.environ.get("MUTATE_ONLY", "").split(",") if n}
    unknown = only - {m[0] for m in MUTATIONS}
    if unknown:
        print(f"!! MUTATE_ONLY に存在しない変異名: {sorted(unknown)}")
        return 1

    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-stage-"))
    try:
        _copy_tree(copy)
        where = (
            subprocess.run(
                [sys.executable, "-c", "import jin_cli.editor; print(jin_cli.editor.__file__)"],
                cwd=copy,
                capture_output=True,
                text=True,
                env=_env(copy),
                check=False,
            )
            .stdout.strip()
            .splitlines()
        )
        print(f"copy: {copy}")
        for line in where:
            print(f"imports from: {line}")
        if not where or not all(line.startswith(str(copy)) for line in where):
            print("!! jin_cli が隔離コピーを指していない。中止")
            return 2

        baseline_py = _run_pytest(copy, [T_STAGE_CONTRACT, T_STAGE_SPEC, T_EDITOR_PY])
        if not _is_green(baseline_py):
            print("BASELINE (pytest) NOT GREEN")
            print(baseline_py.stdout[-3000:])
            return 2
        print(f"baseline pytest: green ({_summary(baseline_py)})")

        for app in PNPM_APPS:
            baseline_ts = _run_pnpm(copy, app, "test")
            baseline_tsc = _run_pnpm(copy, app, "typecheck")
            if not (_is_green(baseline_ts) and _is_green(baseline_tsc)):
                print(f"BASELINE (pnpm {app}) NOT GREEN")
                print(baseline_ts.stdout[-1500:])
                print(baseline_tsc.stdout[-1500:])
                return 2
            print(f"baseline pnpm {app}: green ({_summary(baseline_ts)})")

        caught = 0
        skipped = 0
        mutations = [m for m in MUTATIONS if not only or m[0] in only]
        for name, rel, before, after, check in mutations:
            path = copy / rel
            original = path.read_text(encoding="utf-8")
            if before not in original:
                print(f"{name:38s} SKIP (!! before が見つからない)")
                skipped += 1
                continue
            path.write_text(original.replace(before, after, 1), encoding="utf-8")
            try:
                result = _run(copy, check)
            except subprocess.TimeoutExpired:
                print(f"{name:38s} {'TIMEOUT (!! ハングした)':30s} {RUN_TIMEOUT_SECONDS}s")
                continue
            finally:
                path.write_text(original, encoding="utf-8")
            ok = _is_red(result)
            status = "KILLED (red)" if ok else f"SURVIVED (!! exit {result.returncode})"
            caught += ok
            print(f"{name:38s} {status:30s} [{check[0]}] {_summary(result)}")
            for killer in _killers(result):
                print(f"    killed by: {killer}")
        subset = f" (subset; MUTATE_ONLY={','.join(sorted(only))})" if only else ""
        print(
            f"{caught}/{len(mutations)} mutations killed{subset}"
            + (f" ({skipped} skipped)" if skipped else "")
        )
        return 0 if mutations and caught == len(mutations) and skipped == 0 else 1
    finally:
        shutil.rmtree(copy, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
