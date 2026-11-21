-- ============================================================================
-- 20 · AI 待确认动作（propose → 人工确认 → 执行）
--
-- 设计的核心是 D-01 不被绕开：
--   智能体只能写「提案」（这张表），写不了任何业务表；
--   业务写入只发生在人在界面上点了「确认」之后，执行者是登录用户，不是智能体。
-- 所以这张表的作用是「把 AI 的判断变成一张可核对、可拒绝、可追溯的待办」，
-- 而不是给它一个后门。
-- ============================================================================
CREATE TABLE IF NOT EXISTS `ai_actions` (
  `action_id`    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `entity_id`    BIGINT UNSIGNED NOT NULL,
  `run_id`       BIGINT UNSIGNED DEFAULT NULL COMMENT '关联的智能体运行（ai_run.run_id）',
  `action_type`  VARCHAR(40) NOT NULL COMMENT 'create_bill / create_invoice / create_expense / post_document',
  `title`        VARCHAR(200) NOT NULL COMMENT '给人看的一句话',
  `summary`      LONGTEXT NOT NULL COMMENT '确认卡片：字段行、匹配结果、风险提示（JSON）',
  `payload`      LONGTEXT NOT NULL COMMENT '确认后真正写入的字段（JSON）',
  `status`       ENUM('proposed','confirmed','cancelled','failed') NOT NULL DEFAULT 'proposed',
  `created_by`   VARCHAR(64) NOT NULL COMMENT '提案来源（智能体名或用户名）',
  `confirmed_by` VARCHAR(64) DEFAULT NULL COMMENT '点确认的人',
  `created_at`   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `decided_at`   DATETIME(3) DEFAULT NULL,
  `result`       LONGTEXT DEFAULT NULL COMMENT '执行结果：单据号 / 凭证号 / 错误',
  `source_file`  VARCHAR(255) DEFAULT NULL COMMENT '来源文件（OCR 导入时）',
  PRIMARY KEY (`action_id`),
  KEY `idx_ai_actions_status` (`entity_id`, `status`, `action_id`),
  CONSTRAINT `fk_ai_actions_entity` FOREIGN KEY (`entity_id`) REFERENCES `entities` (`entity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AI 待确认动作：智能体只能提案，写入由人工确认后执行';
