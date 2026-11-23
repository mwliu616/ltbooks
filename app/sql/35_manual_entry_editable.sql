-- ============================================================================
-- 手工凭证过账后仍可修改，直到所属月份被锁定
--
-- 规则：
--   - 已过账的手工凭证（source_type='manual'、非冲销分录），只要所在期间
--     未锁定/未关闭，就允许修改日期、摘要、金额与分录行；
--   - 期间锁定/关闭后一律禁止修改（PERIOD_LOCK）；
--   - 系统生成分录（账单/发票/收付款/流水/期初）与冲销分录维持不可改；
--   - 已冲销的分录维持完全冻结；实体与凭证号始终不可改。
-- ============================================================================

SET NAMES utf8mb4;

DROP TRIGGER IF EXISTS trg_je_before_update;
DROP TRIGGER IF EXISTS trg_jl_before_insert;
DROP TRIGGER IF EXISTS trg_jl_before_update;
DROP TRIGGER IF EXISTS trg_jl_before_delete;

DELIMITER $$

CREATE TRIGGER trg_je_before_update BEFORE UPDATE ON journal_entries
FOR EACH ROW
BEGIN
  DECLARE v_lock VARCHAR(8) DEFAULT 'open';
  DECLARE v_editable INT DEFAULT 0;

  -- 已过账/已冲销：默认冻结；仅「未锁定期间的手工凭证」允许改日期与金额
  IF OLD.status IN ('posted','reversed') THEN
    IF OLD.status = 'posted' AND OLD.source_type = 'manual'
       AND OLD.reversal_of_entry_id IS NULL THEN
      SELECT status INTO v_lock FROM period_locks
       WHERE entity_id = OLD.entity_id AND period = LEFT(OLD.entry_date, 7);
      IF v_lock IN ('locked','closed') THEN
        IF NEW.entry_date <> OLD.entry_date
           OR NEW.total_debit <> OLD.total_debit
           OR NEW.total_credit <> OLD.total_credit
           OR NOT (NEW.description <=> OLD.description) THEN
          SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'PERIOD_LOCK: 该期间已锁定，禁止修改分录';
        END IF;
      ELSE
        SET v_editable = 1;
      END IF;
    END IF;

    IF NEW.entity_id <> OLD.entity_id OR NEW.entry_no <> OLD.entry_no THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的实体与凭证号不可修改';
    END IF;

    IF v_editable = 0 THEN
      IF NEW.entry_date <> OLD.entry_date THEN
        SIGNAL SQLSTATE '45000'
          SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的日期不可修改，请用反向分录更正';
      END IF;
      IF NEW.total_debit <> OLD.total_debit OR NEW.total_credit <> OLD.total_credit THEN
        SIGNAL SQLSTATE '45000'
          SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的借贷合计不可修改，请用反向分录更正';
      END IF;
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

CREATE TRIGGER trg_jl_before_insert BEFORE INSERT ON journal_lines
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  DECLARE v_src VARCHAR(16);
  DECLARE v_rev BIGINT;
  DECLARE v_entity BIGINT;
  DECLARE v_date DATE;
  DECLARE v_lock VARCHAR(8) DEFAULT 'open';
  SELECT status, source_type, reversal_of_entry_id, entity_id, entry_date
    INTO v_status, v_src, v_rev, v_entity, v_date
    FROM journal_entries WHERE entry_id = NEW.entry_id;
  IF v_status IN ('posted','reversed') THEN
    IF NOT (v_status = 'posted' AND v_src = 'manual' AND v_rev IS NULL) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录不可追加行；请用反向分录更正';
    END IF;
    SELECT status INTO v_lock FROM period_locks
     WHERE entity_id = v_entity AND period = LEFT(v_date, 7);
    IF v_lock IN ('locked','closed') THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'PERIOD_LOCK: 该期间已锁定，禁止修改分录行';
    END IF;
  END IF;
END$$

CREATE TRIGGER trg_jl_before_update BEFORE UPDATE ON journal_lines
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  DECLARE v_src VARCHAR(16);
  DECLARE v_rev BIGINT;
  DECLARE v_entity BIGINT;
  DECLARE v_date DATE;
  DECLARE v_lock VARCHAR(8) DEFAULT 'open';
  SELECT status, source_type, reversal_of_entry_id, entity_id, entry_date
    INTO v_status, v_src, v_rev, v_entity, v_date
    FROM journal_entries WHERE entry_id = OLD.entry_id;
  IF v_status IN ('posted','reversed') THEN
    IF NOT (v_status = 'posted' AND v_src = 'manual' AND v_rev IS NULL) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的行不可修改；请用反向分录更正';
    END IF;
    SELECT status INTO v_lock FROM period_locks
     WHERE entity_id = v_entity AND period = LEFT(v_date, 7);
    IF v_lock IN ('locked','closed') THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'PERIOD_LOCK: 该期间已锁定，禁止修改分录行';
    END IF;
  END IF;
END$$

CREATE TRIGGER trg_jl_before_delete BEFORE DELETE ON journal_lines
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(16);
  DECLARE v_src VARCHAR(16);
  DECLARE v_rev BIGINT;
  DECLARE v_entity BIGINT;
  DECLARE v_date DATE;
  DECLARE v_lock VARCHAR(8) DEFAULT 'open';
  SELECT status, source_type, reversal_of_entry_id, entity_id, entry_date
    INTO v_status, v_src, v_rev, v_entity, v_date
    FROM journal_entries WHERE entry_id = OLD.entry_id;
  IF v_status IN ('posted','reversed') THEN
    IF NOT (v_status = 'posted' AND v_src = 'manual' AND v_rev IS NULL) THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'IMMUTABLE: 已过账分录的行不可删除；请用反向分录更正';
    END IF;
    SELECT status INTO v_lock FROM period_locks
     WHERE entity_id = v_entity AND period = LEFT(v_date, 7);
    IF v_lock IN ('locked','closed') THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'PERIOD_LOCK: 该期间已锁定，禁止修改分录行';
    END IF;
  END IF;
END$$

DELIMITER ;

SELECT '手工凭证可改规则已生效' AS result;
