-- ============================================================================
-- 合同 ↔ 发票 关联
--
-- 合同的收入确认与开票/收款进度挂钩：发票是实际开出的凭证，
-- 关联后合同页可看到开票进度、收款进度与未开票余额。
-- ============================================================================
CREATE TABLE IF NOT EXISTS contract_invoices (
  link_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id   BIGINT UNSIGNED NOT NULL,
  contract_id BIGINT UNSIGNED NOT NULL,
  invoice_id  BIGINT UNSIGNED NOT NULL,
  po_id       BIGINT UNSIGNED NULL COMMENT '可指定该发票对应的履约义务；NULL 表示按分摊比例归集',
  amount      DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '该发票计入本合同的金额（合同货币）',
  linked_by   VARCHAR(100) NOT NULL,
  linked_at   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (link_id),
  UNIQUE KEY uq_ci (contract_id, invoice_id),
  KEY idx_ci_invoice (invoice_id),
  CONSTRAINT fk_ci_contract FOREIGN KEY (contract_id)
    REFERENCES revenue_contracts (contract_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
