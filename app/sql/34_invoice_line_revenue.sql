-- 销售发票逐行收入科目：一张发票可以有多行、不同收入科目
ALTER TABLE invoice_lines
  ADD COLUMN revenue_account_code VARCHAR(20) NULL AFTER description;
