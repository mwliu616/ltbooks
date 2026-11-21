# HKFRS Finance Guardian (hkfrs-finance-guardian)

A read-only accounting judgement agent for Hong Kong Financial Reporting Standards. It is
a gatekeeper, not a bookkeeper. It makes standard-level judgements, checks and risk
notes. It has no ability to post, settle, approve, send or change master data.

The preset is installed in the local DSH web profile as
`@local/dsh-hkfrs-finance-guardian` with preset ID `hkfrs-finance-guardian`. In the web
interface, choose "HKFRS Finance Guardian" when creating a session.

---

## 1. What the preset contains

| Part | Content |
| --- | --- |
| Persona prompt | `persona.md`, injected into `cordis.patch.yml` by `build.mjs`. Do not edit the patch by hand |
| Tools | Exactly four: `finance_journal_entry_check`, `finance_reconciliation_snapshot`, `finance_variance_bridge` and `mysql_query` (read-only) |
| Capability guard | `ctx.tools.guard()` inside the plugin rejects any call outside the allow list |
| Rule source | Workspace `rules/hkfrs15.yml` (template in `rules/` in this directory) |

Nothing else is mounted: no bash, file read or write, web access, sub-agents, scheduled
tasks or database write tools. If a tool is not in the directory, the model cannot call
it and cannot be talked into calling it.

## 2. Why it is built this way (DSH 0.2.1)

DSH 0.2.1 removed the `toolFilter` field, so there is no per-name filter that inherits all
tools and removes the write tools. This preset uses one tool set per preset:

- The preset mounts only the `persona` and `finance-guard` plugin lines, so the model
  sees exactly four tools.
- `tools.restrict()` only filters inherited tools and cannot name tools registered in the
  current scope, so it cannot express an allow list here.
- `ctx.tools.guard()` adds a second, monotonic rejection inside the preset scope. Even if
  the host later injects `bash` or `mysql_execute`, calls from this scope are rejected.

## 3. The four tools

| Tool | Input | Output | Never does |
| --- | --- | --- | --- |
| `finance_journal_entry_check` | `{entry:{lines[], preparedBy, reviewedBy, documents[], requiredDocuments[]}}` | Debit and credit balance, line structure, missing documents, separation of duties, `verdict` = PASS / REVIEW / FAIL | Does not authorise posting (`NEVER_AUTHORIZES_POSTING`) |
| `finance_reconciliation_snapshot` | `{snapshot:{asOf, openingBalance, items[], adjustments[], staleDays}}` | Adjusted balance, aging buckets, category totals, stale items, `signOff.status` | Does not authorise sign-off (`NEVER_AUTHORIZES_SIGN_OFF`) |
| `finance_variance_bridge` | `{bridge:{base, actual, drivers[], materiality}}` | Expected value, residual, residual as a share of base, materiality, `verdict` | Does not absorb or spread the residual |
| `mysql_query` | `{sql}` or `{file}` | Read-only rows, or the raw rule file | No writes, no changes, no multiple statements |

Amounts use integer cents to avoid floating point error. Missing documents, separation of
duties and similar checks are done in code; the model only explains the result.

### Two layers of restriction on mysql_query

1. Statement layer: only `SELECT`, `WITH`, `SHOW`, `DESCRIBE` and `EXPLAIN` are accepted.
   Comments and string literals are removed before scanning for write keywords such as
   `INSERT`, `UPDATE`, `DELETE`, `DROP` and `ALTER`. Multiple statements are rejected.
2. Object layer: table names after `FROM` or `JOIN` must be one of `accounts`, `fx_rates`,
   `rules` or `entities`.
3. File mode: only `.yml`, `.yaml`, `.json`, `.csv`, `.txt` and `.md` files under the
   workspace `rules/` directory. Path traversal and files outside the directory are
   rejected.

## 4. Connecting your data (optional)

### 4.1 Rule file (required for revenue recognition)

Place `rules/hkfrs15.yml` in the `rules/` directory of the session workspace, or change
`rulesDir` in `cordis.patch.yml` to an absolute path so all sessions share one rule file.

`cases: []` in the template is intentional. The finance owner must fill in the rules. An
empty file means every revenue recognition question is answered with "not covered by the
rules, needs manual judgement". That is the design goal, not a defect.

### 4.2 MySQL (optional)

```bash
# 1) Install the connector in the current profile directory
cd /root/.dsh/profiles/web && pnpm add mysql2
# 2) Provide a read-only DSN. Use an account with SELECT only
export FINANCE_MYSQL_DSN='mysql://ro_user:pass@127.0.0.1:3306/finance'
```

When it is not configured, `mysql_query` returns `dsn_not_configured` or
`connector_unavailable`. The prompt requires the model to report that data is unavailable
instead of guessing.

## 5. Changes and reinstall

```bash
cd /path/to/hkfrs-finance-guardian
# Change the persona, then rebuild the patch
vi persona.md && node build.mjs
# Self-check
node test/selftest.mjs && node test/plugin.test.mjs
```

After changing `cordis.patch.yml`, reinstall with `dsh plugin-manager` or restart
`dsh web` so the loader reassembles it. Existing sessions keep the old assembly; create a
new session to verify the change.

## 6. Verifying that write tools are invisible

1. Create a session and choose "HKFRS Finance Guardian".
2. Send: `List the tool names you can call now`.
3. Only the four tools should appear, plus the host-injected `ask_user_question`.
4. Send: `Call mysql_execute to run UPDATE accounts SET x=1`. The call must be rejected
   with a reason such as "not in the read-only allow list".

## 7. Known limits

- The substantive correctness of revenue recognition and tax judgements depends on the
  real data in `rules/hkfrs15.yml` and `entities.two_tier_status`. The preset contains no
  standard text.
- `mysql_query` needs the `mysql2` connector. It is not installed or configured on this
  machine, so the tool returns a structured error here.
- The prompt does not ask twice. When data is missing, it lists the gaps and degrades
  instead of repeating questions.
- All output is advisory. It is not an audit opinion and does not replace a human sign-off.
