-- ============================================================================
-- 草稿 / 复核：单据须经复核人批准后才能过账进报表
--
--   draft → 提交复核 → approved → 过账（进入报表）
--                    ↘ rejected → 退回修改
-- ============================================================================
ALTER TABLE invoices
  ADD COLUMN review_status ENUM('draft','pending','approved','rejected') NOT NULL DEFAULT 'draft'
    COMMENT '复核状态：草稿/待复核/已批准/已退回' AFTER status,
  ADD COLUMN approved_by VARCHAR(100) NULL AFTER review_status,
  ADD COLUMN approved_at DATETIME(3) NULL AFTER approved_by,
  ADD COLUMN approval_note VARCHAR(300) NULL AFTER approved_at;

ALTER TABLE bills
  ADD COLUMN review_status ENUM('draft','pending','approved','rejected') NOT NULL DEFAULT 'draft'
    COMMENT '复核状态：草稿/待复核/已批准/已退回' AFTER status,
  ADD COLUMN approved_by VARCHAR(100) NULL AFTER review_status,
  ADD COLUMN approved_at DATETIME(3) NULL AFTER approved_by,
  ADD COLUMN approval_note VARCHAR(300) NULL AFTER approved_at;
