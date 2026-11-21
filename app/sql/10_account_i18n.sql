-- ============================================================================
-- 科目三语名称
--
-- 英文为权威来源（会计术语），简繁由映射表给出，
-- 不依赖简繁自动转换，避免「税/稅」「兑/兌」不一致。
-- ============================================================================
ALTER TABLE accounts
  ADD COLUMN name_zh_cn VARCHAR(200) NULL AFTER account_name,
  ADD COLUMN name_zh_hk VARCHAR(200) NULL AFTER name_zh_cn,
  ADD COLUMN name_en    VARCHAR(200) NULL AFTER name_zh_hk;
