-- ============================================================================
-- LEDU 会计功能台 — 数据层（阶段 1）
-- schema: ledu_accounting
-- 引擎: InnoDB / utf8mb4 / utf8mb4_unicode_ci
--
-- 依据：v5.0 全栈重建规格 §3.1
-- 原则：
--   1. 所有持久化数据在本 schema；文件实体存 storage/，库内只存索引与哈希。
--   2. 唯一约束是防重复入账的最终兜底（§2.3），应用层去重不得替代。
--   3. posted 后禁止 UPDATE 金额/日期/科目、禁止 DELETE（§2.4），
--      由 02_triggers.sql 在数据库层强制。
--   4. 多币种：原币 + 功能货币(HKD) + 汇率 + 汇率日期 全部落库（§2.12）。
--
-- 偏差声明：§3.1.1 列 21 张表；§3.4.3 要求核销，故增加 settlements 承接
-- 收付款与发票/账单的核销明细（含汇兑差额）。此为第 22 张表，已显式声明。
-- ============================================================================

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- 1. entities — 会计实体
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
  entity_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_code          VARCHAR(32)  NOT NULL,
  entity_name          VARCHAR(200) NOT NULL,
  reporting_framework  ENUM('full_hkfrs','hkfrs_pe') NOT NULL DEFAULT 'full_hkfrs',
  -- §2.8 三态：undetermined 时禁止税务计算
  two_tier_status      ENUM('nominated','not_nominated','undetermined') NOT NULL DEFAULT 'undetermined',
  functional_currency  CHAR(3)      NOT NULL DEFAULT 'HKD',
  fiscal_year_end_mmdd CHAR(5)      NOT NULL DEFAULT '12-31',
  status               ENUM('active','archived') NOT NULL DEFAULT 'active',
  created_at           DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at           DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (entity_id),
  UNIQUE KEY uk_entities_code (entity_code)
) ENGINE=InnoDB COMMENT='会计实体';

-- ---------------------------------------------------------------------------
-- 2. accounts — 科目表（§3.1.2）
-- 编码：1 资产 / 2 负债 / 3 权益 / 4 收入 / 5 销售成本 / 6 经营费用
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
  account_code          VARCHAR(20)  NOT NULL,
  entity_id             BIGINT UNSIGNED NOT NULL,
  account_name          VARCHAR(200) NOT NULL,
  category              ENUM('asset','liability','equity','revenue','cogs','expense') NOT NULL,
  fs_line_item          VARCHAR(64)  NOT NULL COMMENT '财务报表行项目（三表聚合依据）',
  normal_balance        ENUM('debit','credit') NOT NULL,
  -- 反向余额重分类目标；NULL = 净额列示（§3.8.2）
  contra_reclass_target VARCHAR(20)      NULL,
  parent_account_code   VARCHAR(20)      NULL COMMENT '父科目，支持子科目',
  is_active             TINYINT(1)   NOT NULL DEFAULT 1,
  created_at            DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (entity_id, account_code),
  KEY idx_accounts_parent (entity_id, parent_account_code),
  KEY idx_accounts_category (entity_id, category),
  KEY idx_accounts_fs (entity_id, fs_line_item),
  CONSTRAINT fk_accounts_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='科目表';

-- ---------------------------------------------------------------------------
-- 3. fx_rates — 汇率缓存（§3.3.2）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fx_rates (
  rate_date   DATE           NOT NULL,
  from_ccy    CHAR(3)        NOT NULL,
  to_ccy      CHAR(3)        NOT NULL,
  rate        DECIMAL(20,10) NOT NULL COMMENT '1 from_ccy = rate to_ccy',
  source      VARCHAR(32)    NOT NULL DEFAULT 'ECB',
  is_fallback TINYINT(1)     NOT NULL DEFAULT 0,
  fetched_at  DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (rate_date, from_ccy, to_ccy),
  KEY idx_fx_pair (from_ccy, to_ccy, rate_date)
) ENGINE=InnoDB COMMENT='汇率缓存；rate_date 为实际使用日';

-- ---------------------------------------------------------------------------
-- 4. customers / 5. vendors — 主数据
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
  customer_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id          BIGINT UNSIGNED NOT NULL,
  customer_code      VARCHAR(32)  NOT NULL,
  customer_name      VARCHAR(200) NOT NULL,
  default_currency   CHAR(3)      NOT NULL DEFAULT 'HKD',
  payment_terms_days INT UNSIGNED NOT NULL DEFAULT 30,
  is_related_party   TINYINT(1)   NOT NULL DEFAULT 0,
  email              VARCHAR(200)     NULL,
  status             ENUM('active','inactive') NOT NULL DEFAULT 'active',
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (customer_id),
  UNIQUE KEY uk_customers_code (entity_id, customer_code),
  KEY idx_customers_name (entity_id, customer_name),
  CONSTRAINT fk_customers_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='客户主数据';

CREATE TABLE IF NOT EXISTS vendors (
  vendor_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id          BIGINT UNSIGNED NOT NULL,
  vendor_code        VARCHAR(32)  NOT NULL,
  vendor_name        VARCHAR(200) NOT NULL,
  default_currency   CHAR(3)      NOT NULL DEFAULT 'HKD',
  payment_terms_days INT UNSIGNED NOT NULL DEFAULT 30,
  is_related_party   TINYINT(1)   NOT NULL DEFAULT 0,
  email              VARCHAR(200)     NULL,
  status             ENUM('active','inactive') NOT NULL DEFAULT 'active',
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (vendor_id),
  UNIQUE KEY uk_vendors_code (entity_id, vendor_code),
  KEY idx_vendors_name (entity_id, vendor_name),
  CONSTRAINT fk_vendors_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='供应商主数据';

-- ---------------------------------------------------------------------------
-- 6. invoices — 销售发票（§3.1.2）
-- 唯一键 (invoice_no, supplier_name) 为防重复入账最终兜底（§2.3）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
  invoice_id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id                  BIGINT UNSIGNED NOT NULL,
  invoice_no                 VARCHAR(64)  NOT NULL,
  supplier_name              VARCHAR(200) NOT NULL COMMENT '规格字段名（语义为开票对象）',
  customer_id                BIGINT UNSIGNED NULL,
  invoice_date               DATE         NOT NULL,
  due_date                   DATE             NULL,
  -- 汇率默认绑定此日（§2.7）
  revenue_recognition_date   DATE             NULL,
  currency                   CHAR(3)      NOT NULL DEFAULT 'HKD',
  amount_original            DECIMAL(20,2) NOT NULL COMMENT '原币不含税',
  tax_original               DECIMAL(20,2) NOT NULL DEFAULT 0,
  gross_original             DECIMAL(20,2) NOT NULL COMMENT '原币含税 = amount + tax',
  tax_rate_implied           DECIMAL(9,6)  NOT NULL DEFAULT 0,
  tax_rate_id                BIGINT UNSIGNED NULL,
  amount_functional          DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '折算 HKD 不含税',
  tax_functional             DECIMAL(20,2) NOT NULL DEFAULT 0,
  fx_rate                    DECIMAL(20,10) NOT NULL DEFAULT 1,
  fx_rate_date               DATE             NULL,
  fx_rate_policy             VARCHAR(32)      NULL,
  -- HKFRS 15 判断结果（§3.3.1）
  performance_obligation_status ENUM('unfulfilled','partial','fulfilled','undetermined') NOT NULL DEFAULT 'undetermined',
  recognition_pattern        ENUM('point_in_time','over_time') NULL,
  revenue_account_code       VARCHAR(20)      NULL COMMENT '规则决定的贷方科目',
  contract_asset_amount      DECIMAL(20,2) NOT NULL DEFAULT 0,
  contract_liability_amount  DECIMAL(20,2) NOT NULL DEFAULT 0,
  settled_original           DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '已核销原币金额',
  confidence                 ENUM('high','medium','low') NULL,
  source_file_path           VARCHAR(500)     NULL,
  matched_rule_id            VARCHAR(32)      NULL,
  status                     ENUM('draft','posted','void') NOT NULL DEFAULT 'draft',
  version                    INT UNSIGNED NOT NULL DEFAULT 1,
  created_by                 VARCHAR(64)  NOT NULL,
  created_at                 DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at                 DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  retention_until            DATE         NOT NULL COMMENT '>= 完结日 + 7 年（§2.4）',
  PRIMARY KEY (invoice_id),
  UNIQUE KEY uk_invoices_no_supplier (invoice_no, supplier_name),
  KEY idx_inv_entity_status (entity_id, status),
  KEY idx_inv_currency (entity_id, currency, status),
  KEY idx_inv_recog (entity_id, revenue_recognition_date),
  CONSTRAINT fk_inv_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id),
  CONSTRAINT fk_inv_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
) ENGINE=InnoDB COMMENT='销售发票';

-- ---------------------------------------------------------------------------
-- 7. invoice_files — 附件索引（§2.1：库内只存路径与哈希）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_files (
  file_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  invoice_id      BIGINT UNSIGNED NOT NULL,
  file_name       VARCHAR(255) NOT NULL,
  file_type       VARCHAR(64)  NOT NULL,
  file_size       BIGINT UNSIGNED NOT NULL DEFAULT 0,
  sha256_hash     CHAR(64)     NOT NULL,
  storage_path    VARCHAR(500) NOT NULL COMMENT '实体文件路径，位于 storage/',
  uploaded_by     VARCHAR(64)  NOT NULL,
  uploaded_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  retention_until DATE         NOT NULL,
  PRIMARY KEY (file_id),
  UNIQUE KEY uk_invfile_hash (invoice_id, sha256_hash),
  KEY idx_invfile_invoice (invoice_id),
  CONSTRAINT fk_invfile_invoice FOREIGN KEY (invoice_id) REFERENCES invoices (invoice_id) ON DELETE RESTRICT
) ENGINE=InnoDB COMMENT='发票原始文件索引';

-- ---------------------------------------------------------------------------
-- 8. bills — 供应商账单（§3.4.2）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bills (
  bill_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id         BIGINT UNSIGNED NOT NULL,
  bill_no           VARCHAR(64)  NOT NULL,
  vendor_id         BIGINT UNSIGNED NOT NULL,
  vendor_name       VARCHAR(200) NOT NULL,
  date              DATE         NOT NULL,
  due_date          DATE             NULL,
  currency          CHAR(3)      NOT NULL DEFAULT 'HKD',
  amount            DECIMAL(20,2) NOT NULL COMMENT '原币不含税',
  tax_amount        DECIMAL(20,2) NOT NULL DEFAULT 0,
  gross_original    DECIMAL(20,2) NOT NULL,
  tax_rate_implied  DECIMAL(9,6)  NOT NULL DEFAULT 0,
  tax_rate_id       BIGINT UNSIGNED NULL,
  amount_functional DECIMAL(20,2) NOT NULL DEFAULT 0,
  fx_rate           DECIMAL(20,10) NOT NULL DEFAULT 1,
  fx_rate_date      DATE             NULL,
  settled_original  DECIMAL(20,2) NOT NULL DEFAULT 0,
  expense_account_code VARCHAR(20) NULL,
  confidence        ENUM('high','medium','low') NULL,
  source_file_path  VARCHAR(500)     NULL,
  status            ENUM('draft','posted','void') NOT NULL DEFAULT 'draft',
  version           INT UNSIGNED NOT NULL DEFAULT 1,
  created_by        VARCHAR(64)  NOT NULL,
  created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  retention_until   DATE         NOT NULL,
  PRIMARY KEY (bill_id),
  UNIQUE KEY uk_bills_no_vendor (bill_no, vendor_id),
  KEY idx_bills_entity_status (entity_id, status),
  CONSTRAINT fk_bills_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id),
  CONSTRAINT fk_bills_vendor FOREIGN KEY (vendor_id) REFERENCES vendors (vendor_id)
) ENGINE=InnoDB COMMENT='供应商账单';

-- ---------------------------------------------------------------------------
-- 9. expenses — 费用（§3.4.2）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expenses (
  expense_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id         BIGINT UNSIGNED NOT NULL,
  expense_no        VARCHAR(64)  NOT NULL,
  vendor_id         BIGINT UNSIGNED NULL,
  bill_id           BIGINT UNSIGNED NULL COMMENT '可选关联账单',
  date              DATE         NOT NULL,
  category          VARCHAR(64)  NOT NULL,
  project_name      VARCHAR(200)     NULL,
  notes             VARCHAR(600)     NULL,
  reviewed_by       VARCHAR(100)     NULL,
  expense_account_code VARCHAR(20) NULL,
  amount            DECIMAL(20,2) NOT NULL,
  currency          CHAR(3)      NOT NULL DEFAULT 'HKD',
  tax_amount        DECIMAL(20,2) NOT NULL DEFAULT 0,
  amount_functional DECIMAL(20,2) NOT NULL DEFAULT 0,
  fx_rate           DECIMAL(20,10) NOT NULL DEFAULT 1,
  fx_rate_date      DATE             NULL,
  receipt_path      VARCHAR(500)     NULL,
  confidence        ENUM('high','medium','low') NULL,
  status            ENUM('draft','posted','void') NOT NULL DEFAULT 'draft',
  created_by        VARCHAR(64)  NOT NULL,
  created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  retention_until   DATE         NOT NULL,
  PRIMARY KEY (expense_id),
  UNIQUE KEY uk_expenses_no (entity_id, expense_no),
  KEY idx_exp_bill (bill_id),
  CONSTRAINT fk_exp_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='费用';

-- ---------------------------------------------------------------------------
-- 10. bank_accounts — 多币种银行账户（§3.5.1）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_accounts (
  account_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id         BIGINT UNSIGNED NOT NULL,
  name              VARCHAR(200) NOT NULL,
  currency          CHAR(3)      NOT NULL COMMENT '账户功能币种；产生流水后不得修改（§2.12）',
  account_code      VARCHAR(20)  NOT NULL COMMENT '对应 GL 科目',
  bank_name         VARCHAR(200)     NULL,
  account_number_masked VARCHAR(64)  NULL,
  is_credit_card    TINYINT(1)   NOT NULL DEFAULT 0,
  opening_balance   DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '期初原币',
  opening_balance_functional DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '期初 HKD',
  current_balance   DECIMAL(20,2) NOT NULL DEFAULT 0,
  current_balance_functional DECIMAL(20,2) NOT NULL DEFAULT 0,
  last_reval_rate   DECIMAL(20,10) NULL,
  last_reval_date   DATE             NULL,
  status            ENUM('active','closed') NOT NULL DEFAULT 'active',
  created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (account_id),
  UNIQUE KEY uk_bank_code (entity_id, account_code),
  KEY idx_bank_ccy (entity_id, currency, status),
  CONSTRAINT fk_bank_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='银行/信用卡账户，每账户一个功能币种';

-- ---------------------------------------------------------------------------
-- 11. statement_imports — 月结单导入批次（§3.6.1）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS statement_imports (
  batch_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id         BIGINT UNSIGNED NOT NULL,
  bank_account_id   BIGINT UNSIGNED NOT NULL,
  account_currency  CHAR(3)      NOT NULL COMMENT '导入时账户币种快照',
  file_name         VARCHAR(255) NOT NULL,
  file_format       ENUM('csv','tsv','xls','xlsx','ofx','qif','camt053') NOT NULL,
  sha256_hash       CHAR(64)     NOT NULL,
  period_start      DATE             NULL,
  period_end        DATE             NULL,
  opening_balance   DECIMAL(20,2) NOT NULL DEFAULT 0,
  closing_balance   DECIMAL(20,2) NOT NULL DEFAULT 0,
  total_debits      DECIMAL(20,2) NOT NULL DEFAULT 0,
  total_credits     DECIMAL(20,2) NOT NULL DEFAULT 0,
  -- 期初 + 贷方 − 借方 = 期末（§3.6.1）
  arithmetic_ok     TINYINT(1)   NOT NULL DEFAULT 0,
  arithmetic_diff   DECIMAL(20,2) NOT NULL DEFAULT 0,
  line_count        INT UNSIGNED NOT NULL DEFAULT 0,
  status            ENUM('validated','rejected','imported') NOT NULL DEFAULT 'validated',
  reject_reason     VARCHAR(500)     NULL,
  imported_by       VARCHAR(64)  NOT NULL,
  imported_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (batch_id),
  UNIQUE KEY uk_import_hash (bank_account_id, sha256_hash),
  CONSTRAINT fk_import_account FOREIGN KEY (bank_account_id) REFERENCES bank_accounts (account_id)
) ENGINE=InnoDB COMMENT='银行月结单导入批次';

-- ---------------------------------------------------------------------------
-- 12. bank_lines — 银行流水（§3.1.2 / §3.5）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_lines (
  line_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id         BIGINT UNSIGNED NOT NULL,
  bank_account_id   BIGINT UNSIGNED NOT NULL,
  bank_ref          VARCHAR(64)      NULL COMMENT 'FPS 最多 35 字符，仅辅助匹配',
  txn_date          DATE         NOT NULL,
  amount_original   DECIMAL(20,2) NOT NULL COMMENT '账户币种原币；支出为负',
  currency          CHAR(3)      NOT NULL,
  counterparty_name VARCHAR(200)     NULL,
  amount_functional DECIMAL(20,2) NOT NULL DEFAULT 0,
  fx_rate           DECIMAL(20,10) NULL,
  fx_rate_date      DATE             NULL,
  match_status      ENUM('unmatched','pending','matched','excluded') NOT NULL DEFAULT 'unmatched',
  matched_type      ENUM('invoice','bill','expense','transfer','bank_charge','interest','manual') NULL,
  matched_id        BIGINT UNSIGNED  NULL,
  match_confidence  ENUM('high','medium','low') NULL,
  match_rule        VARCHAR(8)       NULL COMMENT 'P1/P2/P3/P4',
  -- 跨币种匹配留痕（§3.5.2 路径 B）
  matched_currency  CHAR(3)          NULL,
  matched_amount_at_rate DECIMAL(20,2) NULL,
  match_rate        DECIMAL(20,10)   NULL,
  match_rate_date   DATE             NULL,
  settlement_diff_functional DECIMAL(20,2) NOT NULL DEFAULT 0,
  source_file_path  VARCHAR(500)     NULL,
  statement_import_batch_id BIGINT UNSIGNED NULL,
  is_duplicate      TINYINT(1)   NOT NULL DEFAULT 0,
  created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (line_id),
  UNIQUE KEY uk_bankline_dedup (bank_account_id, bank_ref, amount_original, txn_date),
  KEY idx_bl_account_date (bank_account_id, txn_date),
  KEY idx_bl_match (entity_id, match_status),
  CONSTRAINT fk_bl_account FOREIGN KEY (bank_account_id) REFERENCES bank_accounts (account_id),
  CONSTRAINT fk_bl_batch FOREIGN KEY (statement_import_batch_id) REFERENCES statement_imports (batch_id)
) ENGINE=InnoDB COMMENT='银行流水（原币 + 功能货币）';

-- ---------------------------------------------------------------------------
-- 13. journal_entries — 日记账头（§3.2.1）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journal_entries (
  entry_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id         BIGINT UNSIGNED NOT NULL,
  entry_no          VARCHAR(32)  NOT NULL,
  entry_date        DATE         NOT NULL,
  -- 生成列：恒等于 entry_date 的 YYYY-MM，杜绝写错期间
  period            CHAR(7)      GENERATED ALWAYS AS (LEFT(entry_date, 7)) STORED,
  source_type       ENUM('invoice','bank','fx_reval','tax_adj','manual') NOT NULL,
  source_id         BIGINT UNSIGNED  NULL,
  description       VARCHAR(500)     NULL,
  status            ENUM('draft','pending_review','posted','reversed') NOT NULL DEFAULT 'draft',
  -- §2.4 反向分录链路：更正唯一合法方式
  reversal_of_entry_id BIGINT UNSIGNED NULL,
  reversed_by_entry_id BIGINT UNSIGNED NULL,
  total_debit       DECIMAL(20,2) NOT NULL DEFAULT 0,
  total_credit      DECIMAL(20,2) NOT NULL DEFAULT 0,
  created_by        VARCHAR(64)  NOT NULL,
  posted_by         VARCHAR(64)      NULL,
  posted_at         DATETIME(3)      NULL,
  version           INT UNSIGNED NOT NULL DEFAULT 1,
  retention_until   DATE         NOT NULL,
  created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (entry_id),
  UNIQUE KEY uk_je_no (entity_id, entry_no),
  KEY idx_je_date (entity_id, entry_date),
  KEY idx_je_period (entity_id, period, status),
  KEY idx_je_source (source_type, source_id),
  KEY idx_je_reversal (reversal_of_entry_id),
  CONSTRAINT fk_je_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='日记账头';

-- ---------------------------------------------------------------------------
-- 14. journal_lines — 日记账行（§3.1.2）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journal_lines (
  line_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entry_id        BIGINT UNSIGNED NOT NULL,
  line_no         SMALLINT UNSIGNED NOT NULL,
  account_code    VARCHAR(20)  NOT NULL,
  description     VARCHAR(500)     NULL,
  debit           DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '功能货币(HKD)',
  credit          DECIMAL(20,2) NOT NULL DEFAULT 0,
  ccy             CHAR(3)      NOT NULL DEFAULT 'HKD',
  amount_original DECIMAL(20,2) NOT NULL DEFAULT 0,
  rate            DECIMAL(20,10) NOT NULL DEFAULT 1,
  rate_date       DATE             NULL,
  counterparty    VARCHAR(200)     NULL,
  PRIMARY KEY (line_id),
  UNIQUE KEY uk_jl_entry_line (entry_id, line_no),
  KEY idx_jl_account (account_code, entry_id),
  CONSTRAINT fk_jl_entry FOREIGN KEY (entry_id) REFERENCES journal_entries (entry_id) ON DELETE RESTRICT
) ENGINE=InnoDB COMMENT='日记账行；外键禁止级联删除';

-- ---------------------------------------------------------------------------
-- 15. period_locks — 期间锁定（§3.2.2）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS period_locks (
  entity_id  BIGINT UNSIGNED NOT NULL,
  period     CHAR(7)      NOT NULL COMMENT 'YYYY-MM',
  status     ENUM('open','locked','closed') NOT NULL DEFAULT 'open',
  locked_by  VARCHAR(64)      NULL,
  locked_at  DATETIME(3)      NULL,
  note       VARCHAR(500)     NULL,
  PRIMARY KEY (entity_id, period),
  CONSTRAINT fk_period_locks_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='期间锁定；locked/closed 期间禁止 UPDATE/DELETE';

-- ---------------------------------------------------------------------------
-- 16. pending_review — 待复核队列（§3.1.2）
-- AI 产出的唯一合法写入目标（§2.9）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pending_review (
  review_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id   BIGINT UNSIGNED NOT NULL,
  kind        ENUM('invoice','bank_match','fx_missing','tax_entity_status',
                   'tax_rate_invalid','bank_anomaly','fx_rate_anomaly') NOT NULL,
  ref_table   VARCHAR(64)      NULL,
  ref_id      BIGINT UNSIGNED  NULL,
  reason      VARCHAR(500) NOT NULL,
  payload     JSON         NOT NULL COMMENT '上下文快照与校验摘要',
  severity    ENUM('blocker','warning','info') NOT NULL DEFAULT 'warning',
  status      ENUM('open','resolved','dismissed') NOT NULL DEFAULT 'open',
  resolved_by VARCHAR(64)      NULL,
  resolved_at DATETIME(3)      NULL,
  resolution  VARCHAR(500)     NULL,
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (review_id),
  KEY idx_pr_status (entity_id, status, kind),
  KEY idx_pr_ref (ref_table, ref_id),
  CONSTRAINT fk_pr_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='待人工复核队列';

-- ---------------------------------------------------------------------------
-- 17. tax_rates — 税率表（§3.7.1）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_rates (
  tax_rate_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id      BIGINT UNSIGNED NOT NULL,
  name           VARCHAR(100) NOT NULL,
  rate           DECIMAL(9,6) NOT NULL COMMENT '0.05 = 5%',
  tax_type       ENUM('sales','purchase','withholding','profits_tax') NOT NULL,
  jurisdiction   VARCHAR(16)  NOT NULL DEFAULT 'HK',
  effective_from DATE         NOT NULL,
  effective_to   DATE             NULL,
  is_whitelisted TINYINT(1)   NOT NULL DEFAULT 1,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (tax_rate_id),
  UNIQUE KEY uk_tax_rate (entity_id, name, effective_from),
  KEY idx_tax_rate_lookup (entity_id, tax_type, is_whitelisted),
  CONSTRAINT fk_taxrate_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='税率表';

-- ---------------------------------------------------------------------------
-- 18. tax_adjustments — 税务调整（§3.7.2）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_adjustments (
  adjustment_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id              BIGINT UNSIGNED NOT NULL,
  period                 CHAR(7)      NOT NULL COMMENT 'YYYY-MM',
  accounting_profit      DECIMAL(20,2) NOT NULL,
  tax_adjustment_amount  DECIMAL(20,2) NOT NULL DEFAULT 0,
  assessable_profit      DECIMAL(20,2) NOT NULL DEFAULT 0,
  two_tier_applied       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '仅 nominated 时可置 1',
  two_tier_status_snapshot ENUM('nominated','not_nominated','undetermined') NOT NULL,
  tax_payable            DECIMAL(20,2) NOT NULL DEFAULT 0,
  basis_note             VARCHAR(500)     NULL,
  detail                 JSON             NULL,
  status                 ENUM('draft','pending_review','final') NOT NULL DEFAULT 'draft',
  created_by             VARCHAR(64)  NOT NULL,
  created_at             DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (adjustment_id),
  UNIQUE KEY uk_tax_adj_period (entity_id, period),
  CONSTRAINT fk_taxadj_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='税务调整；与会计利润分离';

-- ---------------------------------------------------------------------------
-- 19. payments_received — 收款（§3.4.3）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments_received (
  payment_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id          BIGINT UNSIGNED NOT NULL,
  payment_no         VARCHAR(64)  NOT NULL,
  customer_id        BIGINT UNSIGNED NULL,
  date               DATE         NOT NULL,
  amount             DECIMAL(20,2) NOT NULL,
  currency           CHAR(3)      NOT NULL,
  amount_functional  DECIMAL(20,2) NOT NULL DEFAULT 0,
  -- 结算汇率（§3.4.3 双汇率之第二汇率）
  fx_rate_at_payment DECIMAL(20,10) NOT NULL DEFAULT 1,
  fx_rate_date       DATE             NULL,
  bank_account_id    BIGINT UNSIGNED  NULL,
  bank_line_id       BIGINT UNSIGNED  NULL,
  bank_account_currency CHAR(3)       NULL,
  settlement_fx_diff DECIMAL(20,2) NOT NULL DEFAULT 0,
  status             ENUM('draft','posted','reversed') NOT NULL DEFAULT 'draft',
  created_by         VARCHAR(64)  NOT NULL,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (payment_id),
  UNIQUE KEY uk_pr_no (entity_id, payment_no),
  KEY idx_pr_date (entity_id, date),
  CONSTRAINT fk_pr_bank FOREIGN KEY (bank_account_id) REFERENCES bank_accounts (account_id)
) ENGINE=InnoDB COMMENT='收款单';

-- ---------------------------------------------------------------------------
-- 20. payments_made — 付款（§3.4.3）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments_made (
  payment_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id          BIGINT UNSIGNED NOT NULL,
  payment_no         VARCHAR(64)  NOT NULL,
  vendor_id          BIGINT UNSIGNED NULL,
  date               DATE         NOT NULL,
  amount             DECIMAL(20,2) NOT NULL,
  currency           CHAR(3)      NOT NULL,
  amount_functional  DECIMAL(20,2) NOT NULL DEFAULT 0,
  fx_rate_at_payment DECIMAL(20,10) NOT NULL DEFAULT 1,
  fx_rate_date       DATE             NULL,
  bank_account_id    BIGINT UNSIGNED  NULL,
  bank_line_id       BIGINT UNSIGNED  NULL,
  bank_account_currency CHAR(3)       NULL,
  settlement_fx_diff DECIMAL(20,2) NOT NULL DEFAULT 0,
  status             ENUM('draft','posted','reversed') NOT NULL DEFAULT 'draft',
  created_by         VARCHAR(64)  NOT NULL,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (payment_id),
  UNIQUE KEY uk_pm_no (entity_id, payment_no),
  KEY idx_pm_date (entity_id, date),
  CONSTRAINT fk_pm_bank FOREIGN KEY (bank_account_id) REFERENCES bank_accounts (account_id)
) ENGINE=InnoDB COMMENT='付款单';

-- ---------------------------------------------------------------------------
-- 21. settlements — 核销明细（偏差声明：§3.1.1 未列，§3.4.3 必需）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settlements (
  settlement_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id          BIGINT UNSIGNED NOT NULL,
  direction          ENUM('received','made') NOT NULL,
  payment_id         BIGINT UNSIGNED NOT NULL,
  invoice_id         BIGINT UNSIGNED NULL,
  bill_id            BIGINT UNSIGNED NULL,
  settled_original   DECIMAL(20,2) NOT NULL COMMENT '原币核销金额',
  doc_currency       CHAR(3)      NOT NULL,
  bank_currency      CHAR(3)      NOT NULL,
  is_cross_currency  TINYINT(1)   NOT NULL DEFAULT 0,
  doc_rate           DECIMAL(20,10) NOT NULL COMMENT '单据记账汇率',
  settle_rate        DECIMAL(20,10) NOT NULL COMMENT '结算汇率',
  fx_diff_functional DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '汇兑差额(HKD)',
  fx_diff_entry_id   BIGINT UNSIGNED NULL,
  created_by         VARCHAR(64)  NOT NULL,
  created_at         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (settlement_id),
  KEY idx_st_payment (direction, payment_id),
  KEY idx_st_invoice (invoice_id),
  KEY idx_st_bill (bill_id),
  CONSTRAINT fk_st_invoice FOREIGN KEY (invoice_id) REFERENCES invoices (invoice_id),
  CONSTRAINT fk_st_bill FOREIGN KEY (bill_id) REFERENCES bills (bill_id)
) ENGINE=InnoDB COMMENT='收付款核销明细（含汇兑差额）';

-- ---------------------------------------------------------------------------
-- 22. audit_log — 审计日志（§3.9.2）
-- 哈希链：prev_hash 指向上一条 record_hash；创世为 64 个 0
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
  log_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id   BIGINT UNSIGNED NOT NULL,
  seq_no      BIGINT UNSIGNED NOT NULL COMMENT '链序号，从 1 连续',
  actor       VARCHAR(64)  NOT NULL,
  actor_role  VARCHAR(32)  NOT NULL COMMENT 'admin/accountant/auditor',
  action      VARCHAR(64)  NOT NULL,
  object_type VARCHAR(64)      NULL,
  object_id   VARCHAR(64)      NULL,
  detail      JSON             NULL,
  client_ip   VARCHAR(64)      NULL,
  prev_hash   CHAR(64)     NOT NULL,
  record_hash CHAR(64)     NOT NULL COMMENT 'SHA-256(prev_hash | 规范化载荷)',
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (log_id),
  UNIQUE KEY uk_audit_seq (entity_id, seq_no),
  KEY idx_audit_actor (entity_id, actor, created_at),
  KEY idx_audit_object (object_type, object_id),
  CONSTRAINT fk_audit_entity FOREIGN KEY (entity_id) REFERENCES entities (entity_id)
) ENGINE=InnoDB COMMENT='审计日志；只追加，哈希链防篡改';

SELECT '数据层建立完成' AS result,
       (SELECT COUNT(*) FROM information_schema.tables
         WHERE table_schema = 'ledu_accounting') AS table_count;
