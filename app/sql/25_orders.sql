-- ============================================================================
-- 25 · 销售订单 / 采购订单（合并成一套，用 direction 区分）
--
-- 为什么合并：两侧字段完全一样，分开写两套表和两套接口只会慢慢不一致。
-- 订单是「承诺」：不进总账、不产生应收应付；转成发票并过账才进账。
--
-- 销售/采购合同扫描件作为订单附件上传（invoice_files 加 order_id）。
-- 订单不是必经流程：也可以直接从发票开始，把合同扫描件挂在发票上。
-- ============================================================================
DROP TABLE IF EXISTS `purchase_order_receipt_lines`;
DROP TABLE IF EXISTS `purchase_order_receipts`;
DROP TABLE IF EXISTS `purchase_order_lines`;
DROP TABLE IF EXISTS `purchase_orders`;

CREATE TABLE IF NOT EXISTS `orders` (
  `order_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `entity_id`    BIGINT UNSIGNED NOT NULL,
  `direction`    ENUM('sales','purchase') NOT NULL,
  `order_no`     VARCHAR(64) NOT NULL,
  `party_id`     BIGINT UNSIGNED NULL,
  `party_name`   VARCHAR(200) NOT NULL,
  `order_date`   DATE NOT NULL,
  `expected_date` DATE NULL,
  `currency`     CHAR(3) NOT NULL DEFAULT 'HKD',
  `amount`       DECIMAL(18,2) NOT NULL DEFAULT 0,
  `tax_amount`   DECIMAL(18,2) NOT NULL DEFAULT 0,
  `gross_original` DECIMAL(18,2) NOT NULL DEFAULT 0,
  `exchange_rate` DECIMAL(18,10) NOT NULL DEFAULT 1,
  `amount_functional` DECIMAL(18,2) NOT NULL DEFAULT 0,
  `contract_note` VARCHAR(200) NULL,
  `reference`    VARCHAR(100) NULL,
  -- draft 草稿 · open 已下单 · partial 部分履行 · fulfilled 已履行完 · closed 已关闭 · cancelled 已取消
  `status`       ENUM('draft','open','partial','fulfilled','closed','cancelled') NOT NULL DEFAULT 'draft',
  `notes`        VARCHAR(500) NULL,
  `created_by`   VARCHAR(64) NOT NULL,
  `retention_until` DATE NOT NULL,
  `created_at`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`order_id`),
  UNIQUE KEY `uk_order_no` (`entity_id`, `order_no`),
  KEY `idx_order_dir` (`entity_id`, `direction`, `status`),
  KEY `idx_order_party` (`entity_id`, `party_name`),
  CONSTRAINT `fk_order_entity` FOREIGN KEY (`entity_id`) REFERENCES `entities` (`entity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='销售/采购订单（承诺，不进总账）';

CREATE TABLE IF NOT EXISTS `order_lines` (
  `line_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_id`    BIGINT UNSIGNED NOT NULL,
  `line_no`     INT NOT NULL,
  `description` VARCHAR(400) NOT NULL,
  `unit`        VARCHAR(32) NULL,
  `quantity`    DECIMAL(18,4) NOT NULL DEFAULT 1,
  `unit_price`  DECIMAL(18,4) NOT NULL DEFAULT 0,
  `amount`      DECIMAL(18,2) NOT NULL DEFAULT 0,
  `tax_rate`    DECIMAL(9,4) NULL,
  `tax_amount`  DECIMAL(18,2) NOT NULL DEFAULT 0,
  `done_qty`    DECIMAL(18,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (`line_id`),
  KEY `idx_ol_order` (`order_id`),
  CONSTRAINT `fk_ol_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`order_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='订单明细';

CREATE TABLE IF NOT EXISTS `order_fulfilments` (
  `fulfilment_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_id`      BIGINT UNSIGNED NOT NULL,
  `direction`     ENUM('sales','purchase') NOT NULL,
  `doc_no`        VARCHAR(64) NOT NULL,
  `doc_date`      DATE NOT NULL,
  `note`          VARCHAR(300) NULL,
  `created_by`    VARCHAR(64) NOT NULL,
  `created_at`    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`fulfilment_id`),
  KEY `idx_of_order` (`order_id`),
  CONSTRAINT `fk_of_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`order_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='订单履行记录：采购=收货/验收，销售=发货/交付';

CREATE TABLE IF NOT EXISTS `order_fulfilment_lines` (
  `line_id`       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `fulfilment_id` BIGINT UNSIGNED NOT NULL,
  `order_line_id` BIGINT UNSIGNED NOT NULL,
  `quantity`      DECIMAL(18,4) NOT NULL,
  PRIMARY KEY (`line_id`),
  KEY `idx_ofl_ful` (`fulfilment_id`),
  CONSTRAINT `fk_ofl_ful` FOREIGN KEY (`fulfilment_id`) REFERENCES `order_fulfilments` (`fulfilment_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ofl_line` FOREIGN KEY (`order_line_id`) REFERENCES `order_lines` (`line_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='履行明细';

-- 合同扫描件挂到订单上（与发票/账单共用一张附件表）
ALTER TABLE `invoice_files`
  ADD COLUMN `order_id` BIGINT UNSIGNED NULL AFTER `expense_id`,
  ADD KEY `idx_if_order` (`order_id`);

-- 附件归属放宽到「订单」：订单也要挂合同扫描件
ALTER TABLE `invoice_files` DROP CONSTRAINT `chk_invfile_owner`;
ALTER TABLE `invoice_files`
  ADD CONSTRAINT `chk_invfile_owner` CHECK (
    `invoice_id` IS NOT NULL OR `bill_id` IS NOT NULL
    OR `expense_id` IS NOT NULL OR `order_id` IS NOT NULL);

-- 发票/账单回指订单
ALTER TABLE `invoices`
  ADD COLUMN `source_order_id` BIGINT UNSIGNED NULL AFTER `bill_no`,
  ADD KEY `idx_inv_order` (`source_order_id`);
