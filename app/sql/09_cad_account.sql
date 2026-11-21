-- ============================================================================
-- 加元（CAD）账户
--
-- 币种不再写死在代码里：以银行账户为准，加账户即自动出现在所有表单。
-- 汇率属演示种子数据，来源标记 SEED，可在「汇率维护」页覆盖。
-- ============================================================================

INSERT INTO accounts
  (entity_id, account_code, account_name, category, fs_line_item, normal_balance,
   parent_account_code, is_active)
VALUES (1,'1124','銀行賬戶 — CAD','asset','CASH_EQUIVALENTS','debit','1120',1)
ON DUPLICATE KEY UPDATE account_name=VALUES(account_name);

INSERT INTO bank_accounts
  (entity_id, name, account_holder, currency, account_code, bank_name, account_number_masked,
   is_credit_card, is_primary_receiving, opening_balance, opening_balance_functional,
   current_balance, current_balance_functional, status)
VALUES (1,'加元账户 — CAD','LEDU TECH CO., LIMITED','CAD','1124','','',0,0,0,0,0,0,'active');

-- 演示汇率：与既有的 USD/CNY 种子同一批日期，来源标记 SEED
INSERT INTO fx_rates (rate_date, from_ccy, to_ccy, rate, source, is_fallback) VALUES
('2026-11-03','CAD','HKD',5.6200,'SEED',0),
('2026-11-04','CAD','HKD',5.6350,'SEED',0),
('2026-11-05','CAD','HKD',5.6480,'SEED',0),
('2026-11-06','CAD','HKD',5.6600,'SEED',0),
('2026-11-07','CAD','HKD',5.6720,'SEED',0),
('2026-11-27','CAD','HKD',5.7010,'SEED',0),
('2026-11-28','CAD','HKD',5.7080,'SEED',0),
('2026-11-29','CAD','HKD',5.7130,'SEED',0),
('2026-11-30','CAD','HKD',5.7200,'SEED',0)
ON DUPLICATE KEY UPDATE rate=VALUES(rate), source=VALUES(source);
