-- Jin v2 プレリュード（docs/spec/v2/runtime.md / jil.md §1 の <prelude>）。jil: 6
--
-- `game.lua` の先頭にそのまま連結される。表示リスト / 入力 / ui / audio / PCG32 / スケジューラ /
-- トレース / JSON 直列化 / 数値書式をここに置き、生成部（<program>）は式とステップだけを出す。
-- すべて local に閉じ、グローバルは末尾の boot / tick の 2 つだけ（jil.md §2）。
-- 読むグローバルはホストが JIL を読む前に置く JIN_ARM / JIN_HOOK の 2 つだけ（runtime.md §8。
-- 読み込み時に local へ捕まえ、ホストは読んだ後に消す。無ければ命令数の上限なし）。
-- 禁止語（pairs / next / setmetatable / load / os / io / debug / select / ... など）は使わない。
-- 走査は tests/contract/test_jil_contract.py が掛ける。
--
-- 生成部が定義するもの（codegen.py と 1:1。ここを変えたら JIL の版を上げる）:
--   DEBUG = true | false          トレース行を出すか（既定 false）
--   ROOT  = <root の陣の添字>
--   FPS   = <stage.fps>
--   CIRCLES[i] = {
--     name = "Play",
--     -- 核なし陣:
--     flow = "sequence" | "parallel" | "loop", children = { j, k, ... }, exit = function() ... end | nil,
--     -- 核あり陣:
--     init = function() return { k_0 = ..., k_1 = ... } end,   -- entered のたびに評価（定数式）
--     publish = function() P[i].k_2 = S[i].k_2 end,             -- out: true の state を確定する
--     dump = function() return "<state の JSON>" end,           -- enter / exit 行と snapshot（DEBUG のみ）
--     pdump = function() return "<公開 state の確定値の JSON>" end,  -- snapshot（DEBUG のみ。out: true の state だけ）
--     restore = function(v) S[i].k_j = RN(v["name"]) ... end,       -- resume（DEBUG のみ。名前で引き、形が合う欄だけ）
--     prestore = function(v) P[i].k_j = RN(v["name"]) ... end,      -- resume の公開 state（DEBUG のみ）
--     core = R[i][j], core_waits = bool,
--     on = { tick = R[i][j], key = ..., pointer = ..., message = ..., exit = ... },
--     on_waits = { tick = bool, ... },
--     on_ptr = { tick = "/circles/i/boundary/on/0", ... },
--     guards = { { fn = function() return <bool> end, message = "...", pointer = "/circles/i/boundary/guards/0" }, ... },
--   }
--   R[i] = {} ; R[i][j] = function(a, b) ... end               -- 手順（引数の数は静的）
--   JF[k] = function(v) return "{...}" end                    -- 型紙 k の直列化（JF[0] は Pointer）
--   JR[k] = function(v) return { f_0 = ..., } | nil end        -- 型紙 k の読み手（DEBUG のみ。resume の JSON → Lua）
-- プレリュードが持つもの:
--   S[i]（陣 i の state。init が返す表）/ P[i]（公開 state の確定値。他陣は P を読む）
--   H（ホスト能力: H.canvas / H.input / H.ui / H.audio / H.random / H.storage）/ F（純関数）/ E（効果）
--   AT / SETAT（添字）/ WAIT_TICKS / WAIT_UNTIL / FINISH / TRANSFER / EMIT / ASK / STOP
--   T / TS / TR / TRET（トレース。DEBUG のときだけ生成部が呼ぶ）
--   RN / RB / RSTR / RL / RREC（resume の読み手。num / bool / str / list / レコード。合わなければ nil）
--   CIRCLES[i].pub = function() return '"Play.score":' .. JN(P[i].k_2) end   -- 公開 state の JSON 断片（tick の戻り値の public）

local DEBUG = false
local ROOT = 1
local FPS = 60
local CIRCLES = {}
local R = {}
local JF = {}
local JR = {}
local S = {}
local P = {}

-- ---------------------------------------------------------------- 実行時の状態
local C = {}          -- C[i] = { status = "idle"|"active"|"done", paused = bool, delegate = j|nil, pending = bool, cursor = n, waits = {} }
local OPS = {}
local AUDIO = {}
local TRACE = {}
local Q = {}          -- 次 tick に配達するメッセージ
local ASKS = {}       -- この tick に v1 の陣へ出した問い（tick 結果の asks・runtime.md §11）
local ASKED = 0       -- 問いの通し番号（snapshot に載せる）
local ASK_MAP = {}    -- 要求 id → { ci, name, pointer }（答えの宛先。未回答の分は差し替えで捨てる）
local SEQ = 0
local TICK = -1
local DONE = false
local ERRMSG = nil
local INK = "#fff"
local INPUTS = { events = {}, keys = {}, pointer = { x = 0.0, y = 0.0, down = false } }
local RELEASES = {}   -- この tick にポインタの主ボタンが離された位置の列
local LAST_DOWN = false
local CUR_PTR = nil   -- 最後にトレースした pointer（error 行のため）
local CUR_CI = nil

-- ---------------------------------------------------------------- 命令数の上限（runtime.md §8）
-- ホストが JIL を読む前に置く 2 つのグローバル（読んだ後にホストが消す。無ければ上限なし）。
-- ARM() は今のスレッドに count hook を掛け直し、HOOK(co) はコルーチン co に同じ hook を掛ける。
-- Lua の hook はスレッドごとなので、wait を含む手順（コルーチン）の無限ループは ARM だけでは
-- 止まらない。boot / tick の先頭で ARM、毎 coroutine.resume の前で HOOK を呼ぶ（count は掛け直す
-- たびに戻るので、何 tick も生きる手順が累積で上限に当たることはない）。
local ARM = JIN_ARM
local HOOK = JIN_HOOK
local MANIFEST = nil
local SEED = 0
-- 状態を保った差し替え（runtime.md §1 の manifest.resume）の結果。直後の tick 結果に 1 回だけ載せる。
local RESUME_NOTE = nil

local ADVANCE_LIMIT = 1000

local function ERR(code, message)
  error({ code = code, message = message }, 0)
end

-- ---------------------------------------------------------------- 数値の書式（runtime.md §6）
-- 整数値（|x| < 2^53）は整数として、それ以外は最短の往復可能表現を Python の repr と同じ配置で書く
-- （指数形は exp < -4 または exp >= 16 のとき。指数は符号付き 2 桁以上）。
local function shortest_digits(x)
  for p = 0, 16 do
    local s = string.format("%." .. p .. "e", x)
    if tonumber(s) == x then
      local sign, int, frac, exp = string.match(s, "^(-?)(%d)%.?(%d*)e([-+]%d+)$")
      return sign, int .. frac, tonumber(exp)
    end
  end
  local s = string.format("%.16e", x)
  local sign, int, frac, exp = string.match(s, "^(-?)(%d)%.?(%d*)e([-+]%d+)$")
  return sign, int .. frac, tonumber(exp)
end

local function NUMSTR(x)
  if x ~= x then return "NaN" end
  if x == math.huge then return "Infinity" end
  if x == -math.huge then return "-Infinity" end
  if x == math.floor(x) and math.abs(x) < 9007199254740992.0 then
    return string.format("%d", x)
  end
  local sign, digits, e = shortest_digits(x)
  local n = #digits
  if e >= -4 and e < 16 then
    if e >= 0 then
      local int = string.sub(digits, 1, e + 1)
      if #int < e + 1 then int = int .. string.rep("0", e + 1 - #int) end
      local frac = string.sub(digits, e + 2)
      if frac == "" then frac = "0" end
      return sign .. int .. "." .. frac
    end
    return sign .. "0." .. string.rep("0", -e - 1) .. digits
  end
  local mant = string.sub(digits, 1, 1)
  if n > 1 then mant = mant .. "." .. string.sub(digits, 2) end
  local es = (e < 0) and "-" or "+"
  local ea = math.abs(e)
  local ed = tostring(ea)
  if ea < 10 then ed = "0" .. ed end
  return sign .. mant .. "e" .. es .. ed
end

-- ---------------------------------------------------------------- JSON
local ESC = { ['"'] = '\\"', ["\\"] = "\\\\", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t", ["\b"] = "\\b", ["\f"] = "\\f" }

local function esc_char(ch)
  local e = ESC[ch]
  if e then return e end
  return string.format("\\u%04x", string.byte(ch))
end

-- 制御文字は範囲で書く（`%c` は C の iscntrl でプロセスのロケールに従い、UTF-8 のロケールでは
-- 非 ASCII の途中のバイトまで \u00xx にして JSON を壊す。lupa のホストで起きた・v2.1）。
local function JS(s)
  return '"' .. string.gsub(s, '[\0-\31\127"\\]', esc_char) .. '"'
end

local function JN(x)
  if x ~= x or x == math.huge or x == -math.huge then return '"' .. NUMSTR(x) .. '"' end
  return NUMSTR(x)
end

local function JB(b)
  if b then return "true" end
  return "false"
end

-- 原始値（num / bool / str / nil）。表は生成部の JF / JL で直列化する。
local function JV(v)
  local t = type(v)
  if t == "number" then return JN(v) end
  if t == "string" then return JS(v) end
  if t == "boolean" then return JB(v) end
  return "null"
end

-- list<T> の直列化（要素の直列化関数を受け取る）。
local function JL(item)
  return function(list)
    local parts = {}
    for k, v in ipairs(list) do parts[k] = item(v) end
    return "[" .. table.concat(parts, ",") .. "]"
  end
end

-- 原始値の配列（表示リスト・音リストの 1 要素）。
local function JA(arr)
  local parts = {}
  for k, v in ipairs(arr) do parts[k] = JV(v) end
  return "[" .. table.concat(parts, ",") .. "]"
end

local JAA = JL(JA)

local function JROW(row)
  return '{"seq":' .. string.format("%d", row.seq)
    .. ',"tick":' .. string.format("%d", row.tick)
    .. ',"circle":' .. JV(row.circle)
    .. ',"kind":' .. JS(row.kind)
    .. ',"name":' .. JV(row.name)
    .. ',"pointer":' .. JV(row.pointer)
    .. ',"input":' .. (row.input or "null")
    .. ',"output":' .. (row.output or "null") .. "}"
end

-- ---------------------------------------------------------------- resume の読み手（runtime.md §1 の manifest.resume）
-- ホストから来た値（lupa は table、Wasmoon は proxy の userdata・probe A.3）を型に合わせて Lua の値にする。
-- 合わなければ nil（呼び出し側は init の値のまま）。形は type() ではなく欄の読み取りと ipairs で見る。
-- 数値は + 0.0（JS の整数値は Lua の integer で入る・probe A.10）。NaN / Infinity は文字列で来るので nil。
local function RREC(v)
  if type(v) == "table" or type(v) == "userdata" then return v end
  return nil
end
local function RN(v)
  if type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge then return v + 0.0 end
  return nil
end
local function RB(v)
  if type(v) == "boolean" then return v end
  return nil
end
local function RSTR(v)
  if type(v) == "string" then return v end
  return nil
end
local function RL(read)
  return function(v)
    if RREC(v) == nil then return nil end
    local out = {}
    for k, item in ipairs(v) do
      local x = read(item)
      if x == nil then return nil end
      out[k] = x
    end
    return out
  end
end

-- ---------------------------------------------------------------- トレース（DEBUG のときだけ）
-- 行は表で持ち（rite 行の output は return 時に埋める）、tick の終わりに直列化する。
local function ROW(kind, ci, name, pointer, input, output)
  local row = {
    seq = SEQ, tick = TICK, circle = ci and CIRCLES[ci].name or nil, kind = kind,
    name = name, pointer = pointer, input = input, output = output,
  }
  SEQ = SEQ + 1
  TRACE[#TRACE + 1] = row
  if pointer then CUR_PTR = pointer end
  if ci then CUR_CI = ci end
  return row
end

-- 生成部が呼ぶ入口。
local function T(kind, ci, name, pointer, input, output)      -- 汎用（cast / emit / transfer / finish）
  return ROW(kind, ci, name, pointer, input, output)
end
local function TS(ci, name, pointer, value_json)              -- set 行（state への代入だけ）
  return ROW("set", ci, name, pointer, nil, value_json)
end
local function TR(ci, name, pointer, args_json)               -- rite 行（起動直前）
  return ROW("rite", ci, name, pointer, args_json, nil)
end
local function TRET(row, value_json)                          -- rite 行の output（return 時）
  if row then row.output = value_json end
end

-- ---------------------------------------------------------------- 入力（abilities.md §3）
local function pointer_value()
  local p = INPUTS.pointer
  return { f_0 = p.x + 0.0, f_1 = p.y + 0.0, f_2 = p.down and true or false }
end

local function JPOINTER(p)
  return '{"x":' .. JN(p.f_0) .. ',"y":' .. JN(p.f_1) .. ',"down":' .. JB(p.f_2) .. "}"
end

local function prepare_inputs(inputs)
  INPUTS = inputs
  if INPUTS.events == nil then INPUTS.events = {} end
  if INPUTS.keys == nil then INPUTS.keys = {} end
  if INPUTS.pointer == nil then INPUTS.pointer = { x = 0.0, y = 0.0, down = false } end
  RELEASES = {}
  for _, ev in ipairs(INPUTS.events) do
    if ev.kind == "pointer" then
      local down = ev.down and true or false
      if LAST_DOWN and not down then
        RELEASES[#RELEASES + 1] = { x = ev.x + 0.0, y = ev.y + 0.0 }
      end
      LAST_DOWN = down
    end
  end
end

-- ---------------------------------------------------------------- 乱数（abilities.md §6・PCG32）
local RS = 0
local RI = 1

local function rng_step()
  local old = RS
  RS = old * 6364136223846793005 + RI
  local xorshifted = (((old >> 18) ~ old) >> 27) & 0xffffffff
  local rot = (old >> 59) & 31
  return ((xorshifted >> rot) | (xorshifted << ((32 - rot) & 31))) & 0xffffffff
end

local function rng_seed(seed)
  RS = 0
  RI = (seed << 1) | 1
  rng_step()
  RS = RS + seed
  rng_step()
end

-- ---------------------------------------------------------------- ホスト能力（abilities.md）
local function check_color(color)
  if type(color) ~= "string"
    or not (string.match(color, "^#%x%x%x$") or string.match(color, "^#%x%x%x%x%x%x$")) then
    ERR("color", "色は \"#rgb\" か \"#rrggbb\" で書きます（" .. tostring(color) .. "）")
  end
  return color
end

local H = {}

H.canvas = {
  clear = function(color) OPS[#OPS + 1] = { "clear", check_color(color) } end,
  ink = function(color) INK = check_color(color); OPS[#OPS + 1] = { "ink", INK } end,
  rect = function(x, y, w, h) OPS[#OPS + 1] = { "rect", x, y, w, h } end,
  circle = function(x, y, r) OPS[#OPS + 1] = { "circle", x, y, r } end,
  line = function(x1, y1, x2, y2) OPS[#OPS + 1] = { "line", x1, y1, x2, y2 } end,
  text = function(s, x, y) OPS[#OPS + 1] = { "text", s, x, y } end,
  sprite = function(name, x, y) OPS[#OPS + 1] = { "sprite", name, x, y } end,
}

H.input = {
  key = function(name) return INPUTS.keys[name] == true end,   -- jil.md §2 が名指しで許す 1 か所
  pressed = function(name)
    for _, ev in ipairs(INPUTS.events) do
      if ev.kind == "key" and ev.name == name and ev.down then return true end
    end
    return false
  end,
  pointer = pointer_value,
  -- この tick に確定した文字列（abilities.md §3・v2.1）。text イベントを発生順につなぐ。無ければ ""。
  -- 状態を持たない（snapshot / resume に運ぶものが無い）。
  text = function()
    local s = ""
    for _, ev in ipairs(INPUTS.events) do
      if ev.kind == "text" then s = s .. ev.text end
    end
    return s
  end,
}

H.ui = {
  button = function(label, x, y, w, h)
    OPS[#OPS + 1] = { "button", label, x, y, w, h }
    for _, r in ipairs(RELEASES) do
      if r.x >= x and r.x <= x + w and r.y >= y and r.y <= y + h then return true end
    end
    return false
  end,
  label = function(s, x, y) OPS[#OPS + 1] = { "label", s, x, y } end,
}

H.audio = {
  tone = function(hz, ms) AUDIO[#AUDIO + 1] = { "tone", hz, ms } end,
  play = function(name) AUDIO[#AUDIO + 1] = { "play", name } end,
}

H.random = {
  ["next"] = function() return rng_step() / 4294967296.0 end,
  range = function(lo, hi)
    lo = math.floor(lo) + 0.0
    hi = math.floor(hi) + 0.0
    if hi < lo then return lo end
    local n = hi - lo + 1.0
    return lo + (rng_step() % n)
  end,
}

-- storage（abilities.md §8・v2.1）。ホストの記憶は境界を越えない: 入りは boot の manifest.storage（写し。
-- lupa は table、Wasmoon は proxy の userdata。pairs は禁止語なので写さず**参照のまま読むだけ**）、
-- 出は tick の戻り値の storage（この tick の書き込みの一覧）。自分の書き込みは STORE に重ねて get に見せる。
local STORAGE_BASE = nil   -- boot の manifest.storage（読むだけ）
local STORE = {}           -- この実行での書き込み（key → val）
local STORE_OUT = {}       -- この tick の書き込みの一覧 { {key, val}, ... }
H.storage = {
  get = function(key)
    local mine = STORE[key]
    if mine ~= nil then return mine end
    if STORAGE_BASE ~= nil then
      local base = RSTR(STORAGE_BASE[key])
      if base ~= nil then return base end
    end
    return ""
  end,
  set = function(key, val)
    STORE[key] = val
    STORE_OUT[#STORE_OUT + 1] = { key, val }
  end,
}

-- ---------------------------------------------------------------- 純関数（expr.md §4.1）と効果（§4.2）
local F = {}
F.abs = math.abs
F.min = math.min
F.max = math.max
F.floor = function(x) return math.floor(x) + 0.0 end
F.ceil = function(x) return math.ceil(x) + 0.0 end
F.round = function(x)
  local f = math.floor(x) + 0.0
  local d = x - f
  if d < 0.5 then return f end
  if d > 0.5 then return f + 1.0 end
  if f % 2.0 == 0.0 then return f end
  return f + 1.0
end
F.sqrt = math.sqrt
F.sin = math.sin
F.cos = math.cos
F.atan2 = function(y, x) return math.atan(y, x) end
F.clamp = function(x, lo, hi) return math.min(math.max(x, lo), hi) end
F.len = function(v)
  if type(v) == "string" then return (utf8.len(v) or #v) + 0.0 end
  return #v + 0.0
end
F.str = function(v)
  local t = type(v)
  if t == "number" then return NUMSTR(v) end
  if t == "boolean" then return v and "true" or "false" end
  return v
end
F.sub = function(s, i, n)
  local total = utf8.len(s) or #s
  i = math.floor(i)
  n = math.floor(n)
  if i < 0 then n = n + i; i = 0 end
  if i >= total or n <= 0 then return "" end
  if i + n > total then n = total - i end
  local first = utf8.offset(s, i + 1)
  local last = utf8.offset(s, i + n + 1)
  if last == nil then return string.sub(s, first) end
  return string.sub(s, first, last - 1)
end
F.contains = function(list, v)
  for _, item in ipairs(list) do
    if item == v then return true end
  end
  return false
end
-- str の逆（expr.md §4.1・v2.1）。受けるのは str() が出す形と JSON の数値の形だけ。tonumber は 16 進・
-- 空白・inf を通すので、先にパターンで弾く。合わなければ 0（無い鍵の "" も 0）。
F.num = function(s)
  if type(s) ~= "string" then return 0.0 end
  if not (string.match(s, "^%-?%d+$")
    or string.match(s, "^%-?%d+%.%d+$")
    or string.match(s, "^%-?%d+[eE][%-+]?%d+$")
    or string.match(s, "^%-?%d+%.%d+[eE][%-+]?%d+$")) then
    return 0.0
  end
  local v = tonumber(s)
  if v == nil or v ~= v or v == math.huge or v == -math.huge then return 0.0 end
  return v + 0.0
end
-- 文字列の順序（expr.md §4.1・v2.1）。-1 / 0 / 1 をコードポイント順（= UTF-8 のバイト順）で返す。
-- Lua の文字列の `<` は strcoll を通ってプロセスのロケールの照合順に従い、lupa（Python のプロセス）と
-- Wasmoon で揃う保証が無いので使わず、バイトを 1 つずつ比べる。
F.cmp = function(a, b)
  if a == b then return 0.0 end
  local la, lb = #a, #b
  for i = 1, math.min(la, lb) do
    local x, y = string.byte(a, i), string.byte(b, i)
    if x ~= y then
      if x < y then return -1.0 end
      return 1.0
    end
  end
  if la < lb then return -1.0 end
  return 1.0
end

local function index_of(list, i)
  local k = math.tointeger(math.floor(i))
  if k == nil or k < 0 or k >= #list then
    ERR("index", "添字 " .. NUMSTR(i) .. " は範囲外です（長さ " .. #list .. "）")
  end
  return k + 1
end

local function AT(list, i) return list[index_of(list, i)] end
local function SETAT(list, i, v) list[index_of(list, i)] = v end

local E = {}
E.push = function(list, v) list[#list + 1] = v end
E.removeAt = function(list, i) table.remove(list, index_of(list, i)) end
E.clear = function(list)
  for k = #list, 1, -1 do list[k] = nil end
end

-- ---------------------------------------------------------------- 陣の順（runtime.md §2「陣の順」）
local function order_into(i, out, seen)
  if seen[i] then return end
  seen[i] = true
  local c = CIRCLES[i]
  if c.flow then
    for _, child in ipairs(c.children) do order_into(child, out, seen) end
    return
  end
  local st = C[i]
  if st.paused and st.delegate then
    order_into(st.delegate, out, seen)
    return
  end
  out[#out + 1] = i
end

local function ORDER()
  local out = {}
  order_into(ROOT, out, {})
  return out
end

local function is_active(i)
  return C[i].status == "active" and not C[i].paused
end

-- ---------------------------------------------------------------- 手順の起動（コルーチン / 直接呼び出し）
local function STOP(i)
  return C[i].status ~= "active" or C[i].paused
end

local function register_wait(i, co, req)
  if C[i].status ~= "active" then
    coroutine.close(co)
    return
  end
  local w = { co = co, pointer = req.pointer }
  if req.ticks then
    w.ticks = req.ticks
    if DEBUG then ROW("wait", i, nil, req.pointer, '{"ticks":' .. JN(req.ticks) .. "}", '"suspend"') end
  else
    w.until_ = req.until_
    if DEBUG then ROW("wait", i, nil, req.pointer, '{"until":true}', '"suspend"') end
  end
  local waits = C[i].waits
  waits[#waits + 1] = w
end

local function resume(i, co, args)
  if HOOK then HOOK(co) end
  local ok, req = coroutine.resume(co, table.unpack(args))
  if not ok then error(req, 0) end
  if coroutine.status(co) == "suspended" then
    register_wait(i, co, req)
  end
end

local function RUN(i, fn, waits, args)
  if not waits then
    fn(table.unpack(args))
    return
  end
  local co = coroutine.create(fn)
  resume(i, co, args)
end

local function WAIT_TICKS(n, pointer)
  local ticks = math.ceil(n)
  if ticks < 1 or ticks ~= ticks then ticks = 1 end
  coroutine.yield({ ticks = ticks, pointer = pointer })
end

local function WAIT_UNTIL(fn, pointer)
  coroutine.yield({ until_ = fn, pointer = pointer })
end

-- ---------------------------------------------------------------- 生存（runtime.md §3）
local ENTER

local function reset(i)
  local st = C[i]
  st.status = "idle"
  st.paused = false
  st.pending = false
  st.cursor = 0
  for _, w in ipairs(st.waits) do coroutine.close(w.co) end
  st.waits = {}
  if st.delegate then
    reset(st.delegate)
    st.delegate = nil
  end
  local c = CIRCLES[i]
  if c.flow then
    for _, child in ipairs(c.children) do reset(child) end
  end
end

local function publish(i)
  local c = CIRCLES[i]
  if c.publish then
    c.publish()
    C[i].published = true
  end
end

local function FINISH(i)
  local st = C[i]
  if st.status ~= "active" then return end
  st.status = "done"
  publish(i)
  for _, w in ipairs(st.waits) do coroutine.close(w.co) end
  st.waits = {}
  local c = CIRCLES[i]
  if DEBUG then ROW("exit", i, c.name, "/circles/" .. (i - 1), nil, c.dump and c.dump() or "null") end
  if c.on and c.on.exit then
    if DEBUG then ROW("event", i, "exit", c.on_ptr.exit, "[]", nil) end
    RUN(i, c.on.exit, c.on_waits.exit, {})
  end
end

local function TRANSFER(i, j)
  local st = C[i]
  if st.status ~= "active" then return end
  if C[j].status ~= "idle" then
    ERR("transfer", "transfer 先 '" .. CIRCLES[j].name .. "' は idle ではありません")
  end
  st.paused = true
  st.delegate = j
  st.pending = true
end

-- meta は DEBUG のときだけ（{ ci = 発信元, pointer = emit ステップ, args_json = 引数の JSON }）。
-- emit 行は配達の tick に積む（runtime.md §5「次 tick の 1 で埋めた行を出す」）。
local function EMIT(to, name, args, meta)
  Q[#Q + 1] = { to = to, name = name, args = args, meta = meta }
end

-- v1 の陣に問う（runtime.md §11・agent の sigil）。同期で返るのは要求 id だけ。答えは後の tick の
-- 入力イベント reply で戻り、deliver が id を出した陣の on message へ配達する。
local function ASK(ci, name, pointer, prompt)
  ASKED = ASKED + 1
  local id = ASKED
  ASK_MAP[id] = { ci = ci, name = name, pointer = pointer }
  ASKS[#ASKS + 1] = { id = id, ci = ci, name = name, prompt = prompt }
  return id + 0.0
end

ENTER = function(i)
  local c = CIRCLES[i]
  local st = C[i]
  st.status = "active"
  st.paused = false
  st.pending = false
  st.cursor = 1
  st.waits = {}
  if c.flow then
    if c.flow == "parallel" then
      for _, child in ipairs(c.children) do ENTER(child) end
    else
      ENTER(c.children[1])
    end
    return
  end
  S[i] = c.init()
  publish(i)
  if DEBUG then ROW("enter", i, c.name, "/circles/" .. (i - 1), nil, c.dump and c.dump() or "null") end
  if c.core then RUN(i, c.core, c.core_waits, {}) end
end

local function advance_flow(i)
  local c = CIRCLES[i]
  local st = C[i]
  if st.status ~= "active" then return false end
  local changed = false
  for _, child in ipairs(c.children) do
    if CIRCLES[child].flow and C[child].status == "active" then
      if advance_flow(child) then changed = true end
    end
  end
  if c.flow == "parallel" then
    for _, child in ipairs(c.children) do
      if C[child].status ~= "done" then return changed end
    end
    st.status = "done"
    return true
  end
  local cur = c.children[st.cursor]
  if C[cur].status ~= "done" then return changed end
  if st.cursor < #c.children then
    st.cursor = st.cursor + 1
    ENTER(c.children[st.cursor])
    return true
  end
  if c.flow == "sequence" or c.exit() then
    st.status = "done"
    return true
  end
  for _, child in ipairs(c.children) do reset(child) end
  st.cursor = 1
  ENTER(c.children[1])
  return true
end

local function ADVANCE()
  for _ = 1, ADVANCE_LIMIT do
    local changed = false
    for i = 1, #CIRCLES do
      local st = C[i]
      if st.delegate then
        if st.pending and C[st.delegate].status == "idle" then
          st.pending = false
          ENTER(st.delegate)
          changed = true
        elseif C[st.delegate].status == "done" then
          reset(st.delegate)
          st.delegate = nil
          st.paused = false
          changed = true
        end
      end
    end
    if CIRCLES[ROOT].flow then
      if advance_flow(ROOT) then changed = true end
    end
    if C[ROOT].status == "done" then DONE = true end
    if not changed then return end
  end
  ERR("advance", "1 tick の中で陣の進行が " .. ADVANCE_LIMIT .. " 回を超えました（exit が常に偽の loop など）")
end

-- ---------------------------------------------------------------- 状態を保った差し替え（runtime.md §1・設計書 §11 #42〜#44）
-- snapshot: tick 結果に載せる実行時の状態（DEBUG のみ）。陣は配列（名前で照合する。pairs は使わない）。
-- 手順の途中（wait 中のコルーチン）と未配達の emit は載らない（復元では捨てる）。
local function snapshot_json()
  local items = {}
  for i = 1, #CIRCLES do
    local c = CIRCLES[i]
    local st = C[i]
    items[i] = '{"name":' .. JS(c.name)
      .. ',"status":' .. JS(st.status)
      .. ',"paused":' .. JB(st.paused)
      .. ',"pending":' .. JB(st.pending)
      .. ',"cursor":' .. JN(st.cursor)
      .. ',"published":' .. JB(st.published)
      .. ',"delegate":' .. (st.delegate and JS(CIRCLES[st.delegate].name) or "null")
      .. ',"state":' .. (c.dump and c.dump() or "null")
      .. ',"public":' .. (c.pdump and c.pdump() or "null")
      .. "}"
  end
  -- PCG32 の状態は 64 bit 整数なので 16 進の文字列で越える（jil.md §5 の例外）。
  -- asked は v1 の陣への問いの通し番号（runtime.md §11。差し替えても id が続く。未回答の問いは載せない）。
  return '{"seed":' .. JN(SEED) .. ',"tick":' .. JN(TICK) .. ',"seq":' .. JN(SEQ)
    .. ',"rng":' .. JS(string.format("0x%x", RS)) .. ',"done":' .. JB(DONE)
    .. ',"asked":' .. JN(ASKED)
    .. ',"circles":[' .. table.concat(items, ",") .. "]}"
end

local function resume_note_json()
  local n = RESUME_NOTE
  local kept = {}
  for k, name in ipairs(n.kept) do kept[k] = JS(name) end
  local dropped = {}
  for k, name in ipairs(n.dropped) do dropped[k] = JS(name) end
  return '{"mode":' .. JS(n.mode) .. ',"tick":' .. JN(n.tick)
    .. ',"kept":[' .. table.concat(kept, ",") .. '],"dropped":[' .. table.concat(dropped, ",") .. "]}"
end

local function find_circle(name)
  for i = 1, #CIRCLES do
    if CIRCLES[i].name == name then return i end
  end
  return nil
end

-- boot の初期状態（idle・init の値）。復元に失敗して通常の boot に落ちるときにも呼ぶ。
local function fresh_state()
  for i = 1, #CIRCLES do
    C[i] = { status = "idle", paused = false, pending = false, cursor = 0, waits = {}, published = false }
    P[i] = {}
    -- 未 entered の陣の state は init の値（model.md §3.2 の summon）。entered で評価し直す
    if CIRCLES[i].init then
      S[i] = CIRCLES[i].init()
      publish(i)
    else
      S[i] = nil
    end
  end
end

-- 陣を名前で照合して状態を写す。核あり ↔ 核なしが変わった陣は照合しない（idle のまま）。
-- root が照合できず idle のままなら false（呼び出し側が通常の boot に落とす）。
local function restore_from(resume)
  local kept = {}
  local dropped = {}
  local snaps = RREC(resume.circles)
  if snaps ~= nil then
    for _, sc in ipairs(snaps) do
      local name = RSTR(sc.name)
      local i = name and find_circle(name) or nil
      local c = i and CIRCLES[i] or nil
      -- 核あり陣の snapshot は state を持ち（空でも {}）、核なし陣は null。
      if c ~= nil and (c.flow ~= nil) == (RREC(sc.state) == nil) then
        local st = C[i]
        local status = RSTR(sc.status)
        if status == "active" or status == "done" or status == "idle" then st.status = status end
        st.paused = sc.paused == true
        st.pending = sc.pending == true
        st.cursor = math.tointeger(sc.cursor) or 0
        st.published = sc.published == true
        local delegate = RSTR(sc.delegate)
        st.delegate = delegate and find_circle(delegate) or nil
        if st.delegate == nil then st.paused = false end
        if st.delegate and C[st.delegate].status == "idle" then st.pending = true end
        if c.restore and RREC(sc.state) then c.restore(sc.state) end
        if c.prestore and RREC(sc.public) then c.prestore(sc.public) end
        kept[#kept + 1] = name
      elseif name ~= nil then
        dropped[#dropped + 1] = name
      end
    end
  end
  if C[ROOT].status == "idle" then
    fresh_state()
    RESUME_NOTE = { mode = "fresh", tick = -1, kept = {}, dropped = dropped }
    return false
  end
  TICK = math.tointeger(resume.tick) or -1
  SEQ = math.tointeger(resume.seq) or 0
  ASKED = math.tointeger(resume.asked) or 0
  local rng = RSTR(resume.rng)
  local rs = rng and math.tointeger(tonumber(rng)) or nil
  if rs ~= nil then RS = rs end
  DONE = resume.done == true
  RESUME_NOTE = { mode = "resumed", tick = TICK, kept = kept, dropped = dropped }
  return true
end

-- 復元後の修復: active な flow の idle な子（足された子・照合できなかった子）を entered にする。
-- それ以外の修復はしない（wait 中の手順・未配達の emit は捨てる）。
local function repair_flows()
  for i = 1, #CIRCLES do
    local c = CIRCLES[i]
    local st = C[i]
    if c.flow and st.status == "active" then
      if c.flow == "parallel" then
        for _, child in ipairs(c.children) do
          if C[child].status == "idle" then ENTER(child) end
        end
      else
        if st.cursor < 1 or st.cursor > #c.children then st.cursor = 1 end
        local cur = c.children[st.cursor]
        if C[cur].status == "idle" then ENTER(cur) end
      end
    end
  end
end

-- ---------------------------------------------------------------- tick の手順（runtime.md §2）
local function deliver()
  local q = Q
  Q = {}
  for _, msg in ipairs(q) do
    local i = msg.to
    local c = CIRCLES[i]
    local delivered = false
    if is_active(i) and c.on and c.on.message then
      delivered = true
    end
    if DEBUG and msg.meta then
      ROW("emit", msg.meta.ci, msg.name, msg.meta.pointer, msg.meta.args_json, JB(delivered))
    end
    if delivered then
      if DEBUG then
        local inner = (msg.meta and msg.meta.args_json) or "[]"
        local input = "[" .. JS(msg.name)
        if inner ~= "[]" then input = input .. "," .. string.sub(inner, 2, -2) end
        ROW("event", i, "message", c.on_ptr.message, input .. "]", nil)
      end
      local args = { msg.name }
      for k, v in ipairs(msg.args) do args[k + 1] = v end
      RUN(i, c.on.message, c.on_waits.message, args)
    end
  end
  -- v1 の陣の答え（入力イベント reply・runtime.md §11）を、id を出した陣の on message へ (sigil 名, id, text) で。
  -- id を知らない / 宛先が active でない / on message が無いときは捨てる（emit 行の output が false）。
  for _, ev in ipairs(INPUTS.events) do
    if ev.kind == "reply" then
      local id = math.tointeger(ev.id)
      local a = id and ASK_MAP[id] or nil
      local text = RSTR(ev.text) or ""
      local delivered = false
      local c = a and CIRCLES[a.ci] or nil
      if a and is_active(a.ci) and c.on and c.on.message then delivered = true end
      if DEBUG then
        ROW("emit", a and a.ci or nil, a and a.name or nil, a and a.pointer or nil,
          "[" .. JN(id and (id + 0.0) or 0.0) .. "," .. JS(text) .. "]", JB(delivered))
      end
      if id then ASK_MAP[id] = nil end
      if delivered then
        if DEBUG then
          ROW("event", a.ci, "message", c.on_ptr.message,
            "[" .. JS(a.name) .. "," .. JN(id + 0.0) .. "," .. JS(text) .. "]", nil)
        end
        RUN(a.ci, c.on.message, c.on_waits.message, { a.name, id + 0.0, text })
      end
    end
  end
end

local function resume_waits()
  for _, i in ipairs(ORDER()) do
    if is_active(i) then
      local pending = C[i].waits
      C[i].waits = {}
      for _, w in ipairs(pending) do
        local go = false
        if w.ticks then
          w.ticks = w.ticks - 1
          go = w.ticks <= 0
        else
          go = w.until_() and true or false
        end
        if go and C[i].status == "active" then
          if DEBUG then
            ROW("wait", i, nil, w.pointer, w.ticks and '{"ticks":0}' or '{"until":true}', '"resume"')
          end
          resume(i, w.co, {})
        elseif C[i].status == "active" then
          local waits = C[i].waits
          waits[#waits + 1] = w
        else
          coroutine.close(w.co)
        end
      end
    end
  end
end

local function dispatch_events()
  local dt = 1.0 / FPS
  for _, i in ipairs(ORDER()) do
    if is_active(i) then
      local c = CIRCLES[i]
      local on = c.on
      if on then
        for _, ev in ipairs(INPUTS.events) do
          if STOP(i) then break end
          if ev.kind == "key" and on.key then
            local down = ev.down and true or false
            if DEBUG then ROW("event", i, "key", c.on_ptr.key, "[" .. JS(ev.name) .. "," .. JB(down) .. "]", nil) end
            RUN(i, on.key, c.on_waits.key, { ev.name, down })
          elseif ev.kind == "pointer" and on.pointer then
            local p = { f_0 = ev.x + 0.0, f_1 = ev.y + 0.0, f_2 = ev.down and true or false }
            if DEBUG then ROW("event", i, "pointer", c.on_ptr.pointer, "[" .. JPOINTER(p) .. "]", nil) end
            RUN(i, on.pointer, c.on_waits.pointer, { p })
          end
        end
        if not STOP(i) and on.tick then
          if DEBUG then ROW("event", i, "tick", c.on_ptr.tick, "[" .. JN(dt) .. "]", nil) end
          RUN(i, on.tick, c.on_waits.tick, { dt })
        end
      end
    end
  end
end

-- 4. 確定: 核あり陣すべて（idle の陣も。summon で書かれた state が読めるように）
local function publish_all()
  for i = 1, #CIRCLES do publish(i) end
end

local function check_guards()
  for _, i in ipairs(ORDER()) do
    if is_active(i) then
      local c = CIRCLES[i]
      if c.guards then
        for _, g in ipairs(c.guards) do
          if not g.fn() then
            ROW("assert", i, nil, g.pointer, nil, g.message and JS(g.message) or "null")
          end
        end
      end
    end
  end
end

local function step(t)
  TICK = t
  deliver()
  resume_waits()
  dispatch_events()
  publish_all()
  if DEBUG then check_guards() end
  ADVANCE()
end

-- スケジューラの pcall はここ 1 か所（jil.md §2）。boot と tick の両方がここを通る。
local function protected(fn)
  local ok, e = pcall(fn)
  if ok then return end
  DONE = true
  if type(e) == "table" then
    ERRMSG = tostring(e.message or e.code or "error")
  else
    ERRMSG = tostring(e)
  end
  if DEBUG then ROW("error", CUR_CI, nil, CUR_PTR, nil, JS(ERRMSG)) end
end

local function result()
  local parts = {}
  parts[1] = '{"ops":' .. JAA(OPS) .. ',"audio":' .. JAA(AUDIO)
  if DEBUG then
    local rows = {}
    for k, row in ipairs(TRACE) do rows[k] = JROW(row) end
    parts[2] = ',"trace":[' .. table.concat(rows, ",") .. "]"
  else
    parts[2] = ""
  end
  local pubs = {}
  for i = 1, #CIRCLES do
    local c = CIRCLES[i]
    if c.pub and C[i].published then pubs[#pubs + 1] = c.pub() end
  end
  parts[3] = ',"done":' .. JB(DONE) .. ',"error":' .. (ERRMSG and JS(ERRMSG) or "null")
    .. ',"public":{' .. table.concat(pubs, ",") .. "}"
  -- storage の書き込みがあった tick だけ（release でも出る。abilities.md §8）。
  if #STORE_OUT > 0 then
    local writes = {}
    for k, w in ipairs(STORE_OUT) do writes[k] = "[" .. JS(w[1]) .. "," .. JS(w[2]) .. "]" end
    parts[4] = ',"storage":[' .. table.concat(writes, ",") .. "]"
  else
    parts[4] = ""
  end
  -- v1 の陣への問いがあった tick だけ（release でも出る。runtime.md §11）。
  if #ASKS > 0 then
    local asks = {}
    for k, a in ipairs(ASKS) do
      asks[k] = '{"id":' .. JN(a.id + 0.0) .. ',"circle":' .. JS(CIRCLES[a.ci].name)
        .. ',"name":' .. JS(a.name) .. ',"prompt":' .. JS(a.prompt) .. "}"
    end
    parts[5] = ',"asks":[' .. table.concat(asks, ",") .. "]"
  else
    parts[5] = ""
  end
  -- DEBUG だけ: 状態を保った差し替えのための snapshot と、復元の直後 1 回だけの resume。
  if DEBUG then
    parts[6] = ',"snapshot":' .. snapshot_json()
    parts[7] = RESUME_NOTE and (',"resume":' .. resume_note_json()) or ""
  else
    parts[6] = ""
    parts[7] = ""
  end
  parts[8] = "}"
  return table.concat(parts)
end

-- ---------------------------------------------------------------- ホスト境界（runtime.md §1）
function boot(seed, manifest)
  if ARM then ARM() end
  if math.maxinteger ~= 9223372036854775807 then
    error("Lua の整数が 64 bit ではありません")
  end
  MANIFEST = manifest
  -- 状態を保った差し替え: manifest.resume（直前の tick 結果の snapshot）があれば、通常の boot の代わりに
  -- 名前で照合して状態を写す（runtime.md §1 / §10・設計書 §11 #42〜#44）。DEBUG でなくても受けるが、
  -- snapshot を出すのは DEBUG だけなので実際にはデバッグビルドでだけ起きる。
  local resume = nil
  STORAGE_BASE = nil
  if RREC(manifest) ~= nil then
    resume = RREC(manifest.resume)
    STORAGE_BASE = RREC(manifest.storage)
  end
  STORE = {}
  STORE_OUT = {}
  ASKS = {}
  ASKED = 0
  ASK_MAP = {}
  SEQ = 0
  TICK = -1
  DONE = false
  ERRMSG = nil
  Q = {}
  OPS = {}
  AUDIO = {}
  TRACE = {}
  LAST_DOWN = false
  CUR_PTR = nil
  CUR_CI = nil
  RESUME_NOTE = nil
  fresh_state()
  seed = math.tointeger(seed) or 0
  -- 乱数列は seed と状態の組で決まる。snapshot の seed を優先する（ホストが別の seed を渡しても割れない）。
  if resume ~= nil and math.tointeger(resume.seed) then seed = math.tointeger(resume.seed) end
  SEED = seed
  rng_seed(seed)
  local resumed = false
  protected(function()
    if resume ~= nil then resumed = restore_from(resume) end
    if resumed then
      repair_flows()
      ADVANCE()
    else
      ENTER(ROOT)
      ADVANCE()
    end
  end)
  -- 通常の boot は全陣を確定する。復元では確定値 P を snapshot から写したので触らない
  -- （tick の終わりの進行で set された値は次 tick の 4 まで P に出ない・設計書 §11 #43）。
  if not resumed then publish_all() end
  OPS = {}
  AUDIO = {}
end

function tick(t, inputs)
  if ARM then ARM() end
  OPS = {}
  AUDIO = {}
  INK = "#fff"
  if DONE then
    local out = result()
    TRACE = {}
    STORE_OUT = {}
    ASKS = {}
    RESUME_NOTE = nil
    return out
  end
  prepare_inputs(inputs)
  protected(function() step(t) end)
  if DEBUG then
    ROW("frame", nil, nil, "/stage", nil, '{"ops":' .. JAA(OPS) .. ',"audio":' .. JAA(AUDIO) .. "}")
  end
  local out = result()
  TRACE = {}
  -- boot（核の手順）で書いた分は最初の tick の結果に載せる。空にするのは返した後（TRACE と同じ）。
  STORE_OUT = {}
  ASKS = {}
  RESUME_NOTE = nil
  return out
end
