-- ============================================================================
-- 附件支持采购发票
--
-- 原表只挂在 invoices（销售）上；用户上传的发票多为供应商开给我的采购发票，
-- 必须能挂到 bills 上，否则采购单据没有原始凭证可追溯。
-- ============================================================================

-- 1) 销售侧改为可空，允许只挂采购
ALTER TABLE invoice_files
  MODIFY COLUMN invoice_id BIGINT UNSIGNED NULL;

-- 2) 增加采购侧关联
ALTER TABLE invoice_files
  ADD COLUMN bill_id BIGINT UNSIGNED NULL AFTER invoice_id,
  ADD KEY idx_invfile_bill (bill_id),
  ADD CONSTRAINT fk_invfile_bill FOREIGN KEY (bill_id) REFERENCES bills (bill_id);

-- 3) 去重约束按单据维度重建
ALTER TABLE invoice_files DROP INDEX uk_invfile_hash;
ALTER TABLE invoice_files
  ADD UNIQUE KEY uk_invfile_hash (invoice_id, bill_id, sha256_hash);

-- 4) 一张附件必须至少属于一张单据
ALTER TABLE invoice_files
  ADD CONSTRAINT chk_invfile_owner CHECK (invoice_id IS NOT NULL OR bill_id IS NOT NULL);
