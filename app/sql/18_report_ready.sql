-- ============================================================================
-- 对账门禁：未经银行对账的业务单据不进财务报表
--
--   report_ready = 1  已对账，计入报表
--   report_ready = 0  待对账，不计入报表
--
-- 由销售发票 / 采购发票 / 收付款生成的分录初始为 0，
-- 与银行流水核销（settlements）后置为 1。
-- 手工分录、期初、重估等直接为 1。
-- ============================================================================
ALTER TABLE journal_entries
  ADD COLUMN report_ready TINYINT(1) NOT NULL DEFAULT 1
    COMMENT '1=已对账计入报表；0=待对账不计入报表'
    AFTER status,
  ADD COLUMN reconciled_at DATETIME(3) NULL COMMENT '对账确认时间' AFTER report_ready,
  ADD COLUMN reconciled_by VARCHAR(100) NULL COMMENT '对账确认人' AFTER reconciled_at,
  ADD KEY idx_je_ready (entity_id, report_ready, entry_date);
