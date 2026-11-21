-- ============================================================================
-- 24 · 采购订单
--
-- 为什么单独一套表：
--   采购订单是「承诺」，不是「应付」。它不进总账，也不影响报表；
--   只有转成采购发票（bills）并过账，才产生应付账款。
--   混进 bills 会让「应付账款」虚增，所以必须分开。
-- ============================================================================
CREATE TABLE IF NOT EXISTS `purchase_orders` (
  `po_id`        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `entity_id`    BIGINT UNSIGNED NOT NULL,
  `po_no`        VARCHAR(64) NOT NULL,
  `vendor_id`    BIGINT UNSIGNED NULL,
  `vendor_name`  VARCHAR(200) NOT NULL,
  `po_date`      DATE NOT NULL,
  `expected_date` DATE NULL,
  `currency`     CHAR(3) NOT NULL DEFAULT 'HKD',
  `amount`       DECIMAL(18,2) NOT NULL DEFAULT 0,
  `tax_amount`   DECIMAL(18,2) NOT NULL DEFAULT 0,
  `gross_original` DECIMAL(18,2) NOT NULL DEFAULT 0,
  `exchange_rate` DECIMAL(18,10) NOT NULL DEFAULT 1,
  `amount_functional` DECIMAL(18,2) NOT NULL DEFAULT 0,
  -- draft 草稿 · open 已下单 · partial 部分收货 · received 已收齐 · closed 已关闭 · cancelled 已取消
  `status`       ENUM('draft','open','partial','received','closed','cancelled') NOT NULL DEFAULT 'draft',
  `notes`        VARCHAR(500) NULL,
  `created_by`   VARCHAR(64) NOT NULL,
  `retention_until` DATE NOT NULL,
  `created_at`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`po_id`),
  UNIQUE KEY `uk_po_no` (`entity_id`, `po_no`),
  KEY `idx_po_vendor` (`entity_id`, `vendor_name`),
  CONSTRAINT `fk_po_entity` FOREIGN KEY (`entity_id`) REFERENCES `entities` (`entity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采购订单（承诺，不进总账）';

CREATE TABLE IF NOT EXISTS `purchase_order_lines` (
  `line_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `po_id`       BIGINT UNSIGNED NOT NULL,
  `line_no`     INT NOT NULL,
  `description` VARCHAR(400) NOT NULL,
  `unit`        VARCHAR(32) NULL,
  `quantity`    DECIMAL(18,4) NOT NULL DEFAULT 1,
  `unit_price`  DECIMAL(18,4) NOT NULL DEFAULT 0,
  `amount`      DECIMAL(18,2) NOT NULL DEFAULT 0,
  `tax_rate`    DECIMAL(9,4) NULL,
  `tax_amount`  DECIMAL(18,2) NOT NULL DEFAULT 0,
  `received_qty` DECIMAL(18,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (`line_id`),
  KEY `idx_pol_po` (`po_id`),
  CONSTRAINT `fk_pol_po` FOREIGN KEY (`po_id`) REFERENCES `purchase_orders` (`po_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采购订单明细';

CREATE TABLE IF NOT EXISTS `purchase_order_receipts` (
  `receipt_id`   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `po_id`        BIGINT UNSIGNED NOT NULL,
  `receipt_no`   VARCHAR(64) NOT NULL,
  `received_date` DATE NOT NULL,
  `note`         VARCHAR(300) NULL,
  `created_by`   VARCHAR(64) NOT NULL,
  `created_at`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`receipt_id`),
  KEY `idx_por_po` (`po_id`),
  CONSTRAINT `fk_por_po` FOREIGN KEY (`po_id`) REFERENCES `purchase_orders` (`po_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采购订单收货记录';

CREATE TABLE IF NOT EXISTS `purchase_order_receipt_lines` (
  `line_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `receipt_id`  BIGINT UNSIGNED NOT NULL,
  `po_line_id`  BIGINT UNSIGNED NOT NULL,
  `quantity`    DECIMAL(18,4) NOT NULL,
  PRIMARY KEY (`line_id`),
  KEY `idx_porl_receipt` (`receipt_id`),
  CONSTRAINT `fk_porl_receipt` FOREIGN KEY (`receipt_id`) REFERENCES `purchase_order_receipts` (`receipt_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_porl_line` FOREIGN KEY (`po_line_id`) REFERENCES `purchase_order_lines` (`line_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='收货明细';

-- 账单回指订单：一张订单可以分几次转发票
ALTER TABLE `bills`
  ADD COLUMN `source_po_id` BIGINT UNSIGNED NULL AFTER `vendor_invoice_no`,
  ADD KEY `idx_bills_po` (`source_po_id`);
