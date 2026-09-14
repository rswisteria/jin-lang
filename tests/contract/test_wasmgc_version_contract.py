"""パッケージ横断契約: wasm-GC 生成系が前提にする wasmtime の版と、実際に入っている版の一致（jil.md §6.1）。

`wat2wasm` が wasm-GC の構文を通すこと・既定の `Config()` で GC が有効なことは
`delivery/<最新ラン>-jin/wasmgc-api-probe.md` の **48.0.0 実測**に固定してある
（`test_adk_version_contract.py` と同じ規律）。`uv.lock` が別の版を解決するようになった瞬間にここが赤くなり、
「probe を取り直して `jin_wasmgc.TARGET_WASMTIME_VERSION` を更新する」手順へ誘導する。
"""

from __future__ import annotations

from importlib.metadata import version

from jin_wasmgc import TARGET_WASMTIME_VERSION

from tests.conftest import DELIVERY_RUN


def test_installed_wasmtime_matches_the_probed_version() -> None:
    assert version("wasmtime") == TARGET_WASMTIME_VERSION, (
        f"wasmtime {version('wasmtime')} が入っているが、生成系は {TARGET_WASMTIME_VERSION} の実測に"
        "固定されている。wasmgc-api-probe.md を取り直してから TARGET_WASMTIME_VERSION を更新すること"
    )


def test_probe_document_records_the_same_version() -> None:
    probe = (DELIVERY_RUN / "wasmgc-api-probe.md").read_text(encoding="utf-8")
    assert f"`wasmtime {TARGET_WASMTIME_VERSION}`" in probe
