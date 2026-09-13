# Wasmoon / lupa 実測 probe

計測日: 2026-09-13。作業ディレクトリ `/home/wisteria/.claude/jobs/8e42df6b/tmp/probe`（git リポジトリの外）。
Node v22.16.0 / npm（`npm install wasmoon`）、Python 3.14.7 / uv 0.12.10（`uv run --with lupa python <script>`）。
すべての値はこのディレクトリのスクリプトを実行して得た生出力から転記した。推測値は無い。
スクリプト全文は同ディレクトリの `probe_a.cjs` / `probe_a4a2.cjs` / `probe_a8.cjs` / `probe_a6.cjs` / `probe_a6b.cjs` / `probe_a9x.cjs` / `probe_b.py`、
生出力は `out_*.txt` に残してある。

## 計測値一覧

| 項目 | wasmoon | lupa |
|---|---|---|
| パッケージ版 | `wasmoon@1.16.0` | `lupa 2.8` |
| Lua 版（`_VERSION`） | `Lua 5.4`（パッチ版はバイナリに埋め込まれておらず未確定） | `lupa.lua54`: `Lua 5.4`（バイナリ文字列は `Lua 5.4.8`）。**既定の `lupa.LuaRuntime` は Lua 5.5.1**（`lupa.LUA_VERSION == (5, 5)`） |
| 配布物サイズ | `glue.wasm` 271,581 B（gzip 111,128 B）/ `index.js` 151,652 B（gzip 39,177 B） | `lua54.cpython-314-x86_64-linux-gnu.so` 672,688 B（lua51/52/53/54/55/luajit20/luajit21 の 7 本を同梱） |
| ホスト→Lua 呼び出しで object/array を渡し table を受け取る | 可。`global.call` は `MultiReturn`（配列）を返す。`{ops={{"rect",1.0,2.0}},n=3}` は `{"ops":[["rect",1,2]],"n":3}` になる（**1.0 は JS の number 1 に潰れる**） | 可。戻りは `lupa.lua54._LuaTable`。`1.0` は Python の `float 1.0`、`1` は `int 1` のまま（型が保たれる） |
| ホスト関数の中から `coroutine.yield` | `attempt to yield across a C-call boundary`（Lua のエラーとして捕捉可）。JS から `global.call` で Lua に再入してそこで yield すると **`PANIC: unprotected error in call to Lua API (attempt to yield from outside a coroutine)` + `Aborted(native code called abort())`**（engine はその後も動いた） | `attempt to yield across a C-call boundary`（`LuaError` として捕捉可） |
| 純 Lua スケジューラ（`tick()` をホストから 3 回） | 可。`step-1` / `step-2` / `step-3`、4 回目で `finished` / `dead` | 可。同じ結果 |
| `math.type(1)` / `math.type(1.0)` | `integer` / `float` | `integer` / `float` |
| `1//2` | `0`（integer） | `0`（integer） |
| `2^63` | `9.2233720368548e+18`（float） | `9.2233720368548e+18`（float） |
| `math.maxinteger` | Lua 内では `9223372036854775807`。**JS に渡すと `9223372036854776000`（`Number.isSafeInteger` false）** | Python の `int 9223372036854775807`（`== 2**63-1` True） |
| `pairs` 順序 {b=1,a=2,c=3} | **1 つの engine 内では安定**。engine を跨ぐと変わる（同時に生かした 4 engine で `a,b,c` / `c,a,b` / `b,c,a` / `a,c,b`。1.1 秒あけて作り直しても変わる） | **1 つの runtime 内では安定**。runtime を跨ぐと変わる（同一プロセスの 2 runtime で `b,a,c` / `c,a,b`、別実行で `a,b,c` / `c,b,a`） |
| `utf8.len("あいう")` | `3`（`#` は 9） | `3`（`#` は 9） |
| 既定で `require` / `load` / `os` / `io` | すべて有り（`loadstring` は nil。`os.execute` / `io.open` / `os.exit` / `os.getenv` も有り） | すべて有り。加えて **`python` グローバル**（`python.builtins` は `register_eval=False` でも残る） |
| ホストから nil 化 | **`global.set('load', null)` は wasmoon 側の `TypeError: Cannot read properties of null (reading 'then')` で失敗し、`load` は残る**。`global.set('load', undefined)` なら消え、以後 `attempt to call a nil value (global 'load')` | `lua.globals().load = None` で消え、以後 `attempt to call a nil value (global 'load')` |
| `openStandardLibs: false` | `string` / `table` / `math` / `utf8` / `coroutine` / `pairs` / `print` / `pcall` / `type` / `tostring` も**全部 nil**（base ライブラリごと無い） | （該当オプション無し） |
| `tick()` が 50 個の小配列を返す往復（1000 回平均） | **約 600 µs/回**（nested）。平坦 250 要素 約 455 µs、10 行 121 µs、単一整数 1.0 µs。**JSON 文字列で返して `JSON.parse` すると 35.5 µs** | 呼び出しのみ（table は Lua 側に留まる）約 5 µs、50 行を Python の list に変換して 35.2 µs |

---

## A. wasmoon

### A.1 版とサイズ

```
$ cd /home/wisteria/.claude/jobs/8e42df6b/tmp/probe && npm init -y >/dev/null && npm install wasmoon && npm ls wasmoon && node --version
added 2 packages, and audited 3 packages in 601ms
found 0 vulnerabilities
probe@1.0.0 /home/wisteria/.claude/jobs/8e42df6b/tmp/probe
└── wasmoon@1.16.0

v22.16.0
```

```
$ ls -l node_modules/wasmoon/dist
total 480
-rw-r--r-- 1 wisteria wisteria    390 Sep 13 12:53 decoration.d.ts
-rw-r--r-- 1 wisteria wisteria    698 Sep 13 12:53 engine.d.ts
-rw-r--r-- 1 wisteria wisteria    566 Sep 13 12:53 factory.d.ts
-rw-r--r-- 1 wisteria wisteria    781 Sep 13 12:53 global.d.ts
-rwxr-xr-x 1 wisteria wisteria 271581 Sep 13 12:53 glue.wasm
-rw-r--r-- 1 wisteria wisteria    686 Sep 13 12:53 index.d.ts
-rw-r--r-- 1 wisteria wisteria 151652 Sep 13 12:53 index.js
-rw-r--r-- 1 wisteria wisteria  11133 Sep 13 12:53 luawasm.d.ts
-rw-r--r-- 1 wisteria wisteria     51 Sep 13 12:53 multireturn.d.ts
-rw-r--r-- 1 wisteria wisteria     48 Sep 13 12:53 pointer.d.ts
-rw-r--r-- 1 wisteria wisteria     95 Sep 13 12:53 raw-result.d.ts
-rw-r--r-- 1 wisteria wisteria   2040 Sep 13 12:53 thread.d.ts
-rw-r--r-- 1 wisteria wisteria    654 Sep 13 12:53 type-extension.d.ts
drwxr-xr-x 2 wisteria wisteria   4096 Sep 13 12:53 type-extensions
-rw-r--r-- 1 wisteria wisteria   1272 Sep 13 12:53 types.d.ts

$ gzip -c node_modules/wasmoon/dist/glue.wasm | wc -c
111128
$ gzip -c node_modules/wasmoon/dist/index.js | wc -c
39177
```

- `.wasm` は `glue.wasm` の 1 本（271,581 B、gzip 111,128 B）。
- JS 本体は `index.js` の 1 本（151,652 B、gzip 39,177 B）。UMD 形式（`require('wasmoon')` で読める）。`package.json` に `"type": "module"` / `exports` は無く `"main": "dist/index.js"`。
- Lua のパッチ版: `strings -n 5 glue.wasm | grep -iE "5\.4\.[0-9]|lua 5"` は `Lua 5.4` のみで、`5.4.x` の文字列は埋め込まれていない（未確定）。

### A.2 `_VERSION`

スクリプト（`probe_a.cjs` 抜粋）:

```js
const { LuaFactory } = require('wasmoon');
const factory = new LuaFactory();
const lua = await factory.createEngine({ openStandardLibs: true });
console.log(lua.doStringSync('return _VERSION'));
```

出力:

```
=== A.2 _VERSION ===
Lua 5.4
```

### A.3 JS→Lua 呼び出し（object/array を渡し、Lua の table を JS で受け取る）

スクリプト（`probe_a.cjs` 抜粋）:

```js
lua.global.set('f', (obj) => {
    console.log('JS f received:', JSON.stringify(obj));
    return 'from-js';
});
lua.doStringSync(`
    function g(input)
        local seen = f(input)
        return {ops = {{"rect", 1.0, 2.0}}, n = 3, echo = seen, got_kind = type(input), got_a = input.a, got_xs2 = input.xs[2]}
    end
`);
const ret = lua.global.call('g', { a: 1, xs: [10, 20, 30] });
console.log('MultiReturn length:', ret.length);
console.log('JSON.stringify(ret[0]):', JSON.stringify(ret[0]));
console.log('typeof ret[0]:', typeof ret[0], 'Array.isArray(ret[0].ops):', Array.isArray(ret[0].ops));
console.log('ops[0]:', JSON.stringify(ret[0].ops[0]), 'Array.isArray(ops[0]):', Array.isArray(ret[0].ops[0]));
console.log('typeof ops[0][1]:', typeof ret[0].ops[0][1], 'value:', ret[0].ops[0][1]);
```

出力:

```
=== A.3 JS -> Lua call with object/array, Lua table back ===
JS f received: {"a":1,"xs":[10,20,30]}
MultiReturn length: 1
JSON.stringify(ret[0]): {"ops":[["rect",1,2]],"got_kind":"userdata","echo":"from-js","got_xs2":20,"n":3,"got_a":1}
typeof ret[0]: object Array.isArray(ret[0].ops): true
ops[0]: ["rect",1,2] Array.isArray(ops[0]): true
typeof ops[0][1]: number value: 1
```

観測:

- `global.set` で JS 関数を Lua グローバルに置き、Lua から呼べる。`global.call('g', obj)` で JS の object/array を渡せる。
- JS から渡した object は Lua 側では **`type(input) == "userdata"`**（proxy）。`input.a` / `input.xs[2]` で読める（`xs[2]` が `20` なので **JS の 0 始まり配列が Lua の 1 始まりで見える**）。
- Lua の table は JS の object / Array に変換されて返る（`ops` は `Array.isArray` true）。
- **Lua の `1.0`（float）は JS では number `1` になり、integer / float の区別は落ちる。**
- `JSON.stringify` のキー順は実行のたびに変わる（`pairs` 順序に依存、A.6 参照）。

### A.4 コルーチンと C 境界

#### A.4(a)-1: Lua から呼んだ JS 関数の中で `coroutine.yield` を呼ぶ

スクリプト（`probe_a.cjs` 抜粋）:

```js
lua.global.set('jsfn', (y) => {
    // y is coroutine.yield passed from Lua; call it from JS
    return y();
});
lua.doStringSync(`
    function coroutine_yield_wrapper() return coroutine.yield() end
    function test_a1()
        local co = coroutine.create(function() jsfn(coroutine.yield) return "done" end)
        local ok, err = coroutine.resume(co)
        return tostring(ok) .. " | " .. tostring(err)
    end
`);
try {
    console.log('test_a1 (JS calls coroutine.yield passed as arg):', lua.global.call('test_a1')[0]);
} catch (e) {
    console.log('test_a1 threw:', String(e));
}
```

出力:

```
=== A.4(a) coroutine.yield inside JS function called from Lua ===
test_a1 (JS calls coroutine.yield passed as arg): false | Error: attempt to yield across a C-call boundary
```

#### A.4(a)-2: JS 関数の中から `global.call` で Lua に再入し、その Lua 関数が yield する（別プロセスで実行）

スクリプト（`probe_a4a2.cjs`）:

```js
const { LuaFactory } = require('wasmoon');
async function main() {
    const lua = await new LuaFactory().createEngine({ openStandardLibs: true });
    lua.global.set('jsfn2', () => {
        return lua.global.call('coroutine_yield_wrapper');
    });
    lua.doStringSync(`
        function coroutine_yield_wrapper() return coroutine.yield() end
        function test_a2()
            local co = coroutine.create(function() jsfn2() return "done" end)
            local ok, err = coroutine.resume(co)
            return tostring(ok) .. " | " .. tostring(err)
        end
    `);
    try {
        console.log('test_a2 (JS calls back into Lua via global.call, which yields):', lua.global.call('test_a2')[0]);
    } catch (e) {
        console.log('test_a2 threw:', String(e));
    }
    console.log('--- is the engine still usable after that? ---');
    try {
        console.log('doStringSync("return 1+1") =', lua.doStringSync('return 1+1'));
    } catch (e) {
        console.log('engine unusable:', String(e));
    }
    try { lua.global.close(); console.log('close() ok'); } catch (e) { console.log('close() threw:', String(e)); }
}
main().catch((e) => { console.error('FATAL', e); process.exit(1); });
```

出力（`FORCE_COLOR=0 node probe_a4a2.cjs`、exit 0）:

```
PANIC: unprotected error in call to Lua API (attempt to yield from outside a coroutine)
Aborted(native code called abort())
test_a2 (JS calls back into Lua via global.call, which yields): false | false
--- is the engine still usable after that? ---
doStringSync("return 1+1") = 2
close() ok
```

観測:

- JS 関数に `coroutine.yield` を渡して呼ぶと、Lua の通常のエラー `attempt to yield across a C-call boundary` になり `coroutine.resume` が `false` を返す（プロセスは無事）。
- JS から `global.call` で Lua に再入した先で yield すると **wasm 側が `PANIC` して `abort()`** を呼ぶ（stderr に `PANIC: unprotected error in call to Lua API (attempt to yield from outside a coroutine)` と `Aborted(native code called abort())`）。`global.call` は `lua_State` の主スレッドで動くため「コルーチンの外」と判定される。resume の戻りは `false | false`（エラーメッセージが `false`）。この試行では engine はその後も `1+1` を評価できたが、abort を経た状態で使い続けるのは前提にできない。
- 結論: **ホスト（JS）を跨いだ yield は不可。yield は純 Lua のコルーチンの中に閉じる必要がある（A.4(b)）。**

#### A.4(b): 純 Lua スケジューラを JS から `tick()` で 3 回進める

スクリプト（`probe_a.cjs` 抜粋）:

```js
lua.doStringSync(`
    local co = coroutine.create(function()
        for i = 1, 3 do
            coroutine.yield("step-" .. i)
        end
        return "finished"
    end)
    function tick()
        local ok, v = coroutine.resume(co)
        return {ok = ok, value = v, status = coroutine.status(co)}
    end
`);
for (let i = 0; i < 4; i++) {
    console.log(`tick ${i + 1}:`, JSON.stringify(lua.global.call('tick')[0]));
}
```

出力:

```
=== A.4(b) pure-Lua scheduler, tick() from JS x3 ===
tick 1: {"ok":true,"value":"step-1","status":"suspended"}
tick 2: {"ok":true,"value":"step-2","status":"suspended"}
tick 3: {"ok":true,"value":"step-3","status":"suspended"}
tick 4: {"ok":true,"value":"finished","status":"dead"}
```

観測: `global.call` を跨いでも Lua 側のコルーチンは中断点を保持し、3 回の tick でそれぞれ `step-1` / `step-2` / `step-3` を返した。4 回目で本体が return し `dead` になる。

### A.5 数値の意味論

スクリプト（`probe_a.cjs` 抜粋。64 bit 整数は JS に出すと壊れるので Lua 内で文字列化）:

```js
console.log(lua.doStringSync(`
    return table.concat({
        "math.type(1)=" .. math.type(1),
        "math.type(1.0)=" .. math.type(1.0),
        "1//2=" .. tostring(1//2) .. " (" .. math.type(1//2) .. ")",
        "2^63=" .. tostring(2^63) .. " (" .. math.type(2^63) .. ") %.17g=" .. string.format("%.17g", 2^63),
        "math.maxinteger=" .. tostring(math.maxinteger),
        "math.mininteger=" .. tostring(math.mininteger),
        "maxinteger+1=" .. tostring(math.maxinteger + 1),
        "3/2=" .. tostring(3/2) .. " (" .. math.type(3/2) .. ")",
        "4/2=" .. tostring(4/2) .. " (" .. math.type(4/2) .. ")",
        "1e15//1=" .. tostring(1e15//1) .. " (" .. math.type(1e15//1) .. ")",
    }, "\\n")
`));
console.log('--- same values crossing into JS ---');
const nums = lua.doStringSync('return {one = 1, onef = 1.0, maxint = math.maxinteger, big = 2^53 + 1, p63 = 2^63}')
console.log('JSON.stringify:', JSON.stringify(nums));
console.log('maxint === 9223372036854775807 ?', nums.maxint === 9223372036854775807, 'Number.isSafeInteger:', Number.isSafeInteger(nums.maxint));
console.log('JS -> Lua: math.type of a JS 1 and JS 1.5:', lua.doStringSync('return function(a, b) return math.type(a) .. "," .. math.type(b) end')(1, 1.5));
```

出力:

```
=== A.5 number semantics (strings built inside Lua) ===
math.type(1)=integer
math.type(1.0)=float
1//2=0 (integer)
2^63=9.2233720368548e+18 (float) %.17g=9.2233720368547758e+18
math.maxinteger=9223372036854775807
math.mininteger=-9223372036854775808
maxinteger+1=-9223372036854775808
3/2=1.5 (float)
4/2=2.0 (float)
1e15//1=1e+15 (float)
--- same values crossing into JS ---
JSON.stringify: {"maxint":9223372036854776000,"one":1,"big":9007199254740992,"p63":9223372036854776000,"onef":1}
maxint === 9223372036854775807 ? true Number.isSafeInteger: false
JS -> Lua: math.type of a JS 1 and JS 1.5: integer,float
```

観測:

- `math.type(1)` は `integer`、`math.type(1.0)` は `float`。`1//2` は integer の `0`。`2^63` は float（`9.2233720368547758e+18`）。
- `math.maxinteger` は `9223372036854775807`（64 bit）。`maxinteger + 1` はラップして `mininteger` になる。
- **JS へ渡すと `math.maxinteger` は `9223372036854776000` に丸まる**（JS の `===` は同じく丸まったリテラルと比較して true になるだけで、`Number.isSafeInteger` は false）。`2^53 + 1` も `9007199254740992` に落ちる。
- JS の整数値 `1` は Lua 側で `integer`、`1.5` は `float` として入る（JS→Lua は整数判定、Lua→JS は区別消失）。

### A.6 `pairs` の順序

スクリプト（`probe_a.cjs` 抜粋）:

```js
const pairsSrc = `
    function pairs_order()
        local t = {b = 1, a = 2, c = 3}
        local ks = {}
        for k in pairs(t) do ks[#ks + 1] = k end
        return table.concat(ks, ",")
    end
`;
lua.doStringSync(pairsSrc);
for (let i = 0; i < 3; i++) console.log('engine1 run', i + 1, ':', lua.global.call('pairs_order')[0]);
const lua2 = await factory.createEngine({ openStandardLibs: true });
lua2.doStringSync(pairsSrc);
for (let i = 0; i < 3; i++) console.log('engine2 (same factory) run', i + 1, ':', lua2.global.call('pairs_order')[0]);
lua2.global.close();
const lua3 = await new LuaFactory().createEngine({ openStandardLibs: true });
lua3.doStringSync(pairsSrc);
for (let i = 0; i < 3; i++) console.log('engine3 (new factory) run', i + 1, ':', lua3.global.call('pairs_order')[0]);
console.log('engine3 fresh table literal each call, 5 keys:', lua3.doStringSync(`
    local out = {}
    for n = 1, 3 do
        local t = {b=1, a=2, c=3, d=4, e=5}
        local ks = {}
        for k in pairs(t) do ks[#ks+1] = k end
        out[n] = table.concat(ks, ",")
    end
    return table.concat(out, " | ")
`));
```

`probe_a.cjs` を 3 回実行したときの出力（3 回とも別プロセス。engine1 は A.3〜A.5 を先に実行済みの engine）:

1 回目:

```
engine1 run 1 : a,b,c
engine1 run 2 : a,b,c
engine1 run 3 : a,b,c
engine2 (same factory) run 1 : c,a,b
engine2 (same factory) run 2 : c,a,b
engine2 (same factory) run 3 : c,a,b
engine3 (new factory) run 1 : a,b,c
engine3 (new factory) run 2 : a,b,c
engine3 (new factory) run 3 : a,b,c
engine3 fresh table literal each call, 5 keys: e,c,d,a,b | e,c,d,a,b | e,c,d,a,b
```

2 回目:

```
engine1 run 1 : c,b,a
engine1 run 2 : c,b,a
engine1 run 3 : c,b,a
engine2 (same factory) run 1 : a,b,c
engine2 (same factory) run 2 : a,b,c
engine2 (same factory) run 3 : a,b,c
engine3 (new factory) run 1 : c,b,a
engine3 (new factory) run 2 : c,b,a
engine3 (new factory) run 3 : c,b,a
engine3 fresh table literal each call, 5 keys: c,b,e,d,a | c,b,e,d,a | c,b,e,d,a
```

3 回目（`out_a.txt` に残っている最終実行）:

```
=== A.6 pairs order {b=1,a=2,c=3} ===
engine1 run 1 : a,b,c
engine1 run 2 : a,b,c
engine1 run 3 : a,b,c
engine2 (same factory) run 1 : a,b,c
engine2 (same factory) run 2 : a,b,c
engine2 (same factory) run 3 : a,b,c
engine3 (new factory) run 1 : a,b,c
engine3 (new factory) run 2 : a,b,c
engine3 (new factory) run 3 : a,b,c
engine3 fresh table literal each call, 5 keys: d,e,b,c,a | d,e,b,c,a | d,e,b,c,a
```

追試 1（`probe_a6.cjs`: engine を 1 つずつ作って閉じる × 3、を 8 プロセス）:

```js
const factory = new LuaFactory();
const out = [];
for (let e = 1; e <= 3; e++) {
    const lua = await factory.createEngine({ openStandardLibs: true });
    lua.doStringSync(src);
    const runs = [];
    for (let i = 0; i < 3; i++) runs.push(lua.global.call('pairs_order')[0]);
    out.push(`engine${e}: ${runs.join(' / ')}`);
    lua.global.close();
}
console.log(`pid ${process.pid}: ${out.join(' | ')}`);
```

```
pid 172252: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172259: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172266: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172273: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172280: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172287: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172294: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
pid 172301: engine1: a,b,c / a,b,c / a,b,c | engine2: a,b,c / a,b,c / a,b,c | engine3: a,b,c / a,b,c / a,b,c
```

追試 2（`probe_a6b.cjs`: engine を閉じずに同時に 4 つ作る / 1.1 秒あけて作り直す）:

```js
console.log('--- 4 engines created back-to-back, all kept alive (different lua_State addresses) ---');
const alive = [];
for (let e = 1; e <= 4; e++) {
    const lua = await factory.createEngine({ openStandardLibs: true });
    lua.doStringSync(src);
    alive.push(lua);
    console.log(`engine${e} (alive, addr ${lua.global.address}): ${lua.global.call('pairs_order')[0]} | 5 keys: ${lua.global.call('pairs_order5')[0]}`);
}
for (const lua of alive) lua.global.close();
console.log('--- 4 engines created 1.1 s apart, each closed before the next (same address, different time seed) ---');
for (let e = 1; e <= 4; e++) {
    const lua = await factory.createEngine({ openStandardLibs: true });
    lua.doStringSync(src);
    console.log(`engine${e} (t=${Math.floor(Date.now() / 1000)}, addr ${lua.global.address}): ${lua.global.call('pairs_order')[0]} | 5 keys: ${lua.global.call('pairs_order5')[0]}`);
    lua.global.close();
    await sleep(1100);
}
```

```
--- 4 engines created back-to-back, all kept alive (different lua_State addresses) ---
engine1 (alive, addr 1083932): a,b,c | 5 keys: e,a,b,c,d
engine2 (alive, addr 1110604): c,a,b | 5 keys: e,c,d,a,b
engine3 (alive, addr 1137044): b,c,a | 5 keys: a,b,c,d,e
engine4 (alive, addr 1163484): a,c,b | 5 keys: e,d,a,c,b
--- 4 engines created 1.1 s apart, each closed before the next (same address, different time seed) ---
engine1 (t=1789272017, addr 1083932): a,b,c | 5 keys: e,a,b,c,d
engine2 (t=1789272019, addr 1083932): b,c,a | 5 keys: a,b,c,d,e
engine3 (t=1789272020, addr 1083932): b,c,a | 5 keys: a,b,c,d,e
engine4 (t=1789272021, addr 1083932): a,c,b | 5 keys: a,c,b,e,d
```

観測:

- **同じ engine の中では `pairs` の順序は何度呼んでも同じ**（毎回 table リテラルを作り直しても同じ）。
- **engine を跨ぐと順序は保証されない。** 実測では (1) engine を閉じずに同時に作る（`lua_State` のアドレスが変わる）、(2) 同じアドレスでも 1 秒以上あけて作り直す、のどちらでも順序が変わった。これは Lua 5.4 のソース上の仕様（`lstate.c` の `luai_makeseed` が `time(NULL)` と `lua_State` などのアドレスから文字列ハッシュのシードを作る）と整合するが、シードの作り方自体は今回の実測対象ではない。
- 追試 1 の 8 プロセス × 3 engine が 3 キーでは全部 `a,b,c` だった一方、追試 2 では同じ作り方の engine が `a,b,c` / `b,c,a` / `a,c,b` と割れた。3 キーの順列は 6 通りしかないので、シードが違っても同じ 3 キー順に当たることは珍しくない。同じ 3 キー順でも 5 キーでは違う例が A.6 本体にある（1 回目の engine3 は `a,b,c` で 5 キーが `e,c,d,a,b`、3 回目の engine3 は同じ `a,b,c` で 5 キーが `d,e,b,c,a`）。「3 キーで同じだったこと」を安定の根拠にはできない。
- 出所の注記: A.6 本体の「1 回目」「2 回目」の出力は `probe_a.cjs` を再実行するたびに `out_a.txt` が上書きされたため、セッションログからの転記である。ディスクに残っているのは「3 回目」（`out_a.txt`）と追試 1 / 2（`out_a6.txt` / `out_a6b.txt`）。
- 設計上の含意: **`pairs` の順序を出力の決定性に使ってはいけない。** キーを `table.sort` してから走査するか、配列（`ipairs`）で持つ。

### A.7 `utf8.len`

スクリプト（`probe_a.cjs` 抜粋）:

```js
console.log('utf8.len("あいう") =', lua.doStringSync('return utf8.len("あいう")'));
console.log('utf8.len("\\u{3042}\\u{3044}\\u{3046}") =', lua.doStringSync('return utf8.len("\\u{3042}\\u{3044}\\u{3046}")'));
console.log('#"あいう" (bytes) =', lua.doStringSync('return #"あいう"'));
console.log('JS string round trip length:', lua.doStringSync('return function(s) return utf8.len(s) .. "/" .. #s end')('あいう'));
```

出力:

```
=== A.7 utf8.len ===
utf8.len("あいう") = 3
utf8.len("\u{3042}\u{3044}\u{3046}") = 3
#"あいう" (bytes) = 9
JS string round trip length: 3/9
```

観測: `utf8.len("あいう")` は `3`。`#` はバイト長 `9`。JS の文字列を引数で渡しても UTF-8 として入る（3/9）。

### A.8 既定のグローバルと削除

スクリプト（`probe_a8.cjs` 抜粋）:

```js
const lua = await factory.createEngine({ openStandardLibs: true });
console.log(lua.doStringSync(`
    return "require=" .. type(require) .. " load=" .. type(load) .. " loadstring=" .. type(loadstring) ..
           " dofile=" .. type(dofile) .. " loadfile=" .. type(loadfile) ..
           " os=" .. type(os) .. " io=" .. type(io) .. " debug=" .. type(debug) .. " package=" .. type(package) ..
           " os.execute=" .. type(os and os.execute) .. " io.open=" .. type(io and io.open) ..
           " os.exit=" .. type(os and os.exit) .. " os.getenv=" .. type(os and os.getenv)
`));
console.log('load("return 1")() before removal:', lua.doStringSync('return load("return 1")()'));

try {
    lua.global.set('load', null);
    console.log('set(null) ok; type(load) =', lua.doStringSync('return type(load)'));
} catch (e) {
    console.log('set("load", null) threw:', String(e));
    console.log('stack top frames:', e.stack.split('\n').slice(0, 3).join(' / '));
}
console.log('type(load) after the failed set:', lua.doStringSync('return type(load)'));

try {
    lua.global.set('load', undefined);
    console.log('set(undefined) ok; type(load) =', lua.doStringSync('return type(load)'));
} catch (e) { console.log('set("load", undefined) threw:', String(e)); }
try {
    console.log('load("return 1")() after undefined:', lua.doStringSync('return load("return 1")()'));
} catch (e) { console.log('load after undefined threw:', String(e)); }

lua.global.set('os', undefined);
lua.global.set('io', undefined);
lua.global.set('require', undefined);
lua.doStringSync('dofile = nil; loadfile = nil; package = nil; debug = nil');
console.log(lua.doStringSync(`
    return "require=" .. type(require) .. " load=" .. type(load) .. " dofile=" .. type(dofile) .. " loadfile=" .. type(loadfile) ..
           " os=" .. type(os) .. " io=" .. type(io) .. " debug=" .. type(debug) .. " package=" .. type(package)
`));
try { lua.doStringSync('return os.time()'); } catch (e) { console.log('os.time() threw:', String(e)); }
try { lua.doStringSync('return io.open("/etc/hostname")'); } catch (e) { console.log('io.open() threw:', String(e)); }
try { lua.doStringSync('return require("x")'); } catch (e) { console.log('require("x") threw:', String(e)); }
console.log('string/table/math/utf8/coroutine still present:', lua.doStringSync(
    'return type(string) .. "," .. type(table) .. "," .. type(math) .. "," .. type(utf8) .. "," .. type(coroutine) .. "," .. type(pcall)'));
console.log('string.rep / string.format still work:', lua.doStringSync('return string.format("%d-%s", 7, string.rep("x", 3))'));

const lua4 = await factory.createEngine({ openStandardLibs: false });
// base library (type / tostring / pairs / print / pcall) is NOT opened either, so compare against nil and return booleans
const names = ['require', 'load', 'os', 'io', 'string', 'table', 'math', 'utf8', 'coroutine', 'pairs', 'print', 'pcall', 'type', 'tostring'];
const flags = lua4.doStringSync('return ' + names.map((n) => `${n} ~= nil`).join(', '));
console.log(names.map((n, i) => `${n}=${flags[i] ? 'present' : 'nil'}`).join(' '));
```

出力:

```
=== A.8 default globals with openStandardLibs:true ===
require=function load=function loadstring=nil dofile=function loadfile=function os=table io=table debug=table package=table os.execute=function io.open=function os.exit=function os.getenv=function
load("return 1")() before removal: 1

=== A.8 removal via lua.global.set("load", null) ===
set("load", null) threw: TypeError: Cannot read properties of null (reading 'then')
stack top frames: TypeError: Cannot read properties of null (reading 'then') /     at PromiseTypeExtension.pushValue (/home/wisteria/.claude/jobs/8e42df6b/tmp/probe/node_modules/wasmoon/dist/index.js:916:102) /     at /home/wisteria/.claude/jobs/8e42df6b/tmp/probe/node_modules/wasmoon/dist/index.js:244:82
type(load) after the failed set: function

=== A.8 removal via lua.global.set("load", undefined) ===
set(undefined) ok; type(load) = nil
load after undefined threw: Error: [string "return load("return 1")()"]:1: attempt to call a nil value (global 'load')

=== A.8 removal of os / io / require / dofile / loadfile via set(undefined) and Lua nil ===
require=nil load=nil dofile=nil loadfile=nil os=nil io=nil debug=nil package=nil
os.time() threw: Error: [string "return os.time()"]:1: attempt to index a nil value (global 'os')
io.open() threw: Error: [string "return io.open("/etc/hostname")"]:1: attempt to index a nil value (global 'io')
require("x") threw: Error: [string "return require("x")"]:1: attempt to call a nil value (global 'require')
string/table/math/utf8/coroutine still present: table,table,table,table,table,function
string.rep / string.format still work: 7-xxx

=== A.8 engine with openStandardLibs:false ===
require=nil load=nil os=nil io=nil string=nil table=nil math=nil utf8=nil coroutine=nil pairs=nil print=nil pcall=nil type=nil tostring=nil
```

観測:

- `openStandardLibs: true` では `require` / `load` / `dofile` / `loadfile` / `os`（`execute` / `exit` / `getenv` 込み）/ `io`（`open` 込み）/ `debug` / `package` が**すべて有効**。`loadstring` は無い（5.4 なので当然）。
- **`lua.global.set('load', null)` は wasmoon 1.16.0 のバグで失敗する**（`null` が `PromiseTypeExtension.pushValue` に流れて `null.then` を読む）。`load` は残ったまま。
- `lua.global.set('load', undefined)`（または Lua 側で `load = nil`）なら消え、以後の呼び出しは `attempt to call a nil value (global 'load')`。`os` / `io` / `require` も同様に消せる。`string` / `table` / `math` / `utf8` / `coroutine` / `pcall` は残る。
- `openStandardLibs: false` は **base ライブラリごと開かない**ので `type` / `tostring` / `pairs` / `print` / `pcall` / `string` / `table` も nil。`global.loadLibrary(LuaLibraries.Base)` 等で必要なものだけ足す設計になる（型定義 `global.d.ts` の `loadLibrary(library: LuaLibraries)`）。
- 削除は「グローバル名を消す」だけで、`debug` などを先に別名で退避されていれば戻せる。サンドボックスとしては `openStandardLibs: false` + 必要ライブラリの明示ロードの方が閉じている。

### A.9 `global.call('tick')` の往復時間（50 個の小配列、1000 回平均）

スクリプト（`probe_a8.cjs` 抜粋）:

```js
lua.doStringSync(`
    function tick50()
        local ops = {}
        for i = 1, 50 do ops[i] = {"rect", i, i * 2.0, 10, 20} end
        return ops
    end
`);
for (let i = 0; i < 100; i++) lua.global.call('tick50');   // warmup
const N = 1000;
for (let round = 1; round <= 3; round++) {
    const t0 = performance.now();
    let last;
    for (let i = 0; i < N; i++) last = lua.global.call('tick50')[0];
    const t1 = performance.now();
    console.log(`round ${round}: result length ${last.length}, sample ${JSON.stringify(last[0])}, total ${(t1 - t0).toFixed(2)} ms, avg ${((t1 - t0) / N * 1000).toFixed(1)} us per call`);
}
lua.doStringSync('function tick0() return 1 end');
for (let i = 0; i < 100; i++) lua.global.call('tick0');
const b0 = performance.now();
for (let i = 0; i < N; i++) lua.global.call('tick0');
const b1 = performance.now();
console.log(`tick0: total ${(b1 - b0).toFixed(2)} ms, avg ${((b1 - b0) / N * 1000).toFixed(1)} us per call`);
```

出力:

```
=== A.9 global.call("tick50") returning 50 small arrays, 1000 calls ===
round 1: result length 50, sample ["rect",1,2,10,20], total 602.45 ms, avg 602.4 us per call
round 2: result length 50, sample ["rect",1,2,10,20], total 595.68 ms, avg 595.7 us per call
round 3: result length 50, sample ["rect",1,2,10,20], total 607.24 ms, avg 607.2 us per call
--- baseline: global.call of a function returning a single integer ---
tick0: total 1.04 ms, avg 1.0 us per call
```

追加計測（`probe_a9x.cjs`: 同じ 50 行 × 5 値を返す形を変えたとき）:

```js
const lua = await new LuaFactory().createEngine({ openStandardLibs: true });
lua.doStringSync(`
    function nested()
        local ops = {}
        for i = 1, 50 do ops[i] = {"rect", i, i * 2.0, 10, 20} end
        return ops
    end
    function flat()
        local ops = {}
        for i = 1, 50 do
            local b = (i - 1) * 5
            ops[b + 1] = "rect"; ops[b + 2] = i; ops[b + 3] = i * 2.0; ops[b + 4] = 10; ops[b + 5] = 20
        end
        return ops
    end
    function flat_numbers_only()
        local ops = {}
        for i = 1, 50 do
            local b = (i - 1) * 5
            ops[b + 1] = 1; ops[b + 2] = i; ops[b + 3] = i * 2.0; ops[b + 4] = 10; ops[b + 5] = 20
        end
        return ops
    end
    function json_string()
        local parts = {}
        for i = 1, 50 do parts[i] = string.format('["rect",%d,%.17g,10,20]', i, i * 2.0) end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    function ten_rows()
        local ops = {}
        for i = 1, 10 do ops[i] = {"rect", i, i * 2.0, 10, 20} end
        return ops
    end
`);
const N = 1000;
for (const name of ['nested', 'flat', 'flat_numbers_only', 'json_string', 'ten_rows']) {
    for (let i = 0; i < 100; i++) lua.global.call(name);
    const t0 = performance.now();
    let last;
    for (let i = 0; i < N; i++) last = lua.global.call(name)[0];
    const t1 = performance.now();
    const desc = typeof last === 'string' ? `string length ${last.length}` : `array length ${last.length}`;
    console.log(`${name}: ${desc}, total ${(t1 - t0).toFixed(2)} ms, avg ${((t1 - t0) / N * 1000).toFixed(1)} us per call`);
}
const t0 = performance.now();
let parsed;
for (let i = 0; i < N; i++) parsed = JSON.parse(lua.global.call('json_string')[0]);
const t1 = performance.now();
console.log(`json_string + JSON.parse: rows ${parsed.length}, total ${(t1 - t0).toFixed(2)} ms, avg ${((t1 - t0) / N * 1000).toFixed(1)} us per call`);
console.log('--- JS -> Lua direction: passing 50 rows as argument, Lua returns #arg ---');
lua.doStringSync('function count(rows) return #rows end');
const rows = [];
for (let i = 1; i <= 50; i++) rows.push(['rect', i, i * 2.0, 10, 20]);
for (let i = 0; i < 100; i++) lua.global.call('count', rows);
const c0 = performance.now();
let cnt;
for (let i = 0; i < N; i++) cnt = lua.global.call('count', rows)[0];
const c1 = performance.now();
console.log(`count(rows): returned ${cnt}, total ${(c1 - c0).toFixed(2)} ms, avg ${((c1 - c0) / N * 1000).toFixed(1)} us per call`);
```

```
nested: array length 50, total 638.10 ms, avg 638.1 us per call
flat: array length 250, total 457.90 ms, avg 457.9 us per call
flat_numbers_only: array length 250, total 453.01 ms, avg 453.0 us per call
json_string: string length 1039, total 26.82 ms, avg 26.8 us per call
ten_rows: array length 10, total 121.09 ms, avg 121.1 us per call
json_string + JSON.parse: rows 50, total 35.48 ms, avg 35.5 us per call
--- JS -> Lua direction: passing 50 rows as argument, Lua returns #arg ---
count(rows): returned 50, total 12.86 ms, avg 12.9 us per call
```

観測:

- 50 個の小配列（250 値 + 50 table）を Lua→JS に変換する往復は **約 600 µs/回**。呼び出し自体は 1 µs なので、ほぼ全部が table→JS object の変換コスト（値 1 個あたり約 1.8 µs、10 行なら 121 µs と行数に比例）。
- **Lua 側で JSON 文字列に組んで 1 本の string で返し JS で `JSON.parse` すると 35.5 µs/回**（約 17 倍速い）。
- JS→Lua 方向（50 行を引数で渡す）は 12.9 µs/回で、Lua→JS の逆方向より大幅に軽い（JS の object は proxy userdata として渡され、深いコピーをしないため。A.3 の `got_kind = "userdata"` と整合）。
- 60 fps（16.7 ms/フレーム）で毎フレーム描画命令列を受け取る用途なら、nested table 経由でも 50 行は収まるが、数百行になると変換だけでフレーム予算を食う。文字列（JSON または独自の平坦なエンコード）で受ける設計が有利。

### A.10（追加・Phase 4）命令数の上限をコルーチンに効かせる経路 / `game.lua` の通し / JS→Lua の数値

Phase 4（2026-09-13）で `apps/player` を書く前に実測した。スクリプトは `probe_p4.cjs` / `probe_p4b.cjs` /
`probe_p4c.cjs` / `probe_p4d.cjs`、生出力は `out_p4.txt` / `out_p4b.txt` / `out_p4c.txt` / `out_p4d.txt`。

**(1) Lua の関数で掛ける count hook は、`global.call` で叩いた Lua のグローバル関数からなら効く。JS ラッパ経由では効かない**（`probe_p4b.cjs`）:

```
(a) busy via global.call after global.call(arm): false|budget
```

`(a)` に続く `busy_co`（`coroutine.create` した中の `while true`）で**プロセスが止まった**（出力なし。5 秒の見張りも
Lua が回り続けて発火しない）。`global.get('__jin_arm')` で JS の関数にしてから呼ぶ (b) も止まった（`probe_p4.cjs` の初版）。
→ **hook は Lua のグローバル関数を `global.call` で呼ぶ形でだけ掛け、コルーチンには届かない**。

**(2) wasmoon の `Thread.setTimeout`（C の hook）はメインスレッドでは効くが、コルーチンの中で PANIC する**（`probe_p4c.cjs`）:

```
(c) busy: false|userdata|Error: thread timeout exceeded ms 302
PANIC: unprotected error in call to Lua API (error object is not a string)
Aborted(native code called abort())
FATAL RuntimeError: Aborted(native code called abort())
```

→ `setTimeout` / `functionTimeout` は使わない（プレイヤーの契約テストが `setTimeout(` の不在を走査する）。

**(3) コルーチンごとに `debug.sethook(co, f, "", n)` を掛ければ届く。ホストが `JIN_ARM` / `JIN_HOOK` を置き、JIL を読んだ後に消す形**（`probe_p4d.cjs`。lupa の §B.8 と同じ Lua）:

```js
lua.doStringSync(`
local sethook = debug.sethook
local limit = 1000
local function over() error({ code = "budget", message = "命令数の上限 " .. limit .. " を超えました（無限ループ？）" }, 0) end
JIN_ARM = function() sethook(over, "", limit) end
JIN_HOOK = function(co) sethook(co, over, "", limit) end
`);
lua.global.set('debug', undefined);
lua.doStringSync(`local ARM, HOOK = JIN_ARM, JIN_HOOK  … function busy_co() if ARM then ARM() end … HOOK(co) … coroutine.resume(co) … end …`);
lua.global.set('JIN_ARM', undefined);
lua.global.set('JIN_HOOK', undefined);
```

```
type(JIN_ARM) after load: nil
busy: false|budget
busy_co: false|budget:命令数の上限 1000 を超えました（無限ループ？）
wait_co (5 yields of 300 iters each, limit 1000): false:budget,false:cannot resume dead coroutine,…
main_after_co: false|budget
```

観測: メインスレッド（`busy`）もコルーチン（`busy_co`）も `budget` で止まる。読み込み後に `JIN_ARM` / `JIN_HOOK` を消しても、
プレリュードが `local` に捕まえた関数は生きる。`wait_co` の 1 回目で止まったのは 300 回のループが約 1,200 命令で
上限 1,000 を超えたため（掛け直しの検証は lupa 側 §B.8 と `packages/jin-wasm/tests/test_runtime.py` の変異で行った）。

**(4) `game.lua`（paddle・debug）を `doStringSync` → `boot` → `tick` × 1204 で通す**（`probe_p4.cjs`）:

```
debug after: nil
number types (t=3, seed=7, x=150, y=1.5, ev.x=12): integer/integer/integer/float/integer/1/true
doStringSync(game.lua) returns: object [ 'tick', 'boot' ]
type(boot)/type(tick): function/function
boot -> []
tick 0 typeof string len 2770 head {"ops":[["clear","#000"],["ink","#fff"],["rect",143,172,40,4],["circle",161.5,41.166666666666664,3],
  ops 5 done false trace 17 public {"Play.score":0,"Result.quit":false} error null
tick 1 typeof string len 2076 …  ops 5 done false trace 12 public {"Play.score":0,"Result.quit":false} error null
tick 2 typeof string len 2085 …  ops 5 done false trace 12 public {"Play.score":0,"Result.quit":false} error null
tick 3 (empty events / keys) ops: 5
600 ticks ms (arm + tick + no parse): 124
600 ticks ms (with JSON.parse): 87
```

観測:

- `doStringSync(game.lua)` は末尾の `return { boot = boot, tick = tick }` を JS の object で返し、`boot` / `tick` はグローバルにもある。
  プレイヤーは戻り値を捨て、`global.call('boot', seed, manifest)` / `global.call('tick', t, inputs)` を使う（戻りは `MultiReturn`。`[0]` が JSON 文字列）
- JS の object / array は Lua の table になる（`#inputs.events == 1`、`inputs.keys.ArrowRight == true`）
- **JS→Lua の数値は `Number.isInteger(v)` なら `lua_pushinteger`、それ以外は `lua_pushnumber`**（`index.js` の `pushValue`。`x=150` → `integer`、`y=1.5` → `float`）。
  lupa は Python の `float` を float のまま渡す（`InputState.apply` は `float()` に揃える）ので、ホスト間で `inputs` の数値の副型が違う。
  プレリュードは `pointer` / イベントの `x` / `y` を読む 3 か所すべてで `+ 0.0` して float に揃えているため（`prelude.lua` の `PTR` / `prepare_inputs` / `dispatch_events`）、
  トレース・表示リストには差が出ない。`t` / `seed` は両ホストとも整数
- 1 tick は約 0.2 ms（60 fps の 16.7 ms に対して 1% 強）

---

## B. lupa

### B.1 版

スクリプト（`probe_b.py` 抜粋）:

```python
import sys, lupa, lupa.lua54
from lupa.lua54 import LuaRuntime, lua_type
print("python", sys.version.split()[0])
print("lupa.__version__ =", lupa.__version__)
print("import lupa.lua54 ->", lupa.lua54)
rt = LuaRuntime()
print("LuaRuntime().lua_version =", rt.lua_version)
print("_VERSION =", rt.eval("_VERSION"))
print("lupa.LUA_VERSION (default module) =", getattr(lupa, "LUA_VERSION", None))
print("lupa.LuaRuntime is lupa.lua54.LuaRuntime ?", lupa.LuaRuntime is lupa.lua54.LuaRuntime)
print("default lupa.LuaRuntime().lua_version =", lupa.LuaRuntime().lua_version, "| _VERSION =", lupa.LuaRuntime().eval("_VERSION"))
print("bundled Lua modules:", [n for n in dir(lupa) if n.startswith("lua")])
```

出力（`uv run --with lupa python /home/wisteria/.claude/jobs/8e42df6b/tmp/probe/probe_b.py`）:

```
=== B.1 version ===
python 3.14.7
lupa.__version__ = 2.8
import lupa.lua54 -> <module 'lupa.lua54' from '/home/wisteria/.cache/uv/archive-v0/fDHCKzDWH0eLBevB/lib/python3.14/site-packages/lupa/lua54.cpython-314-x86_64-linux-gnu.so'>
LuaRuntime().lua_version = (5, 4)
_VERSION = Lua 5.4
lupa.LUA_VERSION (default module) = (5, 5)
lupa.LuaRuntime is lupa.lua54.LuaRuntime ? False
default lupa.LuaRuntime().lua_version = (5, 5) | _VERSION = Lua 5.5
bundled Lua modules: ['lua54', 'lua55']
```

同梱バイナリとパッチ版（`strings` で確認）:

```
$ strings .../site-packages/lupa/lua54.cpython-314-x86_64-linux-gnu.so | grep -E "Lua 5\.[0-9]\.[0-9]"
$LuaVersion: Lua 5.4.8  Copyright (C) 1994-2025 Lua.org, PUC-Rio $$LuaAuthors: R. Ierusalimschy, L. H. de Figueiredo, W. Celes $
$ strings .../site-packages/lupa/lua55.cpython-314-x86_64-linux-gnu.so | grep -E "Lua 5\.[0-9]\.[0-9]"
$LuaVersion: Lua 5.5.1  Copyright (C) 1994-2026 Lua.org, PUC-Rio $$LuaAuthors: R. Ierusalimschy, L. H. de Figueiredo, W. Celes $
$ ls -la .../site-packages/lupa/ | grep -E "\.so"
-rwxr-xr-x 2 wisteria wisteria  557872 Sep 13 12:54 lua51.cpython-314-x86_64-linux-gnu.so
-rwxr-xr-x 2 wisteria wisteria  582544 Sep 13 12:54 lua52.cpython-314-x86_64-linux-gnu.so
-rwxr-xr-x 2 wisteria wisteria  619376 Sep 13 12:54 lua53.cpython-314-x86_64-linux-gnu.so
-rwxr-xr-x 2 wisteria wisteria  672688 Sep 13 12:54 lua54.cpython-314-x86_64-linux-gnu.so
-rwxr-xr-x 2 wisteria wisteria  693168 Sep 13 12:54 lua55.cpython-314-x86_64-linux-gnu.so
-rwxr-xr-x 2 wisteria wisteria  987872 Sep 13 12:54 luajit20.cpython-314-x86_64-linux-gnu.so
-rwxr-xr-x 2 wisteria wisteria 1106912 Sep 13 12:54 luajit21.cpython-314-x86_64-linux-gnu.so
```

観測:

- `lupa 2.8`。`import lupa.lua54` は通り、`LuaRuntime().lua_version == (5, 4)`、`_VERSION == "Lua 5.4"`（バイナリは Lua 5.4.8）。
- **`import lupa; lupa.LuaRuntime()` の既定は Lua 5.5.1** で、`lupa.lua_type` / `lupa.LuaError` などのモジュール直下の名前も 5.5 用のもの。wasmoon（5.4）と揃えるなら **`lupa.lua54` を明示して import し、`lua_type` も `lupa.lua54.lua_type` を使う**（B.5 で `lupa.lua_type(t54)` が `None` を返すことを実測した）。
- `dir(lupa)` に出るのは import 済みの `lua54` / `lua55` だけだが、wheel には lua51 / 52 / 53 / 54 / 55 / luajit20 / luajit21 の 7 本が同梱されている。

### B.2 `register_eval=False` と `load` / `os` / `io` / `require` の nil 化

スクリプト（`probe_b.py` 抜粋）:

```python
lua = LuaRuntime(register_eval=False, unpack_returned_tuples=True)
print("before removal:", lua.eval(
    '"require=" .. type(require) .. " load=" .. type(load) .. " dofile=" .. type(dofile) .. " loadfile=" .. type(loadfile)'
    ' .. " os=" .. type(os) .. " io=" .. type(io) .. " debug=" .. type(debug) .. " package=" .. type(package)'
    ' .. " python=" .. type(python)'))
g = lua.globals()
g.load = None
g.os = None
g.io = None
g.require = None
print("after removal:", lua.eval(
    '"require=" .. type(require) .. " load=" .. type(load) .. " os=" .. type(os) .. " io=" .. type(io)'))
for label, code in [("load", 'load("return 1")()'), ("os.time", "os.time()"),
                    ("io.open", 'io.open("/etc/hostname")'), ("require", 'require("x")')]:
    try:
        print(f"{label}: unexpectedly returned", lua.eval(code))
    except lupa.LuaError as e:
        print(f"{label} -> LuaError: {e}")
    except Exception as e:
        print(f"{label} -> {type(e).__name__}: {e}")

print("--- 'python' global left behind by lupa (not requested, but relevant to sandboxing) ---")
print("type(python) =", lua.eval("type(python)"))
print("type(python.eval) =", lua.eval("type(python.eval)"))
print("type(python.builtins) =", lua.eval("type(python.builtins)"))
print("type(python.import_module) =", lua.eval("type(python.import_module)"))
try:
    print("python.builtins.open exists? ->", lua.eval("python.builtins.open"))
except Exception as e:
    print("python.builtins.open ->", type(e).__name__, e)
try:
    print("python.import_module('os') ->", lua.eval("python.import_module('os')"))
except Exception as e:
    print("python.import_module('os') ->", type(e).__name__, e)
print("--- with register_builtins=False as well ---")
lua_nb = LuaRuntime(register_eval=False, register_builtins=False, unpack_returned_tuples=True)
print("type(python) =", lua_nb.eval("type(python)"))
print("type(python.builtins) =", lua_nb.eval("type(python.builtins)"))
print("type(python.eval) =", lua_nb.eval("type(python.eval)"))
print("type(python.import_module) =", lua_nb.eval("type(python.import_module)"))
lua_nb.globals().python = None
print("after python=nil: type(python) =", lua_nb.eval("type(python)"))
```

出力:

```
=== B.2 register_eval=False + nil-ing load/os/io/require ===
before removal: require=function load=function dofile=function loadfile=function os=table io=table debug=table package=table python=table
after removal: require=nil load=nil os=nil io=nil
load -> LuaError: [string "<python>"]:1: attempt to call a nil value (global 'load')
stack traceback:
	[string "<python>"]:1: in main chunk
os.time -> LuaError: [string "<python>"]:1: attempt to index a nil value (global 'os')
stack traceback:
	[string "<python>"]:1: in main chunk
io.open -> LuaError: [string "<python>"]:1: attempt to index a nil value (global 'io')
stack traceback:
	[string "<python>"]:1: in main chunk
require -> LuaError: [string "<python>"]:1: attempt to call a nil value (global 'require')
stack traceback:
	[string "<python>"]:1: in main chunk
--- 'python' global left behind by lupa (not requested, but relevant to sandboxing) ---
type(python) = table
type(python.eval) = nil
type(python.builtins) = userdata
type(python.import_module) = nil
python.builtins.open exists? -> <built-in function open>
python.import_module('os') -> LuaError [string "<python>"]:1: attempt to call a nil value (field 'import_module')
stack traceback:
	[string "<python>"]:1: in main chunk
--- with register_builtins=False as well ---
type(python) = table
type(python.builtins) = nil
type(python.eval) = nil
type(python.import_module) = nil
after python=nil: type(python) = nil
```

観測:

- `lua.globals().load = None` などで 4 つとも nil になり、呼ぶと `LuaError` `attempt to call a nil value (global 'load')` / `attempt to index a nil value (global 'os')` 等になる（`dofile` / `loadfile` / `debug` / `package` は依頼範囲外なので残したまま。消すなら同様に代入する）。
- **依頼外だが設計に直結する点**: lupa は Lua 側に `python` テーブルを置く。`register_eval=False` は `python.eval` と `python.import_module` を消すが、**`python.builtins` は残り、`python.builtins.open` が Python の `open` そのもの**として見える。サンドボックスにするなら **`register_builtins=False` も付け、さらに `globals().python = None` で `python` テーブル自体を消す**（上の出力で nil になることを確認）。
- `attribute_filter` は Lua グローバルの削除とは別の層で、**Lua から Python オブジェクトの属性を読む/書くときに呼ばれるフック**。`LuaRuntime(attribute_filter=fn)` で受け付けられ、`fn(obj, attr_name, is_setting)` の形で呼ばれる。Lua 側の table には関わらない（`probe_b_attr.py` で実測）:

```python
def deny_all(obj, attr_name, is_setting):
    raise AttributeError(f"blocked: {type(obj).__name__}.{attr_name} setting={is_setting}")

lua = LuaRuntime(register_eval=False, register_builtins=False, unpack_returned_tuples=True, attribute_filter=deny_all)
lua.globals().python = None
print("kwargs accepted; type(python) =", lua.eval("type(python)"))
class Obj:
    x = 1
lua.globals().obj = Obj()
try:
    print("obj.x ->", lua.eval("obj.x"))
except Exception as e:
    print(f"obj.x -> {type(e).__name__}: {e}")
try:
    print("lua-side table.x ->", lua.eval("({x = 5}).x"))
except Exception as e:
    print(f"lua-side table.x -> {type(e).__name__}: {e}")
```

```
kwargs accepted; type(python) = nil
obj.x -> AttributeError: blocked: Obj.x setting=False
lua-side table.x -> 5
```

  フィルタが投げた例外は `LuaError` ではなく **Python の `AttributeError` のまま `lua.eval` の呼び出し元へ伝わる**（最初の実行で `except lupa.lua54.LuaError` では捕まらず traceback になった）。

### B.3 純 Lua スケジューラを Python から `tick()` で 3 回進める

スクリプト（`probe_b.py` 抜粋）:

```python
lua3 = LuaRuntime(register_eval=False, unpack_returned_tuples=True)
lua3.execute("""
    local co = coroutine.create(function()
        for i = 1, 3 do
            coroutine.yield("step-" .. i)
        end
        return "finished"
    end)
    function tick()
        local ok, v = coroutine.resume(co)
        return {ok = ok, value = v, status = coroutine.status(co)}
    end
""")
tick = lua3.globals().tick
for i in range(4):
    t = tick()
    print(f"tick {i + 1}:", dict(t.items()))

# variant: Python function called from Lua calls coroutine.yield
lua3.globals().pyfn = lambda y: y()
lua3.execute("""
    function test_a1()
        local co = coroutine.create(function() pyfn(coroutine.yield) return "done" end)
        local ok, err = coroutine.resume(co)
        return tostring(ok) .. " | " .. tostring(err)
    end
""")
print("test_a1:", lua3.globals().test_a1())
```

出力:

```
=== B.3 pure-Lua scheduler, tick() from Python x3 ===
tick 1: {'value': 'step-1', 'ok': True, 'status': 'suspended'}
tick 2: {'value': 'step-2', 'ok': True, 'status': 'suspended'}
tick 3: {'value': 'step-3', 'ok': True, 'status': 'suspended'}
tick 4: {'value': 'finished', 'ok': True, 'status': 'dead'}
--- B.3 variant: Python function called from Lua calls coroutine.yield (yield across Python boundary) ---
test_a1: false | attempt to yield across a C-call boundary
stack traceback:
	[string "<python>"]:3: in function <[string "<python>"]:3>
	[C]: in global 'pyfn'
	[C]: in function 'coroutine.yield'
```

観測: wasmoon と同じく、Python の呼び出しを跨いでも Lua のコルーチンは中断点を保持する。Python 関数の中から yield すると `attempt to yield across a C-call boundary`（Lua エラーとして捕捉可、abort はしない）。

### B.4 数値 / utf8 / pairs 順序

スクリプト（`probe_b.py` 抜粋）:

```python
lua4 = LuaRuntime(register_eval=False, unpack_returned_tuples=True)
print("math.type(1) =", lua4.eval("math.type(1)"))
print("math.type(1.0) =", lua4.eval("math.type(1.0)"))
print("1//2 =", lua4.eval("1//2"), "math.type(1//2) =", lua4.eval("math.type(1//2)"))
print("2^63 =", lua4.eval("2^63"), "math.type(2^63) =", lua4.eval("math.type(2^63)"), "tostring =", lua4.eval("tostring(2^63)"))
mi = lua4.eval("math.maxinteger")
print("math.maxinteger =", mi, type(mi).__name__, "== 2**63-1 ?", mi == 2**63 - 1)
print("tostring(math.maxinteger) =", lua4.eval("tostring(math.maxinteger)"))
print("Python 1 -> Lua math.type:", lua4.eval("function(a) return math.type(a) end")(1))
print("Python 1.0 -> Lua math.type:", lua4.eval("function(a) return math.type(a) end")(1.0))
print("Lua 1.0 -> Python:", repr(lua4.eval("1.0")), "| Lua 1 -> Python:", repr(lua4.eval("1")))
print('utf8.len("あいう") =', lua4.eval('utf8.len("あいう")'))
print('#"あいう" =', lua4.eval('#"あいう"'))
print("Python str 'あいう' -> Lua utf8.len/#:", lua4.eval("function(s) return utf8.len(s) .. '/' .. #s end")("あいう"))
pairs_src = """
    function pairs_order()
        local t = {b = 1, a = 2, c = 3}
        local ks = {}
        for k in pairs(t) do ks[#ks + 1] = k end
        return table.concat(ks, ",")
    end
"""
for n, rt_ in enumerate([lua4, LuaRuntime(register_eval=False, unpack_returned_tuples=True)], start=1):
    rt_.execute(pairs_src)
    print(f"runtime{n}:", " / ".join(rt_.globals().pairs_order() for _ in range(3)))
```

出力（2 回実行。数値・utf8 は同一、pairs だけ差がある）:

1 回目:

```
runtime1: a,b,c / a,b,c / a,b,c
runtime2: c,b,a / c,b,a / c,b,a
```

2 回目（`out_b.txt` に残っている最終実行）:

```
=== B.4 number semantics / utf8 / pairs order ===
math.type(1) = integer
math.type(1.0) = float
1//2 = 0 math.type(1//2) = integer
2^63 = 9.223372036854776e+18 math.type(2^63) = float tostring = 9.2233720368548e+18
math.maxinteger = 9223372036854775807 int == 2**63-1 ? True
tostring(math.maxinteger) = 9223372036854775807
Python 1 -> Lua math.type: integer
Python 1.0 -> Lua math.type: float
Lua 1.0 -> Python: 1.0 | Lua 1 -> Python: 1
utf8.len("あいう") = 3
#"あいう" = 9
Python str 'あいう' -> Lua utf8.len/#: 3/9
runtime1: b,a,c / b,a,c / b,a,c
runtime2: c,a,b / c,a,b / c,a,b
```

観測:

- `math.type(1)` `integer` / `math.type(1.0)` `float` / `1//2` は integer の `0` / `2^63` は float。`math.maxinteger` は **Python の `int` で `9223372036854775807` のまま届く**（wasmoon と違い 64 bit が保たれる）。
- Python の `1` は Lua で integer、`1.0` は float。Lua の `1.0` は Python の `float 1.0`、`1` は `int 1`（**往復で integer / float の区別が保たれる**）。
- `utf8.len("あいう")` は `3`、`#` は `9`。Python の `str` を渡しても UTF-8 として入る。
- **`pairs` 順序は runtime 内では安定、runtime を跨ぐと不定**（同一プロセスの 2 runtime でも別、実行ごとにも別）。wasmoon と同じ結論。

### B.5 Lua の table を Python で受ける

スクリプト（`probe_b.py` 抜粋）:

```python
lua5 = LuaRuntime(register_eval=False, unpack_returned_tuples=True)
t = lua5.eval('{ops = {{"rect", 1.0, 2.0}}, n = 3}')
print("type(t) =", type(t), "| repr:", repr(t)[:60])
print("lupa.lua54.lua_type(t) =", lua_type(t), "| lupa.lua_type(t) (default module, Lua 5.5 build) =", lupa.lua_type(t))
print("t.n =", t.n, "| t['n'] =", t["n"], "| t.ops =", type(t.ops).__name__)
print("dict(t.items()) =", dict(t.items()))
print("list(t.values()) =", list(t.values()))
print("list(t.keys()) =", list(t.keys()))
print("nested: list(t.ops.values()) =", list(t.ops.values()))
print("nested: list(t.ops[1].values()) =", list(t.ops[1].values()), "types:", [type(v).__name__ for v in t.ops[1].values()])
print("len(t.ops) =", len(t.ops), "| t.ops[0] =", t.ops[0], "(Lua is 1-based)")

def lua_to_py(v):
    """recursive conversion: sequence-like tables (keys 1..n) -> list, others -> dict"""
    if lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [lua_to_py(v[i]) for i in range(1, len(keys) + 1)]
    return {k: lua_to_py(v[k]) for k in keys}

print("recursive conversion:", lua_to_py(t))
arr = lua5.eval('{"rect", 1.0, 2.0}')
print("array-like table: list(arr.values()) =", list(arr.values()), "| lupa.lua54.lua_type =", lua_type(arr))
print("lua.table_from([1,2]) round trip:", lua_type(lua5.table_from([1, 2])), list(lua5.table_from([1, 2]).values()))
print("python dict -> Lua: type =", lua5.eval("function(d) return type(d) end")({"a": 1}),
      "| lupa.lua_type of python dict arg:", lua5.eval("function(d) return d end")({"a": 1}).__class__.__name__)
```

出力（1 回目は `lupa.lua_type` を使っていて `None` が返った。以下は `lupa.lua54.lua_type` に直した最終実行）:

```
=== B.5 Lua table returned to Python ===
type(t) = <class 'lupa.lua54._LuaTable'> | repr: <Lua table at 0x31f454f0>
lua_type(t) = table
t.n = 3 | t['n'] = 3 | t.ops = _LuaTable
dict(t.items()) = {'n': 3, 'ops': <Lua table at 0x31f45670>}
list(t.values()) = [3, <Lua table at 0x31f45670>]
list(t.keys()) = ['n', 'ops']
nested: list(t.ops.values()) = [<Lua table at 0x31f456b0>]
nested: list(t.ops[1].values()) = ['rect', 1.0, 2.0] types: ['str', 'float', 'float']
len(t.ops) = 1 | t.ops[0] = None (Lua is 1-based)
recursive conversion: {'n': 3, 'ops': [['rect', 1.0, 2.0]]}
array-like table: list(arr.values()) = ['rect', 1.0, 2.0] | lupa.lua54.lua_type = table
lua.table_from([1,2]) round trip: table [1, 2]
python dict -> Lua: type = userdata | lupa.lua_type of python dict arg: dict
```

1 回目の該当行（既定モジュールの `lupa.lua_type` を lua54 の table に使った場合）:

```
lupa.lua_type(t) = None
recursive conversion: <Lua table at 0x3cf63670>
array-like table: list(arr.values()) = ['rect', 1.0, 2.0] | lupa.lua_type = None
lua.table_from([1,2]) round trip: None [1, 2]
```

観測:

- 戻り値は **`lupa.lua54._LuaTable`**（変換されない参照）。`t.n` / `t["n"]` / `t.ops[1]` で読める。**添字は Lua の 1 始まりのまま**（`t.ops[0]` は `None`）。
- 1 段の変換は `dict(t.items())` / `list(t.values())` / `list(t.keys())`。**ネストした table は `_LuaTable` のまま残る**ので、深い構造は再帰で変換する（上の `lua_to_py` で `{'n': 3, 'ops': [['rect', 1.0, 2.0]]}` を得た。「キーが 1..n の整数だけなら list、それ以外は dict」という規則は自前で決める必要がある）。
- `lua_type` は **`lupa.lua54.lua_type` を使う**。既定モジュールの `lupa.lua_type` は Lua 5.5 用で、lua54 の table には `None` を返す。
- Python の dict を Lua に渡すと Lua 側では `userdata`（proxy）で、`type(d) == "table"` にはならない。table として渡すには `lua.table_from(...)` で明示変換する。

### B.6（追加）`tick()` が 50 個の小配列を返す往復（1000 回平均）

スクリプト（`probe_b.py` 抜粋）:

```python
lua6 = LuaRuntime(register_eval=False, unpack_returned_tuples=True)
lua6.execute("""
    function tick50()
        local ops = {}
        for i = 1, 50 do ops[i] = {"rect", i, i * 2.0, 10, 20} end
        return ops
    end
""")
tick50 = lua6.globals().tick50
for _ in range(100):
    tick50()
N = 1000
for rnd in range(1, 4):
    t0 = time.perf_counter()
    for _ in range(N):
        last = tick50()
    t1 = time.perf_counter()
    print(f"round {rnd}: call only (table stays in Lua): total {(t1 - t0) * 1000:.2f} ms, avg {(t1 - t0) / N * 1e6:.1f} us")
t0 = time.perf_counter()
for _ in range(N):
    last = [list(row.values()) for row in tick50().values()]
t1 = time.perf_counter()
print(f"call + convert 50 rows to Python lists: total {(t1 - t0) * 1000:.2f} ms, avg {(t1 - t0) / N * 1e6:.1f} us; sample {last[0]}")
```

出力:

```
=== B.6 (extra) tick() returning 50 small arrays, 1000 calls ===
round 1: call only (table stays in Lua): total 3.93 ms, avg 3.9 us
round 2: call only (table stays in Lua): total 5.13 ms, avg 5.1 us
round 3: call only (table stays in Lua): total 5.14 ms, avg 5.1 us
call + convert 50 rows to Python lists: total 35.24 ms, avg 35.2 us; sample ['rect', 1, 2.0, 10, 20]
```

観測: lupa は table を参照のまま返すので呼び出しだけなら約 5 µs、50 行を Python の list に全部変換しても約 35 µs。wasmoon の nested 変換（約 600 µs）とは 1 桁半違う（wasmoon は返却時に必ず深いコピーをする）。

### B.7（追加・Phase 2）lupa の sandbox で `debug` を nil にした後も count hook が生きるか / `table_from(recursive=True)`

Phase 2（2026-09-13）で `jin_wasm.runtime` を書く前に実測した。命令数の上限（設計書 §11 #24）の
根拠と、ホストが `inputs` を Lua の table として渡せることの根拠。

スクリプト（`probe_lupa2.py` 抜粋）:

```python
import lupa.lua54 as L

lua = L.LuaRuntime(register_eval=False, register_builtins=False, unpack_returned_tuples=True)
g = lua.globals()
g.python = None
setup = lua.execute("""
local sethook = debug.sethook
local function arm(limit)
  sethook(function() error({code = "budget", message = "instruction budget exceeded"}) end, "", limit)
end
return arm
""")
for name in ("load", "loadstring", "dofile", "loadfile", "require", "package", "os", "io", "debug", "collectgarbage"):
    setattr(g, name, None)
lua.execute("string.dump = nil")
print("debug after nil:", lua.eval("type(debug)"), "string.dump:", lua.eval("type(string.dump)"))
t = lua.table_from({"events": [{"kind": "key", "name": "ArrowLeft", "down": True}],
                    "keys": {"ArrowLeft": True}, "pointer": {"x": 1.0, "y": 2.0, "down": False}}, recursive=True)
print("recursive:", lua.eval("function(t) return #t.events, t.events[1].name, t.keys.ArrowLeft, t.pointer.x, math.type(t.pointer.x) end")(t))
print("empty list:", lua.eval("function(t) return #t end")(lua.table_from([], recursive=True)))
setup(1000)
f = lua.eval("function() local ok, e = pcall(function() while true do end end) return ok, type(e) == 'table' and e.code or tostring(e) end")
print("budget via pcall:", f())
setup(10**9)
setup(1000)
try:
    lua.eval("(function() while true do end end)()")
except L.LuaError as e:
    print("LuaError outside pcall:", str(e)[:80])
setup(10**9)
print(lua.eval('string.format("%.17g", 0.1)'), lua.eval('string.format("%.16e", 1/3)'), lua.eval("math.maxinteger"))
print("utf8:", lua.eval('utf8.len("あいう")'), lua.eval('string.sub("あいう", utf8.offset("あいう", 2), utf8.offset("あいう", 3) - 1)'))
print("tointeger:", lua.eval("math.tointeger(math.floor(2.7))"), lua.eval("math.type(math.floor(2.7) + 0.0)"))
print("float mod:", lua.eval("-7.0 % 3.0"), lua.eval("7.0 % -3.0"), lua.eval("math.type(4.0 // 2.0)"))
print("coroutine.close:", lua.eval("type(coroutine.close)"))
print("json str return type:", type(lua.eval('"héllo"')))
```

出力（lupa 2.8 / Lua 5.4.8 / Python 3.14.7）:

```
debug after nil: nil string.dump: nil
recursive: (1, 'ArrowLeft', True, 1.0, 'float')
empty list: 0
budget via pcall: (False, 'budget')
LuaError outside pcall:
0.10000000000000001 3.3333333333333331e-01 9223372036854775807
utf8: 3 い
tointeger: 2 float
float mod: 2.0 -2.0 float
coroutine.close: function
json str return type: <class 'str'>
```

観測:

- **`debug.sethook` を局所に捕まえてから `debug` を nil にしても、count hook は掛かる**（`budget via pcall: (False, 'budget')`）。`arm` はセットアップのチャンクの戻り値として Python 側だけが握り、Lua のグローバルには置かない（`jin_wasm.runtime._SETUP`）。`jin_wasm.runtime.INSTRUCTION_BUDGET` の掛け直しはこの `arm` を boot と毎 tick の前に呼ぶ
- hook の `error({code = "budget"})` は **`pcall` の中なら table のまま捕まる**。`pcall` の外へ出ると lupa の `LuaError` になり、error 値が table なので `str(e)` は空文字列（上の `LuaError outside pcall:` の行）。`jin_wasm.runtime._lua_message` が `str(e)` ではなく `exc.args[0]` の table から `message` / `code` を読むのはこのため
- `table_from(..., recursive=True)` は **ネストした dict / list を Lua の table に写す**（`#t.events == 1`、`t.pointer.x` は float のまま）。空 list は `#t == 0`。ホストが `tick(t, inputs)` の `inputs` を渡す経路はこれ 1 本で、`jin_wasm.runtime.LuaHost.tick` が使う
- `string.format("%.17g", 0.1)` は `0.10000000000000001`、`"%.16e"` は 2 桁の指数（`e-01`）。runtime.md §6 の数値書式（Python の `repr` と同じ配置）は `%.<n>e` の桁を自前で組み直す
- `math.floor(2.7) + 0.0` は float、`4.0 // 2.0` も float（jil.md §2「整数サブタイプを作る演算を生成しない」の根拠）。`-7.0 % 3.0 == 2.0`（Python と同じ符号規則）
- `coroutine.close` は Lua 5.4 にある（プレリュードが休止中の陣を捨てるときに使う）

### B.8（追加・Phase 4）lupa の count hook はコルーチンに届かない / コルーチンごとに掛ければ届く

Phase 2 の §B.7 の hook（メインスレッドに `debug.sethook(f, "", n)`）が `wait` を含む手順（コルーチン）の
無限ループを止められるかを Phase 4 の前に実測した（`probe_lupa_co.py` / `probe_lupa_co2.py`）。

**(1) メインスレッドの hook はコルーチンに届かない**（`probe_lupa_co.py`。`busy_co` は 3×10^6 回のループを上限 1,000 で走らせる）:

```
busy: false|budget
busy_co (3e6 loop, would stop at 1000 if hooked): true|ran-to-end
```

→ Phase 2 の `arm`（ホストがメインスレッドにだけ掛ける）は、コルーチンの中では**効いていなかった**（設計書 §11 #24 の残存。#32 で閉じる）。
Lua 5.4 の `lua_newthread` は C の hook をコピーするが、`debug.sethook` の Lua 関数はレジストリのスレッド別テーブルから引かれるので、
新しいスレッドでは何もしない。

**(2) コルーチンごとに `sethook(co, f, "", n)` を掛ければ届く**（`probe_lupa_co2.py`。§A.10 (3) と同じ Lua をホストが置き、読み込み後に消す）:

```
type(JIN_ARM) after load: nil
busy: false|budget
busy_co: false|budget:命令数の上限 1000 を超えました（無限ループ？）
wait_co (5 yields of 300 iters each, limit 1000): false:budget,false:cannot resume dead coroutine,…
main_after_co: false|budget
```

観測: wasmoon（§A.10）と**同じ出力**。`jin_wasm.runtime._SETUP` はこの形（`JIN_ARM` / `JIN_HOOK` を置く）に改め、
`LuaHost` は JIL を読んだ後に 2 つを `None` にする。プレリュードは `boot` / `tick` の先頭で `ARM()`、`resume()` で
`coroutine.resume` の前に `HOOK(co)` を呼ぶ。`sethook` は count を掛け直すたびに 0 に戻すので、何 tick も生きる手順が
累積で上限に当たることはない（`test_the_coroutine_budget_is_reset_on_every_resume`。HOOK を生成時にだけ掛ける変異では
5 tick 目までに `命令数の上限 20000 を超えました` になることを確かめた）。

---

## 設計に効く要点（実測から言えることだけ）

1. **yield はホストを跨げない**（wasmoon / lupa とも `attempt to yield across a C-call boundary`）。wasmoon で JS→Lua 再入先の yield は `PANIC` + `abort()`。スケジューラは純 Lua の中に閉じ、ホストは `tick()` を呼ぶだけにする。
2. **wasmoon は Lua→JS で integer / float の区別と 64 bit 精度を失う**（`1.0` → `1`、`maxinteger` → `9223372036854776000`）。lupa は保つ。描画命令の数値契約を書くなら「ホストに出た時点で double」を前提にする。
3. **`pairs` の順序は engine / runtime を跨ぐと不定**（両方）。決定性が要る出力はキーをソートするか配列で持つ。
4. **wasmoon で標準ライブラリを絞るなら `openStandardLibs: false` + `loadLibrary` の明示ロード**。`global.set(name, null)` は 1.16.0 で TypeError になるので nil 化は `undefined` か Lua 側の代入で行う。
5. **lupa をサンドボックスとして使うなら `register_eval=False` だけでは足りない**。`python.builtins`（`open` を含む）が残るので `register_builtins=False` と `globals().python = None` が要る。
6. **wasmoon の Lua→JS の table 変換は 1 値あたり約 1.8 µs**。50 行 × 5 値で約 600 µs、JSON 文字列で返せば 35 µs。毎フレーム大量の命令を返す設計では文字列（または平坦な数値配列より速い文字列）で受ける方が有利。
7. lupa の既定 `LuaRuntime` は Lua 5.5.1。wasmoon（5.4）と揃えるには `lupa.lua54` を明示する。
