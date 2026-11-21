-- ============================================================================
-- 银行流水附件（收款回单、存款单、支票影像等）
-- 对账时即时上传，作为该笔收付款的原始凭证。
-- ============================================================================
CREATE TABLE IF NOT EXISTS bank_line_files (
  file_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id      BIGINT UNSIGNED NOT NULL,
  line_id        BIGINT UNSIGNED NOT NULL,
  file_name      VARCHAR(255) NOT NULL,
  file_type      VARCHAR(32)  NOT NULL DEFAULT 'other',
  file_size      BIGINT UNSIGNED NOT NULL DEFAULT 0,
  sha256_hash    CHAR(64) NOT NULL,
  storage_path   VARCHAR(500) NOT NULL,
  uploaded_by    VARCHAR(100) NOT NULL,
  uploaded_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  retention_until DATE NOT NULL,
  PRIMARY KEY (file_id),
  KEY idx_blf_line (line_id),
  KEY idx_blf_entity (entity_id, uploaded_at),
  CONSTRAINT fk_blf_line FOREIGN KEY (line_id) REFERENCES bank_lines (line_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
