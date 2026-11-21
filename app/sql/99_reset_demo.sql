-- ============================================================================
-- 演示数据重置（仅用于开发/验收；生产禁止执行）
--
-- 为何需要：§2.4 禁止物理删除会计记录，因此正常运维不能 DELETE。
-- 但开发期需要可复现的干净基线，故在**停用触发器**后清空业务表并重新播种。
-- 生产环境不得运行本脚本。
-- ============================================================================
SET FOREIGN_KEY_CHECKS = 0;

-- 停用不可删除触发器（否则无法清理）
DROP TRIGGER IF EXISTS trg_je_before_delete;
DROP TRIGGER IF EXISTS trg_jl_before_delete;
DROP TRIGGER IF EXISTS trg_inv_before_delete;
DROP TRIGGER IF EXISTS trg_bankline_before_delete;
DROP TRIGGER IF EXISTS trg_audit_before_delete;
DROP TRIGGER IF EXISTS trg_invfile_before_delete;

TRUNCATE TABLE settlements;
TRUNCATE TABLE journal_lines;
TRUNCATE TABLE journal_entries;
TRUNCATE TABLE invoice_files;
TRUNCATE TABLE invoices;
TRUNCATE TABLE bills;
TRUNCATE TABLE expenses;
TRUNCATE TABLE bank_lines;
TRUNCATE TABLE statement_imports;
TRUNCATE TABLE pending_review;
TRUNCATE TABLE tax_adjustments;
TRUNCATE TABLE audit_log;
TRUNCATE TABLE period_locks;

SET FOREIGN_KEY_CHECKS = 1;
