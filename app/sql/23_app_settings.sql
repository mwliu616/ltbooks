-- ============================================================================
-- 23 · 系统设置（键值）
--
-- 大模型 API 配置要能在界面上改，而不是改 .env 再重启服务。
-- 只存「运行期可改」的设置；安全相关的密钥仍优先取环境变量，这里存的是覆盖值。
-- ============================================================================
CREATE TABLE IF NOT EXISTS `app_settings` (
  `k`          VARCHAR(64)  NOT NULL,
  `v`          TEXT         NULL,
  `updated_by` VARCHAR(64)  NULL,
  `updated_at` DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`k`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='系统设置：大模型配置等可运行期修改的项';
