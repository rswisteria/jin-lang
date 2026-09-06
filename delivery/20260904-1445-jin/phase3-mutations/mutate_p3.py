"""Phase 3（jin-render）の主要な防御を 1 つずつ壊し、対応テストが赤くなることを実測する。

`phase2-mutations/mutate_p2.py` と同じ流儀:

**隔離コピー上で変異する**。`packages/` `tests/` `examples/` `pyproject.toml` を一時ディレクトリへ
複製し、`PYTHONPATH` にコピー側の `src` を並べて pytest を走らせる。実ツリーは 1 バイトも
書き換えない（起動時に `jin_render.__file__` がコピー側を指すことを印字して確かめる）。

判定: 「赤」は **`returncode == 1` かつ summary に `failed`** があるとき。`-k` が 0 件を選ぶ exit 5 /
ファイル欠落 exit 4 / collection error は赤に数えない。`SKIP (pattern not found)` も caught に
数えず、1 件でもあれば exit 1。

実行: `uv run python delivery/20260904-1445-jin/phase3-mutations/mutate_p3.py`
      `MUTATE_ONLY=NAME1,NAME2 uv run python ...` で一部だけ回す
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
COPY_ITEMS = ["packages", "tests", "examples", "pyproject.toml"]

GEOMETRY = "packages/jin-render/src/jin_render/geometry.py"
SVG = "packages/jin-render/src/jin_render/svg.py"
LAYOUT = "packages/jin-render/src/jin_render/layout.py"
ORNAMENT = "packages/jin-render/src/jin_render/ornament.py"
OVERLAY = "packages/jin-render/src/jin_render/overlay.py"
CLI = "packages/jin-cli/src/jin_cli/main.py"

T_GEOMETRY = "packages/jin-render/tests/test_geometry.py"
T_SVG = "packages/jin-render/tests/test_svg.py"
T_LAYOUT = "packages/jin-render/tests/test_layout.py"
T_OVERLAY = "packages/jin-render/tests/test_overlay.py"
T_DETERMINISM = "packages/jin-render/tests/test_determinism.py"
T_SNAPSHOT = "packages/jin-render/tests/test_snapshots.py"
T_CLI = "packages/jin-cli/tests/test_render.py"
T_BUILD_RUN = "packages/jin-cli/tests/test_build_run.py"
T_GUARD = "tests/contract/test_guard_claims.py"
T_RENDER_CONTRACT = "tests/contract/test_render_contract.py"

#: (名前, 対象ファイル, before, after, pytest 引数)
MUTATIONS: list[tuple[str, str, str, str, list[str]]] = [
    # --- 決定性: 丸め関数 1 本（DP-JIN-SVG-DETERMINISM-01 / ADR-010）--------------------
    # 申し送り §10「丸め関数を素の str() に替える」
    (
        "DET-plain-str",
        SVG,
        "    text = format(value, _COORD_FORMAT)\n",
        "    text = str(value)\n",
        [
            T_SVG,
            T_LAYOUT,
            T_SNAPSHOT,
            "-k",
            "three_decimals or geometry_numbers or snapshot or negative_zero",
        ],
    ),
    (
        "DET-repr",
        SVG,
        "    text = format(value, _COORD_FORMAT)\n",
        "    text = repr(float(value))\n",
        [T_SVG, T_LAYOUT, "-k", "three_decimals or geometry_numbers"],
    ),
    # 桁数を変える（スナップショットと正規表現の両方が赤くなる）
    (
        "DET-two-decimals",
        SVG,
        "COORD_DECIMALS = 3\n",
        "COORD_DECIMALS = 2\n",
        [T_SVG, T_LAYOUT, T_SNAPSHOT, "-k", "three_decimals or geometry_numbers or snapshot"],
    ),
    # -0.0 の正規化を外す（libm の符号の揺れが SVG に出る）
    (
        "DET-negative-zero",
        SVG,
        "    if float(text) == 0.0:\n        # `-0.000` を `0.000` にそろえる（libm の符号の揺れを SVG に出さない）。\n        text = format(0.0, _COORD_FORMAT)\n",
        "    pass\n",
        [T_SVG, "-k", "negative_zero"],
    ),
    # --- XML エスケープ（申し送り §7 / Phase 5 のエディタが DOM に埋め込む）--------------
    (
        "ESC-attr-passthrough",
        SVG,
        "    return escape(xml_chars(value), _ATTR_ENTITIES)\n",
        "    return value\n",
        [T_SVG, T_LAYOUT, "-k", "escap or injection or quotes"],
    ),
    (
        "ESC-text-passthrough",
        SVG,
        '''def text_value(value: str) -> str:
    """テキストノードをエスケープする。

    guard: text_value -> xml_chars(value)
    guard: text_value -> escape(xml_chars(value))
    """
    return escape(xml_chars(value))
''',
        '''def text_value(value: str) -> str:
    """テキストノードをエスケープする。"""
    return value
''',
        [T_SVG, T_LAYOUT, T_GUARD, "-k", "text_escaping or hostile_rune or guard_claims"],
    ),
    (
        "ESC-quoteattr-style",
        SVG,
        "    return escape(xml_chars(value), _ATTR_ENTITIES)\n",
        "    from xml.sax.saxutils import quoteattr\n\n    return quoteattr(value)[1:-1]\n",
        [T_SVG, "-k", "double_quotes or attribute_escaping"],
    ),
    # --- data-jin 契約（申し送り §7 / machine 3 / 4）-------------------------------------
    # 「data-jin を 1 要素だけ落とす」: 核の pointer を消す
    (
        "CONTRACT-core-no-pointer",
        LAYOUT,
        '                    pointer=f"{base}/core",\n                    kind="core",\n',
        "                    pointer=None,\n                    kind=None,\n",
        [
            T_LAYOUT,
            T_RENDER_CONTRACT,
            "-k",
            "carries_both_attributes or nine_kinds or rendered_pointer",
        ],
    ),
    # 環の pointer だけを落とす（`<g>` は残るので「1 要素だけ」の変異）
    (
        "CONTRACT-ring-no-pointer",
        LAYOUT,
        """        return Node(
            "circle",
            [
                ("cx", fmt_coord(frame.cx)),
                ("cy", fmt_coord(frame.cy)),
                ("r", fmt_coord(radius * frame.scale)),
            ],
            pointer=base,
            kind="circle",
        )
""",
        """        return Node(
            "circle",
            [
                ("cx", fmt_coord(frame.cx)),
                ("cy", fmt_coord(frame.cy)),
                ("r", fmt_coord(radius * frame.scale)),
            ],
        )
""",
        [T_LAYOUT, "-k", "carries_both_attributes"],
    ),
    # 10 種目の kind を作る
    (
        "CONTRACT-tenth-kind",
        LAYOUT,
        '                ("data-jin-seq", str(row.seq)),\n                ],\n                pointer=pointer,\n                kind="circle",\n',
        '                ("data-jin-seq", str(row.seq)),\n                ],\n                pointer=pointer,\n                kind="trace-dot",\n',
        [
            T_LAYOUT,
            T_OVERLAY,
            T_RENDER_CONTRACT,
            "-k",
            "kind_is_one_of_the_nine or pointer_contract or rendered_pointer",
        ],
    ),
    # `<svg>` の外側に data-jin を持たない描画要素を作る（背景の塗り）
    (
        "CONTRACT-background-rect",
        SVG,
        "    lines = [head]\n",
        '    lines = [head, f\'  <rect x="{zero}" y="{zero}" width="{edge}" height="{edge}" fill="#fff"/>\']\n',
        [T_SVG, T_LAYOUT, "-k", "svg_root_is_not_a_contract or carries_both_attributes"],
    ),
    # --- 装飾（machine 8）-----------------------------------------------------------------
    # 申し送り §10「装飾を sha256 でなく固定にする」
    (
        "ORN-fixed",
        ORNAMENT,
        '    digest = hashlib.sha256(rune.encode("utf-8")).digest()\n',
        "    digest = bytes(range(32))\n",
        [
            T_DETERMINISM,
            T_SNAPSHOT,
            "-k",
            "ornament_changes or uses_sha256 or svg_changes_when_only_the_rune or snapshot",
        ],
    ),
    # `hash()`（PYTHONHASHSEED で変わる）に置き換える
    (
        "ORN-builtin-hash",
        ORNAMENT,
        '    digest = hashlib.sha256(rune.encode("utf-8")).digest()\n',
        "    digest = (abs(hash(rune)) % (2**64)).to_bytes(8, 'big') * 4\n",
        [T_DETERMINISM, "-k", "uses_sha256 or hash_seeds_agree"],
    ),
    # rune が無い circle にも装飾を描く
    (
        "ORN-always",
        LAYOUT,
        "        if circle.instruction is None:\n            return []\n",
        "        if circle.instruction is None:\n            circle = circle.model_copy(update={'instruction': None})\n",
        [T_LAYOUT, T_DETERMINISM, "-k", "without_a_rune or rings_are_drawn"],
    ),
    # --- trace overlay（申し送り §4 / machine 5）------------------------------------------
    # 申し送り §10「祖先一致を消す」: 完全一致だけにする
    (
        "OVL-exact-only",
        LAYOUT,
        "            if is_ancestor_or_same(candidate, row.pointer) and (\n",
        "            if candidate == row.pointer and (\n",
        [
            T_OVERLAY,
            T_RENDER_CONTRACT,
            "-k",
            "nearest_ancestor or referent or resolves_at_the_root_focus or live_pointer"
            " or falls_back_to_its_ancestor or huge_pointer",
        ],
    ),
    # referent 規則だけを消す（data-jin-ref を鍵に入れない）
    (
        "OVL-no-referent",
        LAYOUT,
        "        if node.ref is not None:\n            by_pointer.setdefault(node.ref, []).append(position)\n",
        "        pass\n",
        [
            T_OVERLAY,
            T_RENDER_CONTRACT,
            "-k",
            "referent or resolves_at_the_root_focus or live_pointer_resolves_at_the_root",
        ],
    ),
    # data-jin-ref そのものを出さない（属性を落とすと referent 規則も死ぬ）
    (
        "OVL-no-ref-attribute",
        SVG,
        '    if node.ref is not None:\n        out.append(("data-jin-ref", node.ref))\n',
        "    pass\n",
        [
            T_OVERLAY,
            T_LAYOUT,
            T_RENDER_CONTRACT,
            "-k",
            "referent or unresolved_reference or referent_resolves or live_pointer_resolves_at_the_root",
        ],
    ),
    # upto を無視する（単調増加の検査と点の個数が赤くなる）
    (
        "OVL-ignore-upto",
        LAYOUT,
        "    fired_rows = [row for row in all_rows if upto is None or row.seq <= upto]\n",
        "    fired_rows = list(all_rows)\n",
        [
            T_OVERLAY,
            T_CLI,
            T_SNAPSHOT,
            "-k",
            "dots_follows_upto or more_upto or highlights_grow or snapshot or dot_positions",
        ],
    ),
    # 点の角度をトレース全体ではなく発火数で割る（既に置いた点が動く）
    (
        "OVL-dots-move",
        LAYOUT,
        "        angle = geo.angle_at(position, total)\n",
        "        angle = geo.angle_at(position, max(1, len(rows)))\n",
        [T_OVERLAY, "-k", "dot_positions_do_not_move"],
    ),
    # 強調色を使わない（属性は残す = data-jin-fired だけでは検出できない側の確認）
    (
        "OVL-no-accent-colour",
        SVG,
        "        body.append((node.accent_attr, ACCENT))\n",
        "        body.append((node.accent_attr, INK))\n",
        [
            T_SVG,
            T_OVERLAY,
            T_SNAPSHOT,
            "-k",
            "swaps_the_accent or exact_pointer_is_highlighted or group_highlight or snapshot",
        ],
    ),
    # 壊れた行を黙って読み飛ばす（NFR-FAIL-001）
    (
        "OVL-skip-bad-rows",
        OVERLAY,
        "        if isinstance(seq, bool) or not isinstance(seq, int):\n",
        "        if False:\n",
        [T_OVERLAY, T_CLI, "-k", "malformed_row or wrong_types"],
    ),
    (
        "OVL-accept-bool-seq",
        OVERLAY,
        "        if isinstance(seq, bool) or not isinstance(seq, int):\n",
        "        if not isinstance(seq, int):\n",
        [T_OVERLAY, "-k", "malformed_row"],
    ),
    # --- focus（machine 6）----------------------------------------------------------------
    # 申し送り §10「focus を無視する」
    (
        "FOCUS-ignored",
        LAYOUT,
        "        focus_index = index_of[focus]\n",
        "        focus_index = index_of.get(model.root, 0)\n",
        [
            T_LAYOUT,
            T_OVERLAY,
            T_CLI,
            T_SNAPSHOT,
            "-k",
            "focus_changes or focus_switch or focus_decides or expands_only_depth_one or snapshot",
        ],
    ),
    # 未定義の focus を黙って root に落とす
    (
        "FOCUS-unknown-silent",
        LAYOUT,
        "        if focus not in index_of:\n",
        "        if False:\n",
        [T_LAYOUT, T_CLI, "-k", "unknown_focus"],
    ),
    # --- 星形多角形（layout.md §2.1）-------------------------------------------------------
    # 申し送り §10「k を n//2 にする」。n=6 / n=8 で正解と割れる
    (
        "STAR-n-half",
        GEOMETRY,
        "    return max(j for j in range(1, n) if 2 * j < n and math.gcd(n, j) == 1)\n",
        "    return n // 2\n",
        [T_GEOMETRY, T_LAYOUT, "-k", "star_step or loop_edges"],
    ),
    (
        "STAR-always-one",
        GEOMETRY,
        "    if n < 5:\n        return 1\n",
        "    if True:\n        return 1\n",
        [T_GEOMETRY, T_LAYOUT, "-k", "star_step or loop_edges"],
    ),
    # 訪問順を壊す（辺の接続が変わる）
    (
        "STAR-reversed",
        LAYOUT,
        "                pairs = [(j, (j + 1) % count) for j in range(count)]\n",
        "                pairs = [(j, (j - 1) % count) for j in range(count)]\n",
        [T_LAYOUT, "-k", "loop_edges_follow or arrows_follow_the_visit_order"],
    ),
    # C-1: 節を配列順に置き直す。辺は j→j+1 のままなので**単純多角形**になり、
    # 星形でなくなる。実測（F-C-P3-104 で訂正）: test_loop_edges_follow_the_star_polygon
    # の [5-2] / [8-3] が赤・訪問順テストは全 param 緑。
    # 2 本のテストが独立に効くことは下の STAR-pre-fix-* の 2 本が示す
    (
        "STAR-slot-identity",
        LAYOUT,
        "        return [(j * step) % count for j in range(count)]\n",
        "        return list(range(count))\n",
        [T_LAYOUT, "-k", "loop_edges_follow or arrows_follow_the_visit_order or array_order"],
    ),
    # --- レイアウト規則 --------------------------------------------------------------------
    # 存在しない環を描く（layout.md §1「存在しない環は描かず、半径も詰めない」）
    (
        "RING-always",
        LAYOUT,
        "        if circle.instruction is not None:\n            out.append(self._ring(base, frame, geo.RING_INSTRUCTION))\n",
        "        if True:\n            out.append(self._ring(base, frame, geo.RING_INSTRUCTION))\n",
        [T_LAYOUT, "-k", "flow_circle_draws_no_ring or rings_are_drawn"],
    ),
    # 環の半径を詰める
    (
        "RING-shrunk",
        GEOMETRY,
        "RING_BOUNDARY = 0.95\n",
        "RING_BOUNDARY = 0.85\n",
        [T_GEOMETRY, T_SNAPSHOT, "-k", "ring_radii or snapshot"],
    ),
    # 12 時位置から時計回りでなくする
    (
        "ANGLE-counter-clockwise",
        GEOMETRY,
        "    return TOP_ANGLE + 360.0 * index / count\n",
        "    return TOP_ANGLE - 360.0 * index / count\n",
        [T_GEOMETRY, T_SNAPSHOT, "-k", "clockwise or snapshot"],
    ),
    # 深さ 2 以降も展開する（循環で止まらなくなる）
    (
        "DEPTH-unbounded",
        LAYOUT,
        "        if target is None or depth >= 1:\n            return (geo.POINT_RADIUS, None)\n",
        "        if target is None or depth >= 4:\n            return (geo.POINT_RADIUS, None)\n",
        [T_LAYOUT, "-k", "expands_only_depth_one or circular_summon"],
    ),
    # 解決できない参照を破線にしない（JIN011 が普通の点に見える）
    (
        "BROKEN-ref-solid",
        LAYOUT,
        '    if ref is None:\n        # 解決できない参照は破線の空円（layout.md §5）。\n        attrs.append(("stroke-dasharray", DASH))\n',
        "    pass\n",
        [T_LAYOUT, "-k", "unresolved_reference or unresolved_await"],
    ),
    # root 未解決の印を出さない（JIN060）
    (
        "BROKEN-root-silent",
        LAYOUT,
        '            group.attrs.append(("data-jin-root", "unresolved"))\n',
        "            pass\n",
        [T_LAYOUT, "-k", "unresolved_root"],
    ),
    # 壊れたモデルで落ちる（Phase 4 のエラー回復が死ぬ）
    (
        "BROKEN-raise-on-missing",
        LAYOUT,
        "        target = self.index_of.get(name)\n        if target is None:\n            return _dot(center, geo.POINT_RADIUS * frame.scale, pointer, kind, ref=None)\n",
        "        target = self.index_of[name]\n        if target is None:\n            return _dot(center, geo.POINT_RADIUS * frame.scale, pointer, kind, ref=None)\n",
        [T_LAYOUT, "-k", "never_raises or unresolved_reference"],
    ),
    # textPath の id を pointer にする（XML の NCName にならない / 重複する）
    (
        "ID-duplicate",
        LAYOUT,
        '        name = f"jin-rune-{self._rune_paths}"\n        self._rune_paths += 1\n',
        '        name = "jin-rune"\n',
        [T_LAYOUT, "-k", "text_path_ids_are_unique"],
    ),
    # rune の切り詰めをやめる（環からはみ出す・決定的でなくなるわけではないが仕様違反）
    (
        "RUNE-no-truncate",
        LAYOUT,
        "    if len(flat) <= RUNE_MAX_CHARS:\n        return flat\n    return flat[: RUNE_MAX_CHARS - 1] + RUNE_ELLIPSIS\n",
        "    return flat\n",
        [T_LAYOUT, "-k", "truncated_deterministically"],
    ),
    # --- CLI ------------------------------------------------------------------------------
    # 既存ファイルを黙って上書きする
    (
        "CLI-overwrite",
        CLI,
        "    if path.exists() and not force:\n",
        "    if False:\n",
        [T_CLI, "-k", "not_overwritten_without_force"],
    ),
    # 出力先のシンボリックリンクを辿る（**事前判定だけ**を消す = 二層目が守るので緑が正しい）
    (
        "CLI-follow-symlink-upfront-only",
        CLI,
        "    if path.is_symlink():\n"
        "        # 文言にパスを入れ、並びも他の 3 条件と同じ `path: 理由` にそろえる\n"
        "        # （二層目・退避路・`fmt` も同じ形・F-V-P3-301）。R2 で\n"
        "        # `render` 側の前置をやめたときに、ここからパスが消える退行を作った\n"
        "        # （F-C-P3-202 / F-V-P3-201 / F-S-P3-201）。前置しない側に合わせる。\n"
        '        raise SymlinkWriteRefused(f"{path}: シンボリックリンクなので書き込みを拒みました")\n',
        "    pass\n",
        [T_CLI, "-k", "symlinked_output"],
    ),
    # 二層目（_write_atomically の Path(path).is_symlink）も消す → 赤くなる
    (
        "CLI-follow-symlink-both",
        CLI,
        "    if path.is_symlink():\n"
        "        # 文言にパスを入れ、並びも他の 3 条件と同じ `path: 理由` にそろえる\n"
        "        # （二層目・退避路・`fmt` も同じ形・F-V-P3-301）。R2 で\n"
        "        # `render` 側の前置をやめたときに、ここからパスが消える退行を作った\n"
        "        # （F-C-P3-202 / F-V-P3-201 / F-S-P3-201）。前置しない側に合わせる。\n"
        '        raise SymlinkWriteRefused(f"{path}: シンボリックリンクなので書き込みを拒みました")\n',
        "    pass\n",
        [T_CLI, "-k", "symlinked_output"],
    ),
    # 壊れた --trace の行を黙って読み飛ばす
    (
        "CLI-skip-broken-trace",
        CLI,
        "                except ValueError as exc:\n",
        "                except ValueError as exc:\n                    rows.append({'seq': number, 'pointer': None})\n                    numbers.append(number)\n                    continue\n                except AssertionError as exc:\n",
        [T_CLI, "-k", "broken_trace_line"],
    ),
    # --upto だけを受け付ける
    (
        "CLI-upto-without-trace",
        CLI,
        "    if upto is not None and trace is None:\n",
        "    if False:\n",
        [T_CLI, "-k", "upto_without_a_trace"],
    ),
    # 新規ファイルを mkstemp の 0600 のまま残す
    (
        "CLI-new-file-0600",
        CLI,
        "            os.chmod(temporary, _new_file_mode())\n",
        "            pass\n",
        [T_CLI, "-k", "generated_file_mode or jin_build_writes"],
    ),
    # ==================================================================================
    # 修正ラウンド 1（Phase 3 Stage 5 レビュー）で足した防御
    # ==================================================================================
    # --- A-1 / F-C-P3-001: JSONL の行区切りは `\n` だけ ---------------------------------
    (
        "TRACE-splitlines",
        CLI,
        '        with path.open(encoding="utf-8", newline="\\n") as handle:\n'
        "            for number, raw in enumerate(handle, start=1):\n"
        '                line = raw.removesuffix("\\n").removesuffix("\\r")\n',
        '        with path.open(encoding="utf-8") as handle:\n'
        "            for number, raw in enumerate(handle.read().splitlines(), start=1):\n"
        "                line = raw\n",
        [
            T_CLI,
            T_RENDER_CONTRACT,
            "-k",
            "unicode_line_break or crlf_line_endings or readable_by_jin_render",
        ],
    ),
    # --- A-2 / F-S-P3-001: 壊れた入力で Traceback を見せない ----------------------------
    (
        "TRACE-no-recursion-guard",
        CLI,
        "                except RecursionError as exc:\n",
        "                except FloatingPointError as exc:\n",
        [T_CLI, "-k", "deeply_nested_json_row"],
    ),
    (
        "OVL-no-seq-upper-bound",
        OVERLAY,
        "        if not 1 <= seq <= SEQ_MAX:\n",
        "        if not 1 <= seq:\n",
        [T_OVERLAY, T_CLI, "-k", "seq_outside_the_range or huge_integer_seq or huge_seq"],
    ),
    (
        "OVL-brief-raw-repr",
        OVERLAY,
        "    try:\n        text = repr(value)\n    except ValueError:\n",
        "    try:\n        text = repr(value)\n    except ZeroDivisionError:\n",
        [T_OVERLAY, "-k", "huge_value or huge_seq"],
    ),
    # --- B-9 / F-C-P3-004: seq は 1 始まり ---------------------------------------------
    (
        "OVL-accept-seq-zero",
        OVERLAY,
        "        if not 1 <= seq <= SEQ_MAX:\n",
        "        if not 0 <= seq <= SEQ_MAX:\n",
        [T_OVERLAY, T_CLI, "-k", "seq_outside_the_range or seq_below_one"],
    ),
    # --- A-3 / F-S-P3-002: 祖先一致は `/` 区切り ---------------------------------------
    (
        "OVL-prefix-not-segment-wise",
        OVERLAY,
        '        and pointer[len(candidate)] == "/"\n',
        "        and True\n",
        [T_OVERLAY, "-k", "ancestor_matching_is_segment_wise"],
    ),
    # --- B-3 / F-V-P3-004: 行番号は実ファイルの行 --------------------------------------
    (
        "CLI-row-index-as-line",
        CLI,
        '            f"{_safe(str(trace))}:{numbers[exc.index]}"\n',
        '            f"{_safe(str(trace))}:{exc.index + 1}"\n',
        [T_CLI, "-k", "real_file_line_number"],
    ),
    # --- A-4 / F-V-P3-001: 破線も丸め関数を通る ----------------------------------------
    (
        "DASH-raw-literal",
        SVG,
        'DASH = f"{fmt_coord(6.0)} {fmt_coord(4.0)}"\n',
        'DASH = "6 4"\n',
        [T_LAYOUT, "-k", "three_decimals"],
    ),
    # --- B-5 / F-S-P3-005: XML 1.0 Char の外を落とす -----------------------------------
    (
        "ESC-xml-chars-passthrough",
        SVG,
        '    return _XML_NON_CHAR.sub("\\ufffd", value)\n',
        "    return value\n",
        [T_SVG, "-k", "xml_char or replacement_character or noncharacter or valid_characters"],
    ),
    # --- B-1 / F-C-P3-003: summon の紋が見える -----------------------------------------
    (
        "SUMMON-no-outline",
        LAYOUT,
        '        wrapper.children.append(\n            Node(\n                "circle",\n',
        '        wrapper.children.append(\n            Node(\n                "desc",\n',
        [T_LAYOUT, "-k", "visible_outline or parallel_draws_no_chord or actual_reach"],
    ),
    # --- F-C-P3-005: 入れ子の実寸で止まる ----------------------------------------------
    (
        "SUMMON-fixed-extent",
        LAYOUT,
        "        natural = geo.NESTED_SCALE * self._outer_extent(target) + geo.SUMMON_GAP\n",
        "        natural = geo.NESTED_SCALE * geo.RING_BOUNDARY\n",
        [T_LAYOUT, "-k", "actual_reach or radial_line_stops"],
    ),
    # --- C-2 / F-S-P3-004: 新規ファイルのモードが umask を尊重する ----------------------
    (
        "CLI-ignore-umask",
        CLI,
        "    mask = os.umask(0)\n    os.umask(mask)\n    return 0o644 & ~mask\n",
        "    return 0o644\n",
        [T_CLI, "-k", "generated_file_mode or jin_build_writes"],
    ),
    # --- F-V-P3-207: 弦の余裕 ε を消す（レビューの M-B1b。R3 まで緑のままだった）------
    (
        "FLOW-limit-drops-epsilon",
        LAYOUT,
        "        return geo.FLOW_RING * math.sin(math.pi / count) - "
        "(geo.ARROW_HEAD + geo.FLOW_NODE_EPSILON)\n",
        "        return geo.FLOW_RING * math.sin(math.pi / count) - geo.ARROW_HEAD\n",
        [T_LAYOUT, "-k", "every_flow_chord_is_drawn"],
    ),
    # --- B-2 / F-C-P3-205: 点に落ちる下限（この値が動くと 2 つの境界がずれる）-----------
    (
        "FLOW-point-fallback-off",
        LAYOUT,
        "        if limit < geo.POINT_RADIUS:\n",
        "        if limit < 0.0:\n",
        [T_LAYOUT, "-k", "two_crowding_boundaries or crowded_flow"],
    ),
    # --- A-1 / F-C-P3-202: 拒否文言にパスが入る -----------------------------------------
    (
        "CLI-symlink-message-without-path",
        CLI,
        # 一層目（`_write_svg`）だけを狙う。二層目（`_write_atomically`）の raise は
        # 1 行の形が同じなので、直前のコメント行まで含めて一意にする
        "        # （F-C-P3-202 / F-V-P3-201 / F-S-P3-201）。前置しない側に合わせる。\n"
        '        raise SymlinkWriteRefused(f"{path}: シンボリックリンクなので書き込みを拒みました")\n',
        "        # （F-C-P3-202 / F-V-P3-201 / F-S-P3-201）。前置しない側に合わせる。\n"
        '        raise SymlinkWriteRefused("シンボリックリンクなので書き込みを拒みました")\n',
        [T_CLI, "-k", "symlinked_output_is_refused"],
    ),
    # 並びを `理由: path` に戻す（R3 までの形）。パスの有無だけを見ていたので気づけなかった
    # （F-V-P3-301）。
    (
        "CLI-symlink-message-order",
        CLI,
        "        # （F-C-P3-202 / F-V-P3-201 / F-S-P3-201）。前置しない側に合わせる。\n"
        '        raise SymlinkWriteRefused(f"{path}: シンボリックリンクなので書き込みを拒みました")\n',
        "        # （F-C-P3-202 / F-V-P3-201 / F-S-P3-201）。前置しない側に合わせる。\n"
        '        raise SymlinkWriteRefused(f"シンボリックリンクなので書き込みを拒みました: {path}")\n',
        [T_CLI, "-k", "symlinked_output_is_refused"],
    ),
    # --- 項 1 / F-C-P3-303: `jin build` の成功文言も `_echo_or_exit` を通る ------------
    (
        "CLI-build-success-raw-echo",
        CLI,
        '        _echo_or_exit(f"書き出しました: {_safe(str(path))}")\n',
        '        typer.echo(f"書き出しました: {_safe(str(path))}")\n',
        [T_BUILD_RUN, "-k", "full_stdout_on_the_build_success_message"],
    ),
    # --- B-3 / F-W-P3-201: 成功文言も書けなければ 1 行 + exit 1 -------------------------
    (
        "CLI-success-message-raw-echo",
        CLI,
        '    _echo_or_exit(f"書き出しました: {_safe(str(out))}")\n',
        '    typer.echo(f"書き出しました: {_safe(str(out))}")\n',
        [T_CLI, "-k", "full_stdout_on_the_success_message"],
    ),
    # --- B-4 / F-W-P3-202: fd 1 が閉じているとき --------------------------------------
    (
        "CLI-no-closed-stdout-branch",
        CLI,
        "    if sys.stdout is None:\n",
        "    if False:\n",
        [T_CLI, "-k", "closed_stdout"],
    ),
    # --- F-S-P3-105 / F-V-P3-113: umask の読み取りは必ず元に戻す ------------------------
    (
        "CLI-umask-not-restored",
        CLI,
        "    mask = os.umask(0)\n    os.umask(mask)\n",
        "    mask = os.umask(0)\n",
        [T_CLI, "-k", "umask_restores or generated_file_mode"],
    ),
    # --- F-S-P3-103: 標準出力に書けないとき 1 行 + exit 1 -------------------------------
    (
        "CLI-stdout-oserror-traceback",
        CLI,
        "    except OSError as exc:\n        # `> /dev/full`（ENOSPC）など（F-S-P3-103）。\n        _fail_on_stdout(exc)\n",
        "    except ZeroDivisionError as exc:\n        raise\n",
        [T_CLI, "-k", "full_stdout"],
    ),
    # --- F-S-P3-106: --upto の値も 80 文字で切る ----------------------------------------
    (
        "CLI-upto-raw-value",
        CLI,
        '        typer.echo(f"--upto は 0 以上の整数です（指定値: {brief(upto)}）", err=True)\n',
        '        typer.echo(f"--upto は 0 以上の整数です（指定値: {upto}）", err=True)\n',
        [T_CLI, "-k", "huge_negative_upto"],
    ),
    # --- A-9 / F-W-P3-003: 親ディレクトリを作らない ------------------------------------
    (
        "CLI-create-parent",
        CLI,
        '    if not parent.is_dir():\n        raise WriteRefused(f"出力先のディレクトリがありません: {parent}")\n',
        "    parent.mkdir(parents=True, exist_ok=True)\n",
        [T_CLI, "-k", "missing_parent_directory"],
    ),
    # --- F-W-P3-007: 入力の .jin を上書きしない ----------------------------------------
    (
        "CLI-overwrite-the-input",
        CLI,
        "    if path.exists() and path.resolve() == source.resolve():\n",
        "    if False:\n",
        [T_CLI, "-k", "over_the_input_jin"],
    ),
    # --- F-S-P3-010: 標準出力は UTF-8 のバイト列 ---------------------------------------
    (
        "CLI-stdout-locale",
        CLI,
        '    buffer = getattr(sys.stdout, "buffer", None)\n',
        "    buffer = None\n",
        [T_CLI, T_RENDER_CONTRACT, "-k", "byte_identical or locale_cannot_encode"],
    ),
    # --- A-4 / F-C-P3-104: 配置と辺の 2 本のテストが独立に効くことの実測 -----------------
    # 修正前挙動（配置は恒等・辺は j → (j+k) mod n）。星形の見た目は保たれるので
    # 星形テストは**緑のまま**で、訪問順テストだけが赤になる。
    # `_flow_slots` と `_flow_edges` の 2 箇所を同時に変えるので main() で特例扱いする。
    (
        "STAR-pre-fix-visit-order",
        LAYOUT,
        "        return [(j * step) % count for j in range(count)]\n",
        "        return list(range(count))\n",
        [T_LAYOUT, "-k", "arrows_follow_the_visit_order"],
    ),
    # 同じ置換で星形テストが緑のままであることも実測する（EXPECT_GREEN）。
    (
        "STAR-pre-fix-star-shape-stays",
        LAYOUT,
        "        return [(j * step) % count for j in range(count)]\n",
        "        return list(range(count))\n",
        [T_LAYOUT, "-k", "loop_edges_follow"],
    ),
    # --- B-1 / F-C-P3-101: flow の弦が節の数で消えない ----------------------------------
    (
        "FLOW-node-scale-fixed",
        LAYOUT,
        "        if limit is None or natural <= limit:\n",
        "        if True:\n",
        [T_LAYOUT, "-k", "every_flow_chord_is_drawn or shrinks_its_contents"],
    ),
    # 節の紋と弦の隙間は**同じ関数**から採る（片方だけ動くと図が食い違う）。
    # 紋だけ制限を外す変異は弦の本数を変えないので、両者の一致を見るテストが要る。
    (
        "FLOW-no-node-limit",
        LAYOUT,
        "        limit = self._flow_node_limit(count)\n",
        "        limit = None\n",
        [T_LAYOUT, "-k", "chord_gap_matches_the_drawn_node"],
    ),
    (
        "FLOW-extent-no-limit",
        LAYOUT,
        "        return self._reference_size(\n"
        "            flow.steps[position], depth, self._flow_node_limit(len(flow.steps))\n"
        "        )[0]\n",
        "        return self._reference_size(flow.steps[position], depth, None)[0]\n",
        [T_LAYOUT, "-k", "chord_gap_matches_the_drawn_node or every_flow_chord_is_drawn"],
    ),
    # --- B-3 / F-V-P3-105: 弦と節の kind ------------------------------------------------
    (
        "KIND-chord-as-circle",
        LAYOUT,
        '            out.append(Node("path", [("d", d)], pointer=f"{base}/flow", kind="flow-edge"))\n',
        '            out.append(Node("path", [("d", d)], pointer=f"{base}/flow", kind="circle"))\n',
        [T_OVERLAY, T_LAYOUT, "-k", "flow_pointer_lands or every_kind_is_one_of_the_nine"],
    ),
    (
        "KIND-flow-node-as-tool",
        LAYOUT,
        '                    f"{base}/flow/steps/{position}",\n                    "flow-edge",\n',
        '                    f"{base}/flow/steps/{position}",\n                    "tool",\n',
        [T_OVERLAY, "-k", "flow_pointer_lands"],
    ),
    # --- B-5 / F-W-P3-104: jin build の成功文言も _safe -------------------------------
    (
        "CLI-build-success-unsafe",
        CLI,
        '        _echo_or_exit(f"書き出しました: {_safe(str(path))}")\n',
        '        _echo_or_exit(f"書き出しました: {path}")\n',
        [T_BUILD_RUN, "-k", "build_success_message"],
    ),
    # --- A-10 / F-W-P3-005: render がサブコマンドとして登録されている -------------------
    (
        "CLI-render-not-registered",
        CLI,
        "@app.command()\ndef render(\n",
        "def render(\n",
        [T_CLI, "-k", "help_lists_render or registered_subcommand"],
    ),
]

#: 二層防御のため「片方だけ消しても緑」が正しいもの。
#: `jin render -o` のリンク判定は 2 層ある: `_write_svg` の事前判定（文言のため）と
#: `_write_atomically` の `Path(path).is_symlink()`（`os.replace` の直前）。
#: 緑が正しい変異。理由は 2 種類あるので印字も分ける（F-W-P3-204）。
#: - `two-layer`: 二層防御の片方を消しただけ（もう一方が拒む）
#: - `claim`: 緑であること自体が主張（そのテストはこの変異では落ちない、が固定したい性質）
EXPECT_GREEN_REASON: dict[str, str] = {
    "CLI-follow-symlink-upfront-only": "二層目が守る",
    # 修正前挙動（恒等配置 + 辺 j→j+k）は星形の見た目を保つ。星形テストが緑のままで、
    # 訪問順テスト（STAR-pre-fix-visit-order）だけが赤になることが「2 本が独立に効く」
    # 証拠（F-C-P3-104 の実測）。
    "STAR-pre-fix-star-shape-stays": "主張そのもの（星形テストは配置の恒等化では落ちない）",
}
#: 名前は `EXPECT_GREEN_REASON` の鍵が唯一の真実（2 つの集合に分けると片方だけに
#: 足す事故が起きる）。
EXPECT_GREEN: set[str] = set(EXPECT_GREEN_REASON)


def _copy_tree(dest: pathlib.Path) -> None:
    for item in COPY_ITEMS:
        src = ROOT / item
        if src.is_dir():
            shutil.copytree(
                src, dest / item, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
            )
        else:
            shutil.copy2(src, dest / item)


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
            *target,
        ],
        cwd=copy,
        capture_output=True,
        text=True,
        env=_env(copy),
        check=False,
    )


def _summary(result: subprocess.CompletedProcess[str]) -> str:
    lines = [
        ln for ln in result.stdout.splitlines() if "passed" in ln or "failed" in ln or "error" in ln
    ]
    if lines:
        return lines[-1]
    tail = result.stderr.strip().splitlines()
    return tail[-1] if tail else "(no summary)"


def _is_red(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 1 and "failed" in _summary(result)


def _is_green(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0 and "passed" in _summary(result)


def main() -> int:
    # `MUTATE_ONLY` の綴り違いは baseline の**前**に落とす（F-W-P3-009）。
    # 隔離コピーと baseline に数秒かけてから「0 件が緑」で終わると成功に見える。
    only = {n for n in os.environ.get("MUTATE_ONLY", "").split(",") if n}
    unknown = only - {m[0] for m in MUTATIONS}
    if unknown:
        print(f"!! MUTATE_ONLY に存在しない変異名: {sorted(unknown)}")
        return 1

    copy = pathlib.Path(tempfile.mkdtemp(prefix="jin-mutate-p3-"))
    try:
        _copy_tree(copy)
        where = (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import jin_render, jin_cli; print(jin_render.__file__); print(jin_cli.__file__)",
                ],
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
            print("!! jin_render / jin_cli が隔離コピーを指していない。中止")
            return 2
        baseline = _run_pytest(
            copy, ["packages/jin-render/tests", T_CLI, T_GUARD, T_RENDER_CONTRACT]
        )
        if not _is_green(baseline):
            print("BASELINE NOT GREEN")
            print(baseline.stdout[-3000:])
            return 2
        print(f"baseline: green ({_summary(baseline)})")
        caught = 0
        skipped = 0
        mutations = [m for m in MUTATIONS if not only or m[0] in only]
        for name, rel, before, after, target in mutations:
            path = copy / rel
            original = path.read_text(encoding="utf-8")
            if before not in original:
                print(f"{name:28s} SKIP (pattern not found)")
                skipped += 1
                continue
            mutated = original.replace(before, after, 1)
            if name.startswith("STAR-pre-fix-"):
                # 辺も修正前（j → (j+k) mod n）に戻す。`step` は `_flow_edges` の
                # スコープに無いので `geo.star_step(count)` を直に書く。
                edge_before = (
                    "                # 辺は**実行順**（j → j+1）。星形は `_flow_slots` の角位置が作る。\n"
                    "                pairs = [(j, (j + 1) % count) for j in range(count)]\n"
                )
                edge_after = (
                    "                pairs = [\n"
                    "                    (j, (j + geo.star_step(count)) % count) for j in range(count)\n"
                    "                ]\n"
                )
                assert edge_before in mutated, f"{name}: 辺の置換対象が見つからない"
                mutated = mutated.replace(edge_before, edge_after, 1)
            if name == "CLI-follow-symlink-both":
                # 二層目（`_write_atomically` の `os.replace` 直前の判定）も外す
                mutated = mutated.replace(
                    "        if Path(path).is_symlink():\n"
                    '            raise SymlinkWriteRefused(f"{path}: シンボリックリンクなので書き込みを拒みました")\n',
                    "        pass\n",
                    1,
                )
            path.write_text(mutated, encoding="utf-8")
            try:
                result = _run_pytest(copy, target)
            finally:
                path.write_text(original, encoding="utf-8")
            if name in EXPECT_GREEN:
                ok = _is_green(result)
                why = EXPECT_GREEN_REASON.get(name, "期待どおり")
                status = f"GREEN (expected: {why})" if ok else f"RED (!! {why} が成立しない)"
            else:
                ok = _is_red(result)
                if ok:
                    status = "RED (expected)"
                elif result.returncode == 0:
                    status = "GREEN (!! not caught)"
                else:
                    status = f"NOT RED (!! exit {result.returncode})"
            caught += ok
            print(f"{name:28s} {status:34s} {_summary(result)}")
        subset = (
            f" (subset of {len(MUTATIONS)}; MUTATE_ONLY={','.join(sorted(only))})" if only else ""
        )
        print(
            f"{caught}/{len(mutations)} mutations caught{subset}"
            + (f" ({skipped} skipped)" if skipped else "")
        )
        return 0 if mutations and caught == len(mutations) and skipped == 0 else 1
    finally:
        shutil.rmtree(copy, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
