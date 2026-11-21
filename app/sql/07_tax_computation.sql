-- ============================================================================
-- 利得税计算表（按香港税务局 BIR51 的结构）
--
-- 结构：会计利润 → 加回不可扣税开支 → 减非应课税收入
--       → 经调整的应评税利润 → 减资本免税额 → 应评税利润 → 按两级制计税
--
-- 调整必须逐项列示并可追溯到依据，不能只填一个总数。
-- ============================================================================

CREATE TABLE IF NOT EXISTS tax_adjustment_lines (
  line_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id   BIGINT UNSIGNED NOT NULL,
  period      CHAR(7) NOT NULL COMMENT '课税年度基期，YYYY-MM',
  category    ENUM('add_back','deduct','capital_allowance') NOT NULL
              COMMENT 'add_back=加回不可扣税开支；deduct=减非应课税收入；capital_allowance=资本免税额',
  item_name   VARCHAR(200) NOT NULL,
  amount      DECIMAL(20,2) NOT NULL,
  basis_note  VARCHAR(500) NULL COMMENT '依据，如《税务条例》第17条',
  created_by  VARCHAR(64) NULL,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (line_id),
  KEY idx_taxline_entity_period (entity_id, period, category),
  CONSTRAINT fk_taxline_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 课税年度备注与暂缴税，挂在 tax_adjustments 上
ALTER TABLE tax_adjustments
  ADD COLUMN year_of_assessment VARCHAR(16) NULL COMMENT '如 2026/27' AFTER period,
  ADD COLUMN basis_period_start DATE NULL AFTER year_of_assessment,
  ADD COLUMN basis_period_end   DATE NULL AFTER basis_period_start,
  ADD COLUMN provisional_tax_paid DECIMAL(20,2) NOT NULL DEFAULT 0 AFTER tax_payable;
