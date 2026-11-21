-- ============================================================================
-- 用户与认证
--
-- 密码用 PBKDF2-HMAC-SHA256（stdlib 实现，不引第三方库）：
--   pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
-- 角色：admin / accountant / auditor。auditor 为只读，服务端强制。
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
  user_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username      VARCHAR(64)  NOT NULL,
  display_name  VARCHAR(120) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          ENUM('admin','accountant','auditor') NOT NULL DEFAULT 'accountant',
  status        ENUM('active','disabled') NOT NULL DEFAULT 'active',
  must_change   TINYINT(1) NOT NULL DEFAULT 1,
  last_login_at DATETIME(3) NULL,
  failed_count  INT UNSIGNED NOT NULL DEFAULT 0,
  locked_until  DATETIME(3) NULL,
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (user_id),
  UNIQUE KEY uk_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 会话表：服务端保存，Cookie 只带不可猜的 session_id
CREATE TABLE IF NOT EXISTS user_sessions (
  session_id   CHAR(64)     NOT NULL,
  user_id      BIGINT UNSIGNED NOT NULL,
  csrf_token   CHAR(64)     NOT NULL,
  ip           VARCHAR(64)  NULL,
  user_agent   VARCHAR(255) NULL,
  created_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  last_seen_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  expires_at   DATETIME(3)  NOT NULL,
  PRIMARY KEY (session_id),
  KEY idx_sessions_user (user_id),
  KEY idx_sessions_expires (expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
