-- ============================================================================
-- HKFRS 15（2022）收入确认 —— 五步法数据模型
--
-- 与既有发票的关系：发票是「已开出的凭证」，合同是「收入确认的对象」。
-- 一张合同可对应多张发票，一张发票也可覆盖多个履约义务。
-- 未建合同的业务仍走原有单一履约状态路径（向后兼容）。
-- ============================================================================

-- 步骤 1：与客户之间的合同
CREATE TABLE IF NOT EXISTS revenue_contracts (
  contract_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id       BIGINT UNSIGNED NOT NULL,
  contract_ref    VARCHAR(64)  NOT NULL,
  customer_id     BIGINT UNSIGNED NULL,
  customer_name   VARCHAR(200) NOT NULL,
  start_date      DATE NOT NULL,
  end_date        DATE NULL,
  currency        CHAR(3) NOT NULL DEFAULT 'HKD',
  -- 步骤 1 五项合同要件（HKFRS 15.9）
  approved            TINYINT(1) NOT NULL DEFAULT 0,
  rights_identifiable TINYINT(1) NOT NULL DEFAULT 0,
  payment_terms       TINYINT(1) NOT NULL DEFAULT 0,
  commercial_substance TINYINT(1) NOT NULL DEFAULT 0,
  probable_collection TINYINT(1) NOT NULL DEFAULT 0,
  collectability_note VARCHAR(500) NULL,
  -- 步骤 3：交易价格组成（均为合同货币）
  stated_price        DECIMAL(20,2) NOT NULL DEFAULT 0,
  variable_consideration DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '经约束后的可变对价',
  financing_component DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '重大融资成分调整额',
  non_cash_consideration DECIMAL(20,2) NOT NULL DEFAULT 0,
  consideration_to_customer DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '应付客户对价',
  transaction_price   DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '计算得出的交易价格',
  status ENUM('draft','active','completed','cancelled') NOT NULL DEFAULT 'draft',
  created_by VARCHAR(100) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (contract_id),
  UNIQUE KEY uq_contract_ref (entity_id, contract_ref),
  KEY idx_contract_cust (entity_id, customer_id),
  CONSTRAINT fk_rc_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 步骤 2：履约义务
CREATE TABLE IF NOT EXISTS performance_obligations (
  po_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  contract_id     BIGINT UNSIGNED NOT NULL,
  seq             SMALLINT UNSIGNED NOT NULL,
  description     VARCHAR(300) NOT NULL,
  -- 步骤 4：单独售价与分摊
  ssp             DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '单独售价 standalone selling price',
  allocation_pct  DECIMAL(9,6) NOT NULL DEFAULT 0,
  allocated_price DECIMAL(20,2) NOT NULL DEFAULT 0,
  discount_allocated DECIMAL(20,2) NOT NULL DEFAULT 0,
  -- 步骤 5：履约方式
  satisfaction_method ENUM('point_in_time','over_time') NOT NULL DEFAULT 'point_in_time',
  overtime_criterion TINYINT UNSIGNED NULL COMMENT 'HKFRS 15.35 三项条件 1/2/3',
  progress_method ENUM('input','output','milestone') NULL,
  progress_pct    DECIMAL(9,6) NOT NULL DEFAULT 0,
  revenue_account_code VARCHAR(20) NOT NULL DEFAULT '4100',
  satisfied_date  DATE NULL,
  status ENUM('unsatisfied','partially_satisfied','satisfied') NOT NULL DEFAULT 'unsatisfied',
  PRIMARY KEY (po_id),
  UNIQUE KEY uq_po_seq (contract_id, seq),
  CONSTRAINT fk_po_contract FOREIGN KEY (contract_id)
    REFERENCES revenue_contracts (contract_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 步骤 3 明细：可变对价等分项（保留计算过程，便于审计）
CREATE TABLE IF NOT EXISTS contract_price_items (
  item_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  contract_id BIGINT UNSIGNED NOT NULL,
  kind ENUM('variable','financing','non_cash','payable_to_customer') NOT NULL,
  label       VARCHAR(200) NOT NULL,
  method ENUM('expected_value','most_likely','straight') NOT NULL DEFAULT 'most_likely',
  amount      DECIMAL(20,2) NOT NULL DEFAULT 0,
  probability DECIMAL(9,6) NULL COMMENT '期望值法下的概率',
  constrained DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '经约束后的计入额',
  constraint_reason VARCHAR(300) NULL,
  PRIMARY KEY (item_id),
  KEY idx_cpi_contract (contract_id),
  CONSTRAINT fk_cpi_contract FOREIGN KEY (contract_id)
    REFERENCES revenue_contracts (contract_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 合同成本（HKFRS 15.91-98）
CREATE TABLE IF NOT EXISTS contract_costs (
  cost_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  contract_id BIGINT UNSIGNED NOT NULL,
  kind ENUM('obtain','fulfil') NOT NULL,
  label       VARCHAR(200) NOT NULL,
  amount      DECIMAL(20,2) NOT NULL DEFAULT 0,
  amortised   DECIMAL(20,2) NOT NULL DEFAULT 0,
  method ENUM('straight_line','units','as_incurred') NOT NULL DEFAULT 'as_incurred',
  PRIMARY KEY (cost_id),
  KEY idx_cc_contract (contract_id),
  CONSTRAINT fk_cc_contract FOREIGN KEY (contract_id)
    REFERENCES revenue_contracts (contract_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 收入确认记录（每个履约义务按期末的累计确认额）
CREATE TABLE IF NOT EXISTS revenue_recognitions (
  recog_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id   BIGINT UNSIGNED NOT NULL,
  contract_id BIGINT UNSIGNED NOT NULL,
  po_id       BIGINT UNSIGNED NOT NULL,
  as_of       DATE NOT NULL,
  cumulative  DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '累计确认收入（合同货币）',
  period_amount DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '本期确认额',
  invoiced    DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '已开票金额',
  entry_id    BIGINT UNSIGNED NULL COMMENT '对应分录',
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (recog_id),
  UNIQUE KEY uq_recog (po_id, as_of),
  KEY idx_recog_contract (contract_id, as_of),
  CONSTRAINT fk_rr_po FOREIGN KEY (po_id) REFERENCES performance_obligations (po_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
