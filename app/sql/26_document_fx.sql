-- LtBooks Ver 1.0：报价单、贷记单真实外币折算字段及干净安装基表。
-- 外币金额只由已维护汇率计算；查不到汇率时保留 NULL，禁止以 1 或 0 冒充。
CREATE TABLE IF NOT EXISTS quotes (
  quote_id BIGINT NOT NULL AUTO_INCREMENT,
  entity_id BIGINT NOT NULL DEFAULT 1,
  quote_no VARCHAR(64) NOT NULL,
  customer_id BIGINT NULL,
  customer_name VARCHAR(200) NOT NULL,
  subject VARCHAR(200) NULL,
  reference VARCHAR(100) NULL,
  salesperson VARCHAR(100) NULL,
  quote_date DATE NOT NULL,
  valid_until DATE NULL,
  currency CHAR(3) NOT NULL DEFAULT 'HKD',
  amount_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  tax_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  discount_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  gross_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  amount_functional DECIMAL(18,2) NULL COMMENT '按真实汇率折算的含税功能货币金额',
  fx_rate DECIMAL(18,10) NULL COMMENT '原币兑功能货币汇率',
  fx_rate_date DATE NULL COMMENT '实际采用的汇率日期',
  contract_id BIGINT NULL,
  terms VARCHAR(600) NULL,
  notes VARCHAR(600) NULL,
  status ENUM('draft','sent','accepted','declined','expired','converted') NOT NULL DEFAULT 'draft',
  converted_invoice_id BIGINT NULL,
  created_by VARCHAR(64) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (quote_id),
  UNIQUE KEY uk_quote (entity_id, quote_no),
  KEY idx_cust (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS quote_lines (
  line_id BIGINT NOT NULL AUTO_INCREMENT,
  entity_id BIGINT NOT NULL DEFAULT 1,
  quote_id BIGINT NOT NULL,
  line_no INT NOT NULL,
  description VARCHAR(400) NOT NULL,
  unit VARCHAR(32) NULL,
  quantity DECIMAL(18,4) NOT NULL DEFAULT 1,
  unit_price DECIMAL(18,4) NOT NULL DEFAULT 0,
  amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  tax_rate DECIMAL(9,4) NULL,
  tax_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  notes VARCHAR(400) NULL,
  PRIMARY KEY (line_id),
  KEY idx_q (quote_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS credit_notes (
  credit_id BIGINT NOT NULL AUTO_INCREMENT,
  entity_id BIGINT NOT NULL DEFAULT 1,
  credit_no VARCHAR(64) NOT NULL,
  credit_type ENUM('customer','vendor') NOT NULL DEFAULT 'customer',
  party_name VARCHAR(200) NOT NULL,
  credit_date DATE NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'HKD',
  amount_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  tax_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  gross_original DECIMAL(18,2) NOT NULL DEFAULT 0,
  amount_functional DECIMAL(18,2) NULL COMMENT '按真实汇率折算的含税功能货币金额',
  fx_rate DECIMAL(18,10) NULL COMMENT '原币兑功能货币汇率',
  fx_rate_date DATE NULL COMMENT '实际采用的汇率日期',
  reason VARCHAR(400) NULL,
  source_invoice_id BIGINT NULL,
  source_bill_id BIGINT NULL,
  revenue_account_code VARCHAR(32) NULL,
  status ENUM('draft','posted','applied','void') NOT NULL DEFAULT 'draft',
  created_by VARCHAR(64) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (credit_id),
  UNIQUE KEY uk_credit (entity_id, credit_no),
  KEY idx_party (party_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

ALTER TABLE quotes
  ADD COLUMN IF NOT EXISTS amount_functional DECIMAL(18,2) NULL AFTER gross_original,
  ADD COLUMN IF NOT EXISTS fx_rate DECIMAL(18,10) NULL AFTER amount_functional,
  ADD COLUMN IF NOT EXISTS fx_rate_date DATE NULL AFTER fx_rate;

ALTER TABLE credit_notes
  ADD COLUMN IF NOT EXISTS amount_functional DECIMAL(18,2) NULL AFTER gross_original,
  ADD COLUMN IF NOT EXISTS fx_rate DECIMAL(18,10) NULL AFTER amount_functional,
  ADD COLUMN IF NOT EXISTS fx_rate_date DATE NULL AFTER fx_rate;

UPDATE quotes q
  JOIN entities e ON e.entity_id = q.entity_id
   SET q.amount_functional = q.gross_original, q.fx_rate = 1, q.fx_rate_date = q.quote_date
 WHERE BINARY q.currency = BINARY e.functional_currency AND q.amount_functional IS NULL;

UPDATE credit_notes c
  JOIN entities e ON e.entity_id = c.entity_id
   SET c.amount_functional = c.gross_original, c.fx_rate = 1, c.fx_rate_date = c.credit_date
 WHERE BINARY c.currency = BINARY e.functional_currency AND c.amount_functional IS NULL;
