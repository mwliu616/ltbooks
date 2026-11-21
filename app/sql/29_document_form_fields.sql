-- LtBooks Ver 1.0：补齐新建页面已展示但原表未保存的业务字段。
-- 仅增加可空列，不修改现有单据、状态或财务数据。
ALTER TABLE quotes
  ADD COLUMN IF NOT EXISTS subject VARCHAR(200) NULL AFTER customer_name,
  ADD COLUMN IF NOT EXISTS reference VARCHAR(100) NULL AFTER subject,
  ADD COLUMN IF NOT EXISTS salesperson VARCHAR(100) NULL AFTER reference;

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS reference VARCHAR(100) NULL AFTER contract_note;
