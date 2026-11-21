-- LtBooks Ver 1.0：客户主数据支持“公司 / 个人”两种类型。
-- 历史客户一律视为公司，避免改动现有单据上的名称口径。
ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS customer_type ENUM('company','individual')
    NOT NULL DEFAULT 'company' AFTER customer_name;
