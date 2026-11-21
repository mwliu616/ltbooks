-- ============================================================================
-- LEDU 会计功能台 — 种子数据
-- 依据 §3.1.2 / §3.7 / §3.5.1
--
-- 注意 two_tier_status 默认 'undetermined'（最保守）：
-- 在人工确认提名状态前，系统必须拒绝自动税务计算（§2.8）。
-- ============================================================================

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- 实体
-- ---------------------------------------------------------------------------
INSERT INTO entities (entity_code, entity_name, reporting_framework, two_tier_status,
                      functional_currency, fiscal_year_end_mmdd)
VALUES ('LEDU-HK', 'LEDU (HK) Limited', 'full_hkfrs', 'undetermined', 'HKD', '12-31')
ON DUPLICATE KEY UPDATE entity_name = VALUES(entity_name);

SET @eid = (SELECT entity_id FROM entities WHERE entity_code = 'LEDU-HK');

-- ---------------------------------------------------------------------------
-- 科目表（§3.1.2）
-- 编码：1 资产 / 2 负债 / 3 权益 / 4 收入 / 5 销售成本 / 6 经营费用
-- contra_reclass_target：反向余额重分类目标（§3.8.2）
-- ---------------------------------------------------------------------------
INSERT INTO accounts (entity_id, account_code, account_name, category, fs_line_item,
                      normal_balance, parent_account_code, contra_reclass_target)
VALUES
  -- 1xxx 资产
  (@eid, '1000', '资产',                     'asset',     'ASSETS',              'debit',  NULL,   NULL),
  (@eid, '1100', '流动资产',                 'asset',     'CURRENT_ASSETS',      'debit',  '1000', NULL),
  (@eid, '1110', '现金',                     'asset',     'CASH',                'debit',  '1100', NULL),
  (@eid, '1120', '银行及信用卡',             'asset',     'CASH_EQUIVALENTS',    'debit',  '1100', NULL),
  (@eid, '1121', '银行账户 — HKD',           'asset',     'CASH_EQUIVALENTS',    'debit',  '1120', NULL),
  (@eid, '1122', '银行账户 — USD',           'asset',     'CASH_EQUIVALENTS',    'debit',  '1120', NULL),
  (@eid, '1123', '银行账户 — CNY',           'asset',     'CASH_EQUIVALENTS',    'debit',  '1120', NULL),
  (@eid, '1130', '应收账款',                 'asset',     'TRADE_RECEIVABLES',   'debit',  '1100', '2120'),
  (@eid, '1131', '应收账款 — 外币',          'asset',     'TRADE_RECEIVABLES',   'debit',  '1130', '2120'),
  (@eid, '1140', '合同资产',                 'asset',     'CONTRACT_ASSETS',     'debit',  '1100', NULL),
  (@eid, '1150', '预付费用',                 'asset',     'PREPAYMENTS',         'debit',  '1100', NULL),
  (@eid, '1160', '进项税额',                 'asset',     'TAX_ASSETS',          'debit',  '1100', NULL),
  (@eid, '1200', '非流动资产',               'asset',     'NON_CURRENT_ASSETS',  'debit',  '1000', NULL),

  -- 2xxx 负债
  (@eid, '2000', '负债',                     'liability', 'LIABILITIES',         'credit', NULL,   NULL),
  (@eid, '2100', '流动负债',                 'liability', 'CURRENT_LIABILITIES', 'credit', '2000', NULL),
  (@eid, '2110', '应付账款',                 'liability', 'TRADE_PAYABLES',      'credit', '2100', NULL),
  (@eid, '2111', '应付账款 — 外币',          'liability', 'TRADE_PAYABLES',      'credit', '2110', NULL),
  (@eid, '2120', '合同负债',                 'liability', 'CONTRACT_LIABILITIES','credit', '2100', NULL),
  (@eid, '2130', '应付费用',                 'liability', 'ACCRUALS',            'credit', '2100', NULL),
  (@eid, '2140', '销项税额',                 'liability', 'TAX_LIABILITIES',     'credit', '2100', NULL),
  (@eid, '2150', '应付利得税',               'liability', 'TAX_LIABILITIES',     'credit', '2100', NULL),
  (@eid, '2160', '信用卡',                   'liability', 'CREDIT_CARD',         'credit', '2100', NULL),

  -- 3xxx 权益
  (@eid, '3000', '权益',                     'equity',    'EQUITY',              'credit', NULL,   NULL),
  (@eid, '3100', '股本',                     'equity',    'SHARE_CAPITAL',       'credit', '3000', NULL),
  (@eid, '3200', '留存收益',                 'equity',    'RETAINED_EARNINGS',   'credit', '3000', NULL),
  (@eid, '3300', '本期损益',                 'equity',    'CURRENT_YEAR_PL',     'credit', '3000', NULL),

  -- 4xxx 收入
  (@eid, '4000', '收入',                     'revenue',   'REVENUE',             'credit', NULL,   NULL),
  (@eid, '4100', '主营业务收入',             'revenue',   'REVENUE',             'credit', '4000', NULL),
  (@eid, '4200', '服务收入',                 'revenue',   'REVENUE',             'credit', '4000', NULL),
  (@eid, '4300', '其他收入',                 'revenue',   'OTHER_INCOME',        'credit', '4000', NULL),
  (@eid, '4400', '汇兑损益',                 'revenue',   'FX_GAIN_LOSS',        'credit', '4000', NULL),
  (@eid, '4410', '汇兑损益 — 已实现',        'revenue',   'FX_GAIN_LOSS',        'credit', '4400', NULL),
  (@eid, '4420', '汇兑损益 — 未实现（重估）','revenue',   'FX_GAIN_LOSS',        'credit', '4400', NULL),

  -- 5xxx 销售成本
  (@eid, '5000', '销售成本',                 'cogs',      'COST_OF_SALES',       'debit',  NULL,   NULL),
  (@eid, '5100', '采购成本',                 'cogs',      'COST_OF_SALES',       'debit',  '5000', NULL),
  (@eid, '5200', '服务成本',                 'cogs',      'COST_OF_SALES',       'debit',  '5000', NULL),

  -- 6xxx 经营费用
  (@eid, '6000', '经营费用',                 'expense',   'OPERATING_EXPENSES',  'debit',  NULL,   NULL),
  (@eid, '6100', '薪酬',                     'expense',   'STAFF_COSTS',         'debit',  '6000', NULL),
  (@eid, '6110', '强积金供款',               'expense',   'STAFF_COSTS',         'debit',  '6100', NULL),
  (@eid, '6200', '租金',                     'expense',   'OCCUPANCY',           'debit',  '6000', NULL),
  (@eid, '6300', '专业服务费',               'expense',   'PROFESSIONAL_FEES',   'debit',  '6000', NULL),
  (@eid, '6400', '银行手续费',               'expense',   'BANK_CHARGES',        'debit',  '6000', NULL),
  (@eid, '6500', '差旅',                     'expense',   'TRAVEL',              'debit',  '6000', NULL),
  (@eid, '6600', '办公费用',                 'expense',   'ADMIN_EXPENSES',      'debit',  '6000', NULL),
  (@eid, '6700', '折旧',                     'expense',   'DEPRECIATION',        'debit',  '6000', NULL),
  (@eid, '6800', '利得税费用',               'expense',   'TAX_EXPENSE',         'debit',  '6000', NULL)
ON DUPLICATE KEY UPDATE account_name = VALUES(account_name),
  fs_line_item = VALUES(fs_line_item),
  normal_balance = VALUES(normal_balance),
  contra_reclass_target = VALUES(contra_reclass_target);

-- ---------------------------------------------------------------------------
-- 税率表（§3.7.1）
-- 销项/进项税率取 §3.3.3 白名单档位；利得税税率供两级制判断
-- ---------------------------------------------------------------------------
INSERT INTO tax_rates (entity_id, name, rate, tax_type, jurisdiction, effective_from, is_whitelisted) VALUES
  (@eid, 'Sales Tax 13%',   0.1300, 'sales',       'HK', '2018-04-01', 1),
  (@eid, 'Sales Tax 9%',    0.0900, 'sales',       'HK', '2018-04-01', 1),
  (@eid, 'Sales Tax 6%',    0.0600, 'sales',       'HK', '2018-04-01', 1),
  (@eid, 'Sales Tax 3%',    0.0300, 'sales',       'HK', '2018-04-01', 1),
  (@eid, 'Sales Tax 0%',    0.0000, 'sales',       'HK', '2018-04-01', 1),
  (@eid, 'Purchase Tax 13%',0.1300, 'purchase',    'HK', '2018-04-01', 1),
  (@eid, 'Purchase Tax 9%', 0.0900, 'purchase',    'HK', '2018-04-01', 1),
  (@eid, 'Purchase Tax 6%', 0.0600, 'purchase',    'HK', '2018-04-01', 1),
  (@eid, 'Purchase Tax 3%', 0.0300, 'purchase',    'HK', '2018-04-01', 1),
  (@eid, 'Purchase Tax 0%', 0.0000, 'purchase',    'HK', '2018-04-01', 1),
  -- 香港利得税两级制（§2.8 / §3.7.2）
  (@eid, 'HK Profits Tax — first 2M (two-tier)', 0.0825, 'profits_tax', 'HK', '2018-04-01', 1),
  (@eid, 'HK Profits Tax — remainder / flat',    0.1650, 'profits_tax', 'HK', '2018-04-01', 1)
ON DUPLICATE KEY UPDATE rate = VALUES(rate), is_whitelisted = VALUES(is_whitelisted);

-- ---------------------------------------------------------------------------
-- 银行账户（§3.5.1：每账户一个功能币种）
-- ---------------------------------------------------------------------------
INSERT INTO bank_accounts (entity_id, name, currency, account_code, bank_name,
                           account_number_masked, is_credit_card,
                           opening_balance, opening_balance_functional,
                           current_balance, current_balance_functional)
VALUES
  (@eid, '运营账户 — HKD', 'HKD', '1121', 'TEST_BANK', '****1001', 0, 100000.00, 100000.00, 100000.00, 100000.00),
  (@eid, '外币账户 — USD', 'USD', '1122', 'TEST_BANK', '****2002', 0,  20000.00, 156000.00,  20000.00, 156000.00),
  (@eid, '外币账户 — CNY', 'CNY', '1123', 'TEST_BANK', '****3003', 0,  50000.00,  54000.00,  50000.00,  54000.00)
ON DUPLICATE KEY UPDATE name = VALUES(name), currency = VALUES(currency);

-- ---------------------------------------------------------------------------
-- 汇率（演示数据；生产由 ECB/Frankfurter 拉取）
-- ---------------------------------------------------------------------------
INSERT INTO fx_rates (rate_date, from_ccy, to_ccy, rate, source, is_fallback) VALUES
  ('2026-10-31','USD','HKD',7.7900,'ECB',0),
  ('2026-11-03','USD','HKD',7.8000,'ECB',0),
  ('2026-11-04','USD','HKD',7.8100,'ECB',0),
  ('2026-11-05','USD','HKD',7.8200,'ECB',0),
  ('2026-11-06','USD','HKD',7.8500,'ECB',0),
  ('2026-11-07','USD','HKD',7.8600,'ECB',0),
  ('2026-10-31','CNY','HKD',1.0800,'ECB',0),
  ('2026-11-03','CNY','HKD',1.0850,'ECB',0),
  ('2026-11-04','CNY','HKD',1.0870,'ECB',0),
  ('2026-11-05','CNY','HKD',1.0880,'ECB',0),
  ('2026-11-06','CNY','HKD',1.0900,'ECB',0),
  ('2026-11-07','CNY','HKD',1.0910,'ECB',0)
ON DUPLICATE KEY UPDATE rate = VALUES(rate), source = VALUES(source);

-- ---------------------------------------------------------------------------
-- 客户 / 供应商
-- ---------------------------------------------------------------------------
INSERT INTO customers (entity_id, customer_code, customer_name, default_currency, payment_terms_days)
VALUES (@eid,'C001','TEST_Acme Trading Limited','HKD',30),
       (@eid,'C002','TEST_Beta Services Limited','USD',30),
       (@eid,'C003','TEST_Gamma Industries Limited','CNY',45)
ON DUPLICATE KEY UPDATE customer_name = VALUES(customer_name);

INSERT INTO vendors (entity_id, vendor_code, vendor_name, default_currency, payment_terms_days)
VALUES (@eid,'V001','TEST_Supplier Alpha Limited','HKD',30),
       (@eid,'V002','TEST_Supplier Beta Limited','USD',30)
ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name);

SELECT '种子数据写入完成' AS result,
       (SELECT COUNT(*) FROM accounts WHERE entity_id=@eid) AS accounts,
       (SELECT COUNT(*) FROM tax_rates WHERE entity_id=@eid) AS tax_rates,
       (SELECT COUNT(*) FROM bank_accounts WHERE entity_id=@eid) AS bank_accounts,
       (SELECT COUNT(*) FROM fx_rates) AS fx_rates,
       (SELECT two_tier_status FROM entities WHERE entity_id=@eid) AS two_tier_status;
