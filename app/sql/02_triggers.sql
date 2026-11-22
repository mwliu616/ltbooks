-- ============================================================================
-- LEDU 会计功能台 — 不可篡改强制层
--
-- 依据 v5.0 §2.4 / §3.2.2：
--   - posted 分录禁止 UPDATE 金额/日期/科目
--   - 禁止 DELETE 非草稿 journal_entries；草稿允许编辑、删除
--   - 更正只能通过反向分录
--   - 发票 posted 后原始文件不得删除
--   - 禁止对非草稿 invoices / bank_lines 物理删除
--   - audit_log 只追加
--   - 锁定/关闭期间禁止写入该期间
--
-- 为什么放数据库层：应用层自律可被一次直连绕过。触发器让约束成为
-- 数据库的物理属性，对任何账号（含应用账号）生效。
-- SIGNAL SQLSTATE '45000' 表示业务规则拒绝，应用应转为可读提示。
-- ============================================================================

SET NAMES utf8mb4;

DROP TRIGGER IF EXISTS trg_je_before_insert;
DROP TRIGGER IF EXISTS trg_je_before_update;
DROP TRIGGER IF EXISTS trg_je_before_delete;
DROP TRIGGER IF EXISTS trg_jl_before_insert;
DROP TRIGGER IF EXISTS trg_jl_before_update;
DROP TRIGGER IF EXISTS trg_jl_before_delete;
DROP TRIGGER IF EXISTS trg_inv_before_delete;
DROP TRIGGER IF EXISTS trg_bankline_before_delete;
DROP TRIGGER IF EXISTS trg_invfile_before_delete;
DROP TRIGGER IF EXISTS trg_audit_before_update;
DROP TRIGGER IF EXISTS trg_audit_before_delete;
DROP TRIGGER IF EXISTS trg_period_lock_before_update;
DROP TRIGGER IF EXISTS trg_period_lock_before_delete;
DROP TRIGGER IF EXISTS trg_bank_currency_before_update;

DELIMITER $$

-- ---------------------------------------------------------------------------
-- 1. journal_entries：期间锁定 + posted 冻结 + 禁止删除
-- ---------------------------------------------------------------------------

-- 写入前检查所属期间是否已锁定（§3.2.2）
CREATE TRIGGER trg_je_before_insert BEFORE INSERT ON journal_entries
FOR EACH ROW
BEGIN
  DECLARE v_lock VARCHAR(8) DEFAULT 'open';
  SELECT status INTO v_lock FROM period_locks
   WHERE entity_id = NEW.entity_id AND period = LEFT(NEW.entry_date, 7);
  IF v_lock IN ('locked','closed') THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'PERIOD_LOCK: 该期间已锁定，禁止写入日记账';
  END IF;
END$$

CREATE TRIGGER trg_je_before_update BEFORE UPDATE ON journal_entries
FOR EACH ROW
BEGIN
  DECLARE v_lock VARCHAR(8) DEFAULT 'open';

  -- 已过账/已冲销：核心字段冻结（§2.4）
  IF OLD.status IN ('posted','reversed') THEN
    IF NEW.entry_date <> OLD.entry_date THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的日期不可修改，请用反向分录更正';
    END IF;
    IF NEW.total_debit <> OLD.total_debit OR NEW.total_credit <> OLD.total_credit THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的借贷合计不可修改，请用反向分录更正';
    END IF;
    IF NEW.entity_id <> OLD.entity_id OR NEW.entry_no <> OLD.entry_no THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的实体与凭证号不可修改';
    END IF;
  END IF;

  -- 状态流转白名单
  IF OLD.status = 'posted' AND NEW.status = 'draft' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'INVALID_FLOW: 已过账分录不可退回草稿';
  END IF;
  IF OLD.status = 'reversed' AND NEW.status <> 'reversed' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'INVALID_FLOW: 已冲销分录状态不可变更';
  END IF;

  -- 过账必须留下过账人与时间（审计要求）
  IF NEW.status = 'posted' AND OLD.status <> 'posted' THEN
    IF NEW.posted_by IS NULL OR NEW.posted_at IS NULL THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'AUDIT: 过账必须记录 posted_by 与 posted_at';
    END IF;
  END IF;

  -- 目标期间若已锁定，禁止把分录改入该期间
  IF NEW.entry_date <> OLD.entry_date THEN
    SELECT status INTO v_lock FROM period_locks
     WHERE entity_id = NEW.entity_id AND period = LEFT(NEW.entry_date, 7);
    IF v_lock IN ('locked','closed') THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'PERIOD_LOCK: 目标期间已锁定，禁止改入';
    END IF;
  END IF;
END$$

CREATE TRIGGER trg_je_before_delete BEFORE DELETE ON journal_entries
FOR EACH ROW
BEGIN
  IF OLD.status <> 'draft' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'IMMUTABLE: 非草稿日记账禁止物理删除；请标记 reversed 并生成反向分录';
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- 2. journal_lines：分录过账后行不可增删改
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_jl_before_insert BEFORE INSERT ON journal_lines
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  SELECT status INTO v_status FROM journal_entries WHERE entry_id = NEW.entry_id;
  IF v_status IN ('posted','reversed') THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录不可追加行；请用反向分录更正';
  END IF;
END$$

CREATE TRIGGER trg_jl_before_update BEFORE UPDATE ON journal_lines
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  SELECT status INTO v_status FROM journal_entries WHERE entry_id = OLD.entry_id;
  IF v_status IN ('posted','reversed') THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的行不可修改；请用反向分录更正';
  END IF;
END$$

CREATE TRIGGER trg_jl_before_delete BEFORE DELETE ON journal_lines
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  SELECT status INTO v_status FROM journal_entries WHERE entry_id = OLD.entry_id;
  IF v_status IN ('posted','reversed') THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的行不可删除；请用反向分录更正';
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- 3. 业务单据：禁止物理删除（§2.4）
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_inv_before_delete BEFORE DELETE ON invoices
FOR EACH ROW
BEGIN
  IF OLD.status <> 'draft' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'IMMUTABLE: 非草稿发票禁止物理删除；请置 status=void 并保留记录（留存 7 年）';
  END IF;
END$$

CREATE TRIGGER trg_bankline_before_delete BEFORE DELETE ON bank_lines
FOR EACH ROW
BEGIN
  -- 已对账的流水永久保护；未对账的允许随「删除月结单导入」一起删除，便于重新导入
  IF OLD.match_status = 'matched' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'IMMUTABLE: 已对账的银行流水禁止删除；请先撤销匹配';
  END IF;
END$$

CREATE TRIGGER trg_invfile_before_delete BEFORE DELETE ON invoice_files
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  SELECT status INTO v_status FROM invoices WHERE invoice_id = OLD.invoice_id;
  IF v_status = 'posted' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'RETENTION: 发票已过账，其原始文件不得删除（留存 7 年）';
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- 4. bank_accounts：产生流水后币种不得修改（§2.12）
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_bank_currency_before_update BEFORE UPDATE ON bank_accounts
FOR EACH ROW
BEGIN
  DECLARE v_lines INT DEFAULT 0;
  IF NEW.currency <> OLD.currency THEN
    SELECT COUNT(*) INTO v_lines FROM bank_lines WHERE bank_account_id = OLD.account_id;
    IF v_lines > 0 THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 账户已产生流水，币种不得修改；如需变更请走受控的账户重建流程';
    END IF;
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- 5. audit_log：只追加（哈希链前提）
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_audit_before_update BEFORE UPDATE ON audit_log
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'IMMUTABLE: audit_log 只可追加，不可修改（哈希链会断裂）';
END$$

CREATE TRIGGER trg_audit_before_delete BEFORE DELETE ON audit_log
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'IMMUTABLE: audit_log 只可追加，不可删除（哈希链会断裂）';
END$$

-- ---------------------------------------------------------------------------
-- 6. period_locks：关闭后不可回退，锁定记录不可删除
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_period_lock_before_update BEFORE UPDATE ON period_locks
FOR EACH ROW
BEGIN
  IF OLD.status = 'closed' AND NEW.status <> 'closed' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'PERIOD_LOCK: 已关闭期间不可重新打开；如需更正请在当前期间做调整分录';
  END IF;
END$$

CREATE TRIGGER trg_period_lock_before_delete BEFORE DELETE ON period_locks
FOR EACH ROW
BEGIN
  IF OLD.status IN ('locked','closed') THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'PERIOD_LOCK: 已锁定/已关闭的期间记录不可删除（留痕要求）';
  END IF;
END$$

DELIMITER ;

SELECT '不可篡改层建立完成' AS result,
       (SELECT COUNT(*) FROM information_schema.triggers
         WHERE trigger_schema = 'ledu_accounting') AS trigger_count;
