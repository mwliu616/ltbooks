-- ============================================================================
-- 香港会计科目表补全（HKFRS 常用科目）
--
-- 原则：只新增，不改动既有科目编码 —— 已有分录与规则映射都指向原编码。
-- 分类遵循 HKAS 1 的流动/非流动划分；累计折旧以负数计入资产。
-- ============================================================================

INSERT INTO accounts
  (entity_id, account_code, account_name, category, fs_line_item, normal_balance,
   parent_account_code, is_active)
VALUES
-- ---------- 非流动资产 ----------
(1,'1210','物業、廠房及設備','asset','NON_CURRENT_ASSETS','debit','1200',1),
(1,'1211','樓宇','asset','NON_CURRENT_ASSETS','debit','1210',1),
(1,'1212','機器及設備','asset','NON_CURRENT_ASSETS','debit','1210',1),
(1,'1213','電腦設備','asset','NON_CURRENT_ASSETS','debit','1210',1),
(1,'1214','傢俬及裝置','asset','NON_CURRENT_ASSETS','debit','1210',1),
(1,'1215','汽車','asset','NON_CURRENT_ASSETS','debit','1210',1),
(1,'1219','累計折舊 — 物業、廠房及設備','asset','NON_CURRENT_ASSETS','debit','1210',1),
(1,'1220','使用權資產','asset','NON_CURRENT_ASSETS','debit','1200',1),
(1,'1229','累計折舊 — 使用權資產','asset','NON_CURRENT_ASSETS','debit','1200',1),
(1,'1230','無形資產','asset','NON_CURRENT_ASSETS','debit','1200',1),
(1,'1240','投資物業','asset','NON_CURRENT_ASSETS','debit','1200',1),
(1,'1250','長期投資','asset','NON_CURRENT_ASSETS','debit','1200',1),
(1,'1260','遞延稅項資產','asset','NON_CURRENT_ASSETS','debit','1200',1),

-- ---------- 流动资产补充 ----------
(1,'1170','存貨','asset','CURRENT_ASSETS','debit','1100',1),
(1,'1171','應收票據','asset','TRADE_RECEIVABLES','debit','1100',1),
(1,'1172','其他應收賬款','asset','OTHER_RECEIVABLES','debit','1100',1),
(1,'1173','按金及預付款','asset','PREPAYMENTS','debit','1100',1),
(1,'1174','可收回稅項','asset','TAX_ASSETS','debit','1100',1),

-- ---------- 非流动负债 ----------
(1,'2200','非流動負債','liability','NON_CURRENT_LIABILITIES','credit','2000',1),
(1,'2210','長期借款','liability','NON_CURRENT_LIABILITIES','credit','2200',1),
(1,'2220','租賃負債 — 非流動','liability','NON_CURRENT_LIABILITIES','credit','2200',1),
(1,'2230','遞延稅項負債','liability','NON_CURRENT_LIABILITIES','credit','2200',1),
(1,'2240','撥備','liability','NON_CURRENT_LIABILITIES','credit','2200',1),

-- ---------- 流动负债补充 ----------
(1,'2170','應付票據','liability','TRADE_PAYABLES','credit','2100',1),
(1,'2171','應付薪金及工資','liability','ACCRUALS','credit','2100',1),
(1,'2172','暫繳利得稅','liability','TAX_LIABILITIES','credit','2100',1),
(1,'2173','其他應付款','liability','OTHER_PAYABLES','credit','2100',1),
(1,'2174','租賃負債 — 流動','liability','LEASE_LIABILITIES_CURRENT','credit','2100',1),
(1,'2175','短期借款','liability','SHORT_TERM_BORROWINGS','credit','2100',1),

-- ---------- 权益补充 ----------
(1,'3400','股份溢價','equity','SHARE_PREMIUM','credit','3000',1),
(1,'3500','重估儲備','equity','REVALUATION_RESERVE','credit','3000',1),
(1,'3600','外幣換算儲備','equity','FX_TRANSLATION_RESERVE','credit','3000',1),
(1,'3700','已宣派股息','equity','DIVIDENDS_DECLARED','debit','3000',1),

-- ---------- 收入补充 ----------
(1,'4500','利息收入','revenue','OTHER_INCOME','credit','4000',1),
(1,'4510','股息收入','revenue','OTHER_INCOME','credit','4000',1),
(1,'4520','政府補助','revenue','OTHER_INCOME','credit','4000',1),
(1,'4530','雜項收入','revenue','OTHER_INCOME','credit','4000',1),

-- ---------- 销售成本补充 ----------
(1,'5300','存貨調整','cogs','COST_OF_SALES','debit','5000',1),
(1,'5400','分包成本','cogs','COST_OF_SALES','debit','5000',1),

-- ---------- 经营费用补充 ----------
(1,'6120','薪金及工資','expense','STAFF_COSTS','debit','6100',1),
(1,'6130','員工福利','expense','STAFF_COSTS','debit','6100',1),
(1,'6140','遣散費及長期服務金','expense','STAFF_COSTS','debit','6100',1),
(1,'6210','差餉及地租','expense','OCCUPANCY','debit','6200',1),
(1,'6220','管理費','expense','OCCUPANCY','debit','6200',1),
(1,'6230','水電費','expense','OCCUPANCY','debit','6200',1),
(1,'6310','核數費','expense','PROFESSIONAL_FEES','debit','6300',1),
(1,'6320','法律及諮詢費','expense','PROFESSIONAL_FEES','debit','6300',1),
(1,'6330','公司秘書費','expense','PROFESSIONAL_FEES','debit','6300',1),
(1,'6510','應酬費','expense','ENTERTAINMENT','debit','6500',1),
(1,'6520','交通費','expense','TRAVEL','debit','6500',1),
(1,'6610','通訊費','expense','ADMIN_EXPENSES','debit','6600',1),
(1,'6620','電腦及軟件','expense','ADMIN_EXPENSES','debit','6600',1),
(1,'6630','維修保養','expense','ADMIN_EXPENSES','debit','6600',1),
(1,'6640','保險','expense','ADMIN_EXPENSES','debit','6600',1),
(1,'6650','商業登記費','expense','ADMIN_EXPENSES','debit','6600',1),
(1,'6810','攤銷','expense','AMORTISATION','debit','6000',1),
(1,'6820','折舊 — 使用權資產','expense','DEPRECIATION','debit','6000',1),

-- ---------- 财务费用（HKAS 1 独立列示） ----------
(1,'7000','財務費用','expense','FINANCE_COSTS','debit',NULL,1),
(1,'7100','利息支出','expense','FINANCE_COSTS','debit','7000',1),
(1,'7110','銀行透支利息','expense','FINANCE_COSTS','debit','7000',1)
ON DUPLICATE KEY UPDATE
  account_name=VALUES(account_name), category=VALUES(category),
  fs_line_item=VALUES(fs_line_item), normal_balance=VALUES(normal_balance),
  parent_account_code=VALUES(parent_account_code);
