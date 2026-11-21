-- ============================================================================
-- 22 · 票据识别：纠正样本与学到的规则
--
-- 为什么要单独两张表：
--   识别错的地方（供应商名称取成中文、单号读错、税额凭空来）不是靠「再想一遍」能修好的，
--   只能靠人改一次、系统记住。
--   extract_samples 存「模型当时怎么读、人改成什么」；
--   extract_rules 存「这个供应商的单据，某某字段固定是什么」。
--   规则由确定性代码在识别之后套用，不依赖模型是否记得。
-- ============================================================================
CREATE TABLE IF NOT EXISTS `extract_samples` (
  `sample_id`   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `entity_id`   BIGINT UNSIGNED NOT NULL,
  `vendor_key`  VARCHAR(120) NOT NULL COMMENT '归一化后的开票方（用于分组学习）',
  `doc_kind`    VARCHAR(16)  NOT NULL DEFAULT 'bill',
  `predicted`   LONGTEXT NOT NULL COMMENT '模型识别结果（JSON）',
  `corrected`   LONGTEXT NOT NULL COMMENT '人确认/修改后的结果（JSON）',
  `changed`     LONGTEXT NOT NULL COMMENT '改了哪些字段（JSON：[{field,from,to}]）',
  `raw_excerpt` TEXT NULL COMMENT '原文片段，便于回溯是什么单据',
  `actor`       VARCHAR(64) NOT NULL,
  `created_at`  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`sample_id`),
  KEY `idx_samples_vendor` (`entity_id`, `vendor_key`),
  CONSTRAINT `fk_extract_samples_entity` FOREIGN KEY (`entity_id`) REFERENCES `entities` (`entity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='票据识别的纠正样本';

CREATE TABLE IF NOT EXISTS `extract_rules` (
  `rule_id`    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `entity_id`  BIGINT UNSIGNED NOT NULL,
  `vendor_key` VARCHAR(120) NOT NULL,
  `field`      VARCHAR(32)  NOT NULL COMMENT 'partyName / currency / taxOriginal / docNoPrefix …',
  `value`      VARCHAR(200) NOT NULL COMMENT '固定值（apply=set）或匹配值',
  `mode`       VARCHAR(16)  NOT NULL DEFAULT 'set' COMMENT 'set：一律改写为该值',
  `samples`    INT NOT NULL DEFAULT 0,
  `status`     ENUM('active','paused','retired') NOT NULL DEFAULT 'active',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`rule_id`),
  UNIQUE KEY `uk_rule` (`entity_id`, `vendor_key`, `field`, `value`),
  KEY `idx_rules_vendor` (`entity_id`, `vendor_key`, `status`),
  CONSTRAINT `fk_extract_rules_entity` FOREIGN KEY (`entity_id`) REFERENCES `entities` (`entity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='票据识别的确定性改写规则（学出来的）';
