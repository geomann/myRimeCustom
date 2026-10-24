-- Block candidate texts in all configured schemes.
-- Managed by manage_words.py; you can also edit this list by hand.
local blocked = {
  ["手机商"] = true,
  ["三个丶"] = true,
}

return function(input, env)
  for cand in input:iter() do
    if not blocked[cand.text] then
      yield(cand)
    end
  end
end
