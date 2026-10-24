local rules = require("preferred_words")
local SEARCH_LIMIT = 100

return function(input, env)
  local schema_rules = rules[env.engine.schema.schema_id]
  local code = env.engine.context.input
  local wanted = schema_rules and schema_rules[code]

  if not wanted or #wanted == 0 then
    for cand in input:iter() do
      yield(cand)
    end
    return
  end

  -- Look ahead only a bounded number of candidates. Keep their original order
  -- if none of the preferred words exists for this exact code.
  local buffered, picked, picked_at = {}, {}, {}
  local picked_count = 0
  for cand in input:iter() do
    buffered[#buffered + 1] = cand
    if cand.start == 0 and cand._end == #code then
      for rank, word in ipairs(wanted) do
        if cand.text == word and not picked[rank] then
          picked[rank] = cand
          picked_at[#buffered] = true
          picked_count = picked_count + 1
          break
        end
      end
    end
    if picked_count == #wanted or #buffered >= SEARCH_LIMIT then
      break
    end
  end

  for rank = 1, #wanted do
    if picked[rank] then
      yield(picked[rank])
    end
  end
  for index, cand in ipairs(buffered) do
    if not picked_at[index] then
      yield(cand)
    end
  end
  for cand in input:iter() do
    yield(cand)
  end
end
