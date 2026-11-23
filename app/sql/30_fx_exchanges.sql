-- 30 跨币种外币兑换单
-- 记录银行实际成交价，点差/兑换损失进 4410，手续费单独进费用科目。

CREATE TABLE IF NOT EXISTS fx_exchanges (
  exchange_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  entity_id        BIGINT UNSIGNED NOT NULL,
  exchange_no      VARCHAR(32)     NOT NULL,
  exchange_date    DATE            NOT NULL,
  from_account_id  BIGINT UNSIGNED NOT NULL,
  to_account_id    BIGINT UNSIGNED NOT NULL,
  from_currency    CHAR(3)         NOT NULL,
  to_currency      CHAR(3)         NOT NULL,
  from_amount      DECIMAL(20,2)   NOT NULL COMMENT '卖出的源币金额',
  to_amount        DECIMAL(20,2)   NOT NULL COMMENT '买入的目标币金额',
  deal_rate        DECIMAL(20,10)  NOT NULL COMMENT '1 源币 = X 目标币（银行实际成交）',
  mid_rate_from    DECIMAL(20,10)  NULL,
  mid_rate_to      DECIMAL(20,10)  NULL,
  mid_rate_date    DATE            NULL,
  fx_diff_functional DECIMAL(20,2) NOT NULL DEFAULT 0 COMMENT '正数为汇兑损失',
  fee_amount       DECIMAL(20,2)   NOT NULL DEFAULT 0,
  fee_currency     CHAR(3)         NULL,
  fee_account_code VARCHAR(16)     NULL,
  status           ENUM('posted','void') NOT NULL DEFAULT 'posted',
  entry_id         BIGINT UNSIGNED NULL,
  note             VARCHAR(255)    NULL,
  created_by       VARCHAR(64)     NULL,
  created_at       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  voided_by        VARCHAR(64)     NULL,
  voided_at        DATETIME(3)     NULL,
  PRIMARY KEY (exchange_id),
  UNIQUE KEY uk_fx_exchange_no (entity_id, exchange_no),
  KEY idx_fx_exchange_date (entity_id, exchange_date),
  CONSTRAINT fk_fx_exchange_from FOREIGN KEY (from_account_id) REFERENCES bank_accounts (account_id),
  CONSTRAINT fk_fx_exchange_to FOREIGN KEY (to_account_id) REFERENCES bank_accounts (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE bank_lines
  ADD COLUMN exchange_id BIGINT UNSIGNED NULL AFTER matched_id,
  ADD KEY idx_bank_lines_exchange (exchange_id);

ALTER TABLE journal_entries
  MODIFY COLUMN source_type ENUM('invoice','bill','expense','payment','payment_received',
    'payment_made','settlement','fx_reval','manual','reversal','adjustment','opening',
    'contract_revenue','bank_line','fx_exchange') NOT NULL;
