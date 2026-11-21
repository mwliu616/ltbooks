-- ============================================================================
-- 收入合同附件（合同扫描件、签署页、附件条款等）
-- ============================================================================
CREATE TABLE IF NOT EXISTS contract_files (
  file_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id      BIGINT UNSIGNED NOT NULL,
  contract_id    BIGINT UNSIGNED NOT NULL,
  file_name      VARCHAR(255) NOT NULL,
  file_type      VARCHAR(32)  NOT NULL DEFAULT 'other',
  file_size      BIGINT UNSIGNED NOT NULL DEFAULT 0,
  sha256_hash    CHAR(64) NOT NULL,
  storage_path   VARCHAR(500) NOT NULL,
  uploaded_by    VARCHAR(100) NOT NULL,
  uploaded_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  retention_until DATE NOT NULL,
  PRIMARY KEY (file_id),
  KEY idx_cf_contract (contract_id),
  KEY idx_cf_entity (entity_id, uploaded_at),
  CONSTRAINT fk_cf_contract FOREIGN KEY (contract_id)
    REFERENCES revenue_contracts (contract_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
