-- Words that should never appear as candidates, regardless of dictionary source.
-- Add one entry per line. This filters candidates; it does not edit the userdb.
local blocked = {
  ["手机商"] = true,
}

return function(input, env)
  for cand in input:iter() do
    if not blocked[cand.text] then
      yield(cand)
    end
  end
end
