-- 采购订单行支持逐行费用科目：转账单时按行带入，避免整单只能用一个科目。
ALTER TABLE order_lines
  ADD COLUMN account_code VARCHAR(20) NULL AFTER description;
