-- LtBooks Ver 1.0：费用单补充项目与备注，并支持草稿完整回显。
ALTER TABLE expenses
  ADD COLUMN IF NOT EXISTS project_name VARCHAR(200) NULL AFTER category,
  ADD COLUMN IF NOT EXISTS notes VARCHAR(600) NULL AFTER project_name,
  ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(100) NULL AFTER notes;
