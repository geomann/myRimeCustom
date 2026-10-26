--[[
no_english_filter —— 中文输入时不混出英文候选

作用：丢弃「由 ASCII 英文字母组成」的候选项，例如 Chrome、CleanShot X、
GitHub Desktop、readme.md、v2ex.com 等。
含汉字、符号或 emoji 的候选（B站、U盘、Up主、㎡、🐂️🍺️）不受影响；
纯符号候选（> ≥ < ≤）也不算英文，同样保留。

这些英文候选原本来自两处：
  1. easy_en 英文码表（table_translator@english）
  2. custom_phrase.txt 里手工加的英文短码条目（ch → Chrome、cs → CleanShot X …）
在候选层面统一拦截，词库数据保持原样，随时可恢复。

想恢复中英混输：把方案里的 `lua_filter@no_english_filter` 一行注释掉，
重新部署即可。
--]]

local function is_plain_english(text)
  if text == nil or text == "" then
    return false
  end
  local has_latin = false
  for i = 1, #text do
    local byte = text:byte(i)
    if byte < 0x20 or byte > 0x7E then
      return false -- 含非 ASCII 字节（汉字、全角符号、emoji…）→ 保留
    end
    if (byte >= 0x41 and byte <= 0x5A) or (byte >= 0x61 and byte <= 0x7A) then
      has_latin = true
    end
  end
  return has_latin
end

return function(input, env)
  for cand in input:iter() do
    if not is_plain_english(cand.text) then
      yield(cand)
    end
  end
end
