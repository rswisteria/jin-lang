-- Jin v2 プレリュード（docs/spec/v2/runtime.md / jil.md §1 の <prelude>）。jil: 1
--
-- `game.lua` の先頭にそのまま連結される。表示リスト / 入力 / ui / audio / PCG32 / スケジューラ /
-- トレース / JSON 直列化 / 数値書式をここに置き、生成部（<program>）は式とステップだけを出す。
-- すべて local に閉じ、グローバルは末尾の boot / tick の 2 つだけ（jil.md §2）。
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
--     dump = function() return "<state の JSON>" end,           -- enter / exit 行（DEBUG のみ呼ぶ）
--     core = R[i][j], core_waits = bool,
--     on = { tick = R[i][j], key = ..., pointer = ..., message = ..., exit = ... },
--     on_waits = { tick = bool, ... },
--     on_ptr = { tick = "/circles/i/boundary/on/0", ... },
--     guards = { { fn = function() return <bool> end, message = "...", pointer = "/circles/i/boundary/guards/0" }, ... },
--   }
--   R[i] = {} ; R[i][j] = function(a, b) ... end               -- 手順（引数の数は静的）
--   JF[k] = function(v) return "{...}" end                    -- 型紙 k の直列化（JF[0] は Pointer）
-- プレリュードが持つもの:
--   S[i]（陣 i の state。init が返す表）/ P[i]（公開 state の確定値。他陣は P を読む）
--   H（ホスト能力: H.canvas / H.input / H.ui / H.audio / H.random）/ F（純関数）/ E（効果）
--   AT / SETAT（添字）/ WAIT_TICKS / WAIT_UNTIL / FINISH / TRANSFER / EMIT / STOP
--   T / TS / TR / TRET（トレース。DEBUG のときだけ生成部が呼ぶ）
--   CIRCLES[i].pub = function() return '"Play.score":' .. JN(P[i].k_2) end   -- 公開 state の JSON 断片（tick の戻り値の public）

local DEBUG = false
local ROOT = 1
local FPS = 60
local CIRCLES = {}
local R = {}
local JF = {}
local S = {}
local P = {}

-- ---------------------------------------------------------------- 実行時の状態
local C = {}          -- C[i] = { status = "idle"|"active"|"done", paused = bool, delegate = j|nil, pending = bool, cursor = n, waits = {} }
local OPS = {}
local AUDIO = {}
local TRACE = {}
local Q = {}          -- 次 tick に配達するメッセージ
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
local MANIFEST = nil

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

local function JS(s)
  return '"' .. string.gsub(s, '[%c"\\]', esc_char) .. '"'
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
    .. ',"public":{' .. table.concat(pubs, ",") .. "}}"
  return table.concat(parts)
end

-- ---------------------------------------------------------------- ホスト境界（runtime.md §1）
function boot(seed, manifest)
  if math.maxinteger ~= 9223372036854775807 then
    error("Lua の整数が 64 bit ではありません")
  end
  MANIFEST = manifest
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
  rng_seed(math.tointeger(seed) or 0)
  protected(function()
    ENTER(ROOT)
    ADVANCE()
  end)
  publish_all()
  OPS = {}
  AUDIO = {}
end

function tick(t, inputs)
  OPS = {}
  AUDIO = {}
  INK = "#fff"
  if DONE then
    local out = result()
    TRACE = {}
    return out
  end
  prepare_inputs(inputs)
  protected(function() step(t) end)
  if DEBUG then
    ROW("frame", nil, nil, "/stage", nil, '{"ops":' .. JAA(OPS) .. ',"audio":' .. JAA(AUDIO) .. "}")
  end
  local out = result()
  TRACE = {}
  return out
end
