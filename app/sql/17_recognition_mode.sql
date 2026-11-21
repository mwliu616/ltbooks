-- ============================================================================
-- 收入确认模式（按合同选择）
--
--   on_invoice  随开票确认 —— 开票即确认收入，合同只跟踪开票/收款进度
--   progress    按履约进度确认 —— 严格 HKFRS 15，履约早于开票时确认合同资产
--
-- 两种模式并存，按合同各自选择。
-- ============================================================================
ALTER TABLE revenue_contracts
  ADD COLUMN recognition_mode ENUM('on_invoice','progress') NOT NULL DEFAULT 'on_invoice'
  COMMENT 'on_invoice=随开票确认；progress=按履约进度确认'
  AFTER currency,
  ADD COLUMN mode_note VARCHAR(300) NULL COMMENT '模式选择依据，便于审计追溯'
  AFTER recognition_mode;
