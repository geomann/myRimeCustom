-- Put existing candidates first for an exact input code.
-- Format: [schema_id] = { [input_code] = { "first", "second", ... } }
-- Flypy uses ui for shi; Luna Pinyin uses shi.
return {
  flypy_bt = {
    ui = { "是" },
  },
  double_pinyin_flypy = {
    ui = { "是" },
  },
  luna_pinyin_simp = {
    shi = { "是" },
  },
}
