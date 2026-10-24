-- stroke_filter.lua  ——  「拼音 + 笔画辅码」候选筛选滤镜
--
-- 来源：fork 自 mirtlecn/rime-radical-pinyin 的 lua/search.lua
--       https://github.com/mirtlecn/rime-radical-pinyin   （原作者 Mirtle）
--       本文件按其原仓库许可使用（个人自用）。
--
-- 与上游的差异（fork 的三点理由）：
--   1) 裁剪：只保留 reverse db（以字查码）单路。移除 schema 反查、
--      码表投影（fuma_format / code_projection）、用户词库写入（input2code_format）等分支。
--   2) 新增：总开关 option（默认名 `stroke_filter`）。关闭时逐条原样放行，对输入零影响。
--   3) 修正：上游在未配置 search/wildcard 时会把通配符当成空串，
--      经 s:gsub('', '.*') 退化成「顺序包含」匹配 —— 那会让「灵」(zhhnppn，首笔折)
--      因“含 h”而被错误保留。本版未配 wildcard 时严格做前缀匹配 part:find('^'..s)。
--
-- 工作机制：
--   输入串形如   <主码><引导键><辅码>      例如  lk`h
--   → 取候选首字，用 ReverseLookup 查其笔画串
--   → 与辅码做「前缀匹配」：lk`h ⇒ 只认笔画串以 h 开头者（即首笔为横）
--   → 命中的候选提前；show_other_cands=false 时则只保留命中的
--   引导键默认为 `（由 key_binder 把 Tab 改写成 ` 得到）。
--
-- 笔画键位（本方案）：
--   h=横  s=竖  p=撇  n=点  z=折        ← Rime 内置 stroke 码表的字符集
--   d=点（别名）                        ← 搜狗等输入法的习惯用 d 表示点
--   注：stroke.dict.yaml 的码表只用 h s p n z 五个字符，没有 d；
--       若不映射，输入 d 会命中 0 个候选（表现为“按了没反应”）。
--       支持多笔画连写，如 ke`nd = ke + 首笔点 + 次笔点。

-- 诊断开关（排障期开；确认无误后设为 false 即可）
local DEBUG = true

-- 诊断落点：同时 print + 追加写文件（print 的日志级别常被过滤，写文件更可靠）
local user_dir = rime_api and rime_api.get_user_data_dir and rime_api.get_user_data_dir() or '.'
local DEBUG_LOG = user_dir .. '/stroke_filter.debug.log'

local function dlog( msg )
    if not DEBUG then return end
    local line = '[stroke_filter] ' .. tostring( msg )
    pcall( function() print( line ) end )
    pcall( function()
        local fh = io.open( DEBUG_LOG, 'a' )
        if fh then
            fh:write( os.date( '%m-%d %H:%M:%S ' ) .. line .. '\n' )
            fh:close()
        end
    end )
end

-- seg 的 tag 判定：双路探测
--   上游写法是 seg.tags[v]（tags 为 table）；另有版本暴露 seg:has_tag(v)
--   两者都试，任一命中即算 —— 避免「方法不存在导致静默 false」这类隐形失效
local function seg_has_tag( seg, tag )
    if not seg then return false end
    local ok_t, tags = pcall( function() return seg[ 'tags' ] end )
    if ok_t and type( tags ) == 'table' and tags[ tag ] then return true end
    local ok_m, v = pcall( function() return seg:has_tag( tag ) end )
    if ok_m and v then return true end
    return false
end

-- 安全体检：一次看清 seg 的真实结构（全程 pcall，绝不抛异常）
local function probe_seg( seg )
    if not seg then return 'seg=nil' end
    local out = {}
    pcall( function()
        local t = seg[ 'tags' ]
        out[ #out + 1 ] = 'tags_type=' .. type( t )
        if type( t ) == 'table' then
            local ks = {}
            for k, v in pairs( t ) do ks[ #ks + 1 ] = tostring( k ) .. '=' .. tostring( v ) end
            out[ #out + 1 ] = 'tags={' .. table.concat( ks, ',' ) .. '}'
        end
        out[ #out + 1 ] = 'has_tag=' .. type( seg[ 'has_tag' ] )
        out[ #out + 1 ] = 'start=' .. tostring( seg[ 'start' ] )
        -- 注意：librime-lua 里 Segment.end 绑定为 _end（end 是 lua 关键字）
        out[ #out + 1 ] = '_end=' .. tostring( seg[ '_end' ] )
        out[ #out + 1 ] = 'status=' .. tostring( seg[ 'status' ] )
    end )
    return table.concat( out, ' ' )
end

-- 笔画辅码归一化
--   ① 别名映射：默认 d → n（点），兼容搜狗 hspdz 习惯
--   ② 剔除非法字符：只保留 h s p n z，其余字符丢弃（并回报，供日志）
--   返回：归一化后的串、被丢弃的字符
local DEFAULT_STROKE_ALIAS = { d = 'n' }

local function normalize_fuma( s, alias )
    alias = alias or DEFAULT_STROKE_ALIAS
    local out, dropped = {}, ''
    for ch in s:gmatch( '.' ) do
        local m = alias[ ch ] or ch
        if m:match( '^[hspnz]$' ) then
            out[ #out + 1 ] = m
        else
            dropped = dropped .. ch
        end
    end
    return table.concat( out ), dropped
end

local function alt_lua_punc( s )
    if s then
        return ( s:gsub( '([%.%+%-%*%?%[%]%^%$%(%)%%])', '%%%1' ) )
    end
    return ''
end

local function cfg_str( config, path, default )
    local v = config:get_string( path )
    if v == nil or #v == 0 then return default end
    return v
end

-- 以字查码：取该字笔画串的每一段，与辅码做前缀匹配
local function reverse_lookup( db_table, wildcard, text, s )
    if wildcard then s = s:gsub( wildcard, '.*' ) end
    for _, db in ipairs( db_table ) do
        local code = db:lookup( text )
        if code and #code > 0 then
            for part in code:gmatch( '%S+' ) do
                if part:find( '^' .. s ) then return true end
            end
        end
    end
    return false
end

-- 单字优先：开启时把多字候选先攒起来，最后再吐，让单字先出现
local function handle_long_cand( if_single_char_first, cand, long_word_cands )
    if if_single_char_first and utf8.len( cand.text ) > 1 then
        table.insert( long_word_cands, cand )
    else
        yield( cand )
    end
end

local f = {}

function f.init( env )
    local config = env.engine.schema.config
    local ns = 'search'

    -- ---- 标量配置：先全部就绪，保证 func / tags_match 不会读到 nil ----
    env.option_name      = cfg_str( config, ns .. '/option_name', 'stroke_filter' )
    env.show_other_cands = config:get_bool( ns .. '/show_other_cands' )
    env.code_pattern     = cfg_str( config, ns .. '/code_pattern', '[a-z;]' )

    local search_key = config:get_string( 'key_binder/search' )
    if search_key == nil or #search_key == 0 then
        search_key = cfg_str( config, ns .. '/key', '`' )
    end
    env.search_key     = search_key
    env.search_key_alt = alt_lua_punc( search_key )

    env.tag = { 'abc' }
    local tag = config:get_list( ns .. '/tags' )
    if tag and tag.size > 0 then
        env.tag = {}
        for i = 0, tag.size - 1 do table.insert( env.tag, tag:get_value_at( i ).value ) end
    end

    -- ---- 反查库（reverse db）----
    env.db_table = {}
    env.if_reverse_lookup = false
    local db = config:get_list( ns .. '/db' )
    if db and db.size > 0 then
        for i = 0, db.size - 1 do
            table.insert( env.db_table, ReverseLookup( db:get_value_at( i ).value ) )
        end
        env.if_reverse_lookup = #env.db_table > 0
    end

    -- 通配：仅显式配置时才启用；否则严格前缀匹配（见文件头第 3 点）
    local wildcard = config:get_string( ns .. '/wildcard' )
    if wildcard and #wildcard > 0 then
        env.wildcard = alt_lua_punc( wildcard )
    else
        env.wildcard = nil
    end

    dlog( string.format(
        'init: key=%q db=%d option=%s show_other=%s',
        env.search_key, #env.db_table, env.option_name,
        tostring( env.show_other_cands ) ) )

    -- ---- 上屏接管：选词组保留引导码（可继续给下一字加辅码），选单字剥离引导码 ----
    env.notifier = nil
    if env.if_reverse_lookup then
        env.notifier = env.engine.context.select_notifier:connect( function( ctx )
            local code = ctx.input:match( '^(.-)' .. env.search_key_alt )
            if (not code or #code == 0) then return end

            local preedit = ctx:get_preedit()
            local no_search_string = ctx.input:match( '^(.-)' .. env.search_key_alt )
            local edit = preedit.text:match( '^(.-)' .. env.search_key_alt )

            if edit and edit:match( env.code_pattern ) then
                ctx.input = no_search_string .. env.search_key
            else
                ctx.input = no_search_string
                ctx:commit()
            end
        end )
    end
end

function f.func( input, env )
    local ctx = env.engine.context
    local raw_input = ctx.input or ''
    local interested = raw_input:find( env.search_key, 1, true ) ~= nil

    -- ① 总开关：关闭 → 逐条原样放行，零副作用
    if not ctx:get_option( env.option_name ) then
        if interested then dlog( 'func: option OFF, pass-through. input=' .. raw_input ) end
        for cand in input:iter() do yield( cand ) end
        return
    end

    -- ② 仅当输入串含 <引导键>+辅码 时才介入，否则零副作用
    local code, fuma = raw_input:match( '^(.-)' .. env.search_key_alt .. '(.+)$' )
    if (not code or #code == 0) or (not fuma or #fuma == 0) or not env.if_reverse_lookup then
        if interested then
            dlog( string.format(
                'func: NOT engaged (code=%q fuma=%q rl=%s). input=%s',
                tostring( code ), tostring( fuma ),
                tostring( env.if_reverse_lookup ), raw_input ) )
        end
        for cand in input:iter() do yield( cand ) end
        return
    end

    local if_single_char_first = ctx:get_option( 'search_single_char' )
    local other_cand = {}
    local long_word_cands = {}
    local n_in, n_hit = 0, 0

    -- ③ 辅码归一化：键位别名（d→n）+ 剔除非法字符
    --    不归一化的话，搜狗习惯的 d（点）会因为不在 stroke 码表里而命中 0，表现为“没反应”
    local fuma_raw = fuma
    do
        local norm, dropped = normalize_fuma( fuma )
        if #dropped > 0 then
            dlog( string.format(
                'func: 辅码含非笔画键 [%s] 已忽略；原始=%s 归一化=%s',
                dropped, fuma_raw, norm ) )
        end
        if #norm == 0 then
            dlog( 'func: 归一化后辅码为空，原样放行。input=' .. raw_input )
            for cand in input:iter() do yield( cand ) end
            return
        end
        fuma = norm
    end

    for cand in input:iter() do
        n_in = n_in + 1
        if cand.type ~= 'sentence' then
            local cand_text = cand.text
            local text = cand_text
            -- 候选多于一个字时，只取首字与辅码比对
            if utf8.len( cand_text ) and utf8.len( cand_text ) > 1 then
                text = cand_text:sub( 1, utf8.offset( cand_text, 2 ) - 1 )
            end

            if reverse_lookup( env.db_table, env.wildcard, text, fuma ) then
                n_hit = n_hit + 1
                handle_long_cand( if_single_char_first, cand, long_word_cands )
            else
                table.insert( other_cand, cand )
            end
        end
    end

    dlog( string.format(
        'func: ENGAGED input=%s code=%s fuma=%s(raw %s) cand_in=%d hit=%d single_first=%s',
        raw_input, code, fuma, fuma_raw, n_in, n_hit, tostring( if_single_char_first ) ) )

    -- 命中 0 时显式告警：多半是辅码字符不在笔画集里，或该拼音下确实无此首笔的字
    if n_hit == 0 then
        dlog( string.format(
            'func: WARN hit=0（拼音【%s】的候选里没有首笔为【%s】的字，或辅码字符非法）',
            code, fuma ) )
    end

    -- 上屏命中的（顺序：单字在前，词组在后）
    for _, cand in ipairs( long_word_cands ) do yield( cand ) end
    -- 不匹配的：show_other_cands=true 时后置保留（“优先出现”），false 时丢弃（“只留命中”）
    if env.show_other_cands then
        for _, cand in ipairs( other_cand ) do yield( cand ) end
    end
end

function f.tags_match( seg, env )
    local ctx = env.engine.context
    local raw_input = ( ctx and ctx.input ) or ''

    local match = false
    for _, v in ipairs( env.tag or { 'abc' } ) do
        if seg_has_tag( seg, v ) then match = true; break end
    end

    if DEBUG and raw_input:find( env.search_key, 1, true ) then
        dlog( string.format( 'tags_match: input=%s match=%s %s',
            raw_input, tostring( match ), probe_seg( seg ) ) )
    end

    return match
end

function f.fini( env )
    if env.notifier then env.notifier:disconnect() end
    env.db_table = nil
    collectgarbage( 'collect' )
end

return f
