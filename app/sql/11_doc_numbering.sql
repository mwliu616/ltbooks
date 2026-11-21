-- ============================================================================
-- 统一文件编号：LEDU + 年月日 + 当日第几份
--
-- 例：LEDU20261110001 = 2026-11-10 的第 1 份
-- 序号按「实体 + 日期 + 范围」原子递增，并发下不会重号。
-- ============================================================================

CREATE TABLE IF NOT EXISTS doc_sequences (
  entity_id BIGINT UNSIGNED NOT NULL,
  doc_date  DATE NOT NULL,
  scope     VARCHAR(16) NOT NULL DEFAULT 'ALL',
  last_seq  INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (entity_id, doc_date, scope),
  CONSTRAINT fk_docseq_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 采购发票：bill_no 改为我方档案号（自动），另存供应商发票号（法律凭证）
ALTER TABLE bills
  ADD COLUMN vendor_invoice_no VARCHAR(64) NULL COMMENT '供应商发票号（对方开具的凭证号）'
  AFTER bill_no;
