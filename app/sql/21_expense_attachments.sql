-- ============================================================================
-- 21 · 费用单也能挂原始凭证
--
-- 原来 invoice_files 只支持 invoices / bills。AI 界面导入的费用类单据
-- 也需要把原件存成附件，否则费用没有凭证可追溯。
-- ============================================================================

-- 1) 增加费用侧关联
ALTER TABLE invoice_files
  ADD COLUMN expense_id BIGINT UNSIGNED NULL AFTER bill_id,
  ADD KEY idx_invfile_expense (expense_id);

-- 2) 外键：expenses 表用什么主键先确认（expense_id）
ALTER TABLE invoice_files
  ADD CONSTRAINT fk_invfile_expense FOREIGN KEY (expense_id) REFERENCES expenses (expense_id);

-- 3) 归属约束改为三选一
ALTER TABLE invoice_files DROP CONSTRAINT chk_invfile_owner;
ALTER TABLE invoice_files
  ADD CONSTRAINT chk_invfile_owner
  CHECK (invoice_id IS NOT NULL OR bill_id IS NOT NULL OR expense_id IS NOT NULL);

-- 4) 去重维度带上费用
ALTER TABLE invoice_files DROP INDEX uk_invfile_hash;
ALTER TABLE invoice_files
  ADD UNIQUE KEY uk_invfile_hash (invoice_id, bill_id, expense_id, sha256_hash);
