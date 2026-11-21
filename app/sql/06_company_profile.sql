-- ============================================================================
-- 公司档案与开户行信息
--
-- 用途：发票/账单抬头、PDF 收款信息、报表落款。
-- 注意：行名与地址必须与银行开户文件一致，否则收款方可能拒付。
-- ============================================================================

ALTER TABLE entities
  ADD COLUMN legal_name        VARCHAR(200) NULL AFTER entity_name,
  ADD COLUMN br_number         VARCHAR(32)  NULL COMMENT '商业登记证号码' AFTER legal_name,
  ADD COLUMN address_line1     VARCHAR(200) NULL AFTER br_number,
  ADD COLUMN address_line2     VARCHAR(200) NULL AFTER address_line1,
  ADD COLUMN district          VARCHAR(100) NULL AFTER address_line2,
  ADD COLUMN region            VARCHAR(100) NULL AFTER district,
  ADD COLUMN phone             VARCHAR(64)  NULL AFTER region,
  ADD COLUMN email             VARCHAR(200) NULL AFTER phone,
  ADD COLUMN website           VARCHAR(200) NULL AFTER email;

ALTER TABLE bank_accounts
  ADD COLUMN account_holder    VARCHAR(200) NULL AFTER name,
  ADD COLUMN account_number    VARCHAR(64)  NULL COMMENT '完整账号，仅用于单据打印与对账' AFTER account_number_masked,
  ADD COLUMN bank_code         VARCHAR(16)  NULL COMMENT '香港银行代码，汇丰为 004' AFTER bank_name,
  ADD COLUMN swift_code        VARCHAR(32)  NULL AFTER bank_code,
  ADD COLUMN bank_address      VARCHAR(300) NULL AFTER swift_code,
  ADD COLUMN branch            VARCHAR(200) NULL AFTER bank_address;

-- 只允许一个实体持有「主收款账户」标记，避免发票上印错账户
ALTER TABLE bank_accounts
  ADD COLUMN is_primary_receiving TINYINT(1) NOT NULL DEFAULT 0 AFTER is_credit_card;
