-- 32: 供应商银行信息（付款用）
ALTER TABLE vendors
  ADD COLUMN bank_name         VARCHAR(200) NULL AFTER tax_id,
  ADD COLUMN bank_account_name VARCHAR(200) NULL AFTER bank_name,
  ADD COLUMN bank_account_no   VARCHAR(64)  NULL AFTER bank_account_name,
  ADD COLUMN bank_swift        VARCHAR(32)  NULL AFTER bank_account_no,
  ADD COLUMN bank_address      VARCHAR(300) NULL AFTER bank_swift;
