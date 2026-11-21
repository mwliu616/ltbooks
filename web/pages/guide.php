<?php
/*
 * LtBooks — pages/guide.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 模块使用说明：每个功能区一页完整说明，便于集中查阅操作步骤。
 *  讲清三件事：这块是干什么的 / 一笔业务怎么从头走到尾 / 每个按钮按了会怎样。
 */
$topic = (string) ($_GET['topic'] ?? 'sales');
$G = [
'sales' => [
    'name' => '销售',
    'what' => '管「你开给客户的东西」：报价 → 订单 → 发票 → 收款。贷记单用来冲销。',
    'flow' => [
        ['客户', '?p=customers', '先把客户建一次。之后开票直接选，不用每次手打名字。'],
        ['报价单', '?p=quotes', '给客户报价。客户接受后点「转发票」，自动带出明细。'],
        ['销售订单', '?p=sales-orders', '需要分批交付时才用。订单只登记不记账，履行一段转一段发票。'],
        ['发票', '?p=invoices', '正式单据。草稿 → 提交复核 → 记账，记账后才进收入与应收。'],
        ['收款', '?p=receipts', '钱到账后核销发票。核销后发票的「余额」变 0。'],
        ['贷记单', '?p=credit-notes', '退货或折让。选原发票，过账时自动冲减那张发票的余额。'],
        ['经常性发票', '?p=recurring-invoices', '每月固定收的钱（订阅、月费）。到点「立即生成」出一张草稿。'],
    ],
    'fields' => [
        ['客户名称', '必填。选不到就点「+ 新客户」手打，之后再建档也行。'],
        ['付款条件', '选了自动算到期日：收到即付 / Net 15 / 30 / 45 / 60。'],
        ['项目明细', '数量 × 单价 ×（1 − 行折扣%）= 行金额；税% 单独算税额。'],
        ['整单折扣率', '在右下角，作用于小计，税额按比例同步。'],
        ['附件', '合同、PO、送货单拖到页面底部，保存后自动挂到这张发票上。'],
    ],
    'faq' => [
        ['开错了怎么办？', '没记账的直接改或删；记过账的开贷记单冲销，不要改原单。'],
        ['为什么记账按钮是灰的？', '有阻断项：缺汇率、税率不在白名单、或多币种没配汇率。看页面顶部的提示。'],
        ['客户还没付钱，能先开票吗？', '能。发票记的是应收，收款是另一件事，收到钱再核销。'],
    ],
],
'purchase' => [
    'name' => '采购',
    'what' => '管「别人开给你的东西」：供应商 → 账单 → 付款。费用单据走同一套。',
    'flow' => [
        ['供应商', '?p=vendors', '先把供应商建一次。'],
        ['账单', '?p=bills', '收到供应商发票后录进来。草稿 → 复核 → 记账，记账后进成本费用与应付。'],
        ['费用', '?p=expenses', '没有正式发票的小额支出（打车、文具）走这里，比建账单快。'],
        ['付款', '?p=payments', '付钱后核销账单，账单余额归零。'],
        ['经常性账单', '?p=recurring-bills', '每月固定的支出（房租、订阅）。到点生成草稿。'],
    ],
    'fields' => [
        ['供应商发票号', '对方单据上的号，对账和查证用；填了以后搜得到。'],
        ['费用 / 成本科目', '借方记哪个科目。服务类记费用，转售的货记销售成本。'],
        ['付款条件', '同销售：选完自动算到期日。'],
        ['附件', '供应商发票扫描件拖到页面底部，保存后自动挂上。'],
    ],
    'faq' => [
        ['账单和费用有什么区别？', '账单有供应商、有账期、进应付；费用是当场付掉的零星支出。'],
        ['对方没给发票能记吗？', '能，但复核时会被标记「凭证缺失」。建议先记费用，拿到票再补附件。'],
    ],
],
'bank' => [
    'name' => '银行',
    'what' => '管钱的实际进出：账户、流水、对账、规则、转账。账簿里的「现金」就是这里的总账余额。',
    'flow' => [
        ['银行账户', '?p=banks', '每个账户对应一个会计科目（如 1121）。'],
        ['导入月结单', '?p=bank-import', '上传 PDF / CSV，系统解析成流水，导入时会校验「期初 + 贷 − 借 = 期末」。'],
        ['交易记录', '?p=bank-transactions', '所有流水一页看，按已匹配 / 未匹配筛。'],
        ['对账', '?p=reconcile', '把流水和发票、账单、凭证对上。对上了「已匹配」。'],
        ['银行规则', '?p=bank-rules', '摘要含某个词的自动指定对方科目，比如月费 → 银行手续费。'],
        ['转账', '?p=bank-transfer', '两个同币种账户之间调钱，生成一张两行凭证。'],
    ],
    'fields' => [
        ['匹配', '流水和单据金额一致就算匹配；多币种按银行当天汇率折算后比。'],
        ['未匹配', '不代表错，只代表还没归类。月结前应该清零。'],
        ['规则套用', '只给建议清单，不会自动记账——避免规则写错把钱记乱。'],
    ],
    'faq' => [
        ['为什么现金显示 0？', '看「银行账户」的余额是不是从总账取；期初结转或手工分录不会自动更新账户表。'],
        ['导入报「不平」怎么办？', '说明解析漏行或多行。先看导入预览的条数与期初期末，再决定是补行还是手工录入。'],
        ['流水能删吗？', '不能。重复导入会被识别为重复流水，标出来但不会重复入账。'],
    ],
],
'accounting' => [
    'name' => '会计',
    'what' => '管账簿本身：科目、凭证、汇率、期初、月结。单据最终都汇到这里。',
    'flow' => [
        ['会计科目', '?p=accounts', '110 个 HKFRS 科目。不建议随便加，先用现有的。'],
        ['日记账', '?p=journal', '所有凭证。按日期看、按科目看、反冲都在这里。'],
        ['手工凭证', '?p=journal-new', '单据覆盖不到的分录（折旧、计提、调整）用它，借贷必须平。'],
        ['汇率维护', '?p=rates', '外币折算用。缺汇率的单据过不了账，会显示「缺汇率」。'],
        ['期初余额', '?p=opening-balances', '看每个科目的期初，以及期初结转凭证。'],
        ['月结', '?p=period-close', '对账 → 重估 → 计提 → 锁账。锁了之后当期不能再写。'],
    ],
    'fields' => [
        ['凭证号', '系统按「公司-功能-日期-序号」自动生成，可以改。'],
        ['借贷平衡', '保存时校验，不平直接拒绝，不会「先记了再调」。'],
        ['反冲', '已过账的凭证不能删，只能反冲；反冲会留审计痕迹。'],
    ],
    'faq' => [
        ['为什么改不了上个月的账？', '期间锁定了。要改先解锁，解锁会记录是谁解的。'],
        ['审计链是什么？', '每条记账动作都算一个哈希，串成链。任何一条被改，链就断。'],
    ],
],
'reports' => [
    'name' => '报表',
    'what' => '把账簿数字整理成给人看的样子：三大表、试算表、总账、账龄、税务。',
    'flow' => [
        ['报表中心', '?p=report-center', '一个期间的概览，往下接所有报表，也是年包入口。'],
        ['财务报表', '?p=report-statements', '资产负债表 + 损益表 + 现金流量表，可出 PDF。'],
        ['试算表', '?p=report-tb', '全部科目借贷余额，检查账平不平。'],
        ['总分类账', '?p=report-gl', '按科目看发生额；要看逐笔用「详细的总分类账」。'],
        ['账龄', '?p=report-aging', '谁欠你、你欠谁、多久了。'],
        ['利得税', '?p=tax', '两级制税率与应缴税款。'],
    ],
    'fields' => [
        ['期间', '默认按财务年度（LEDU 是 4 月 30 日年结）给，可以改任意起止。'],
        ['PDF 语言', '报表 PDF 可单独选英文 / 简中 / 繁中，与界面语言无关。'],
        ['导出 CSV', '每张报表都能导出，导出会记一条审计。'],
    ],
    'faq' => [
        ['报表数和单据对不上？', '报表只算「已过账」的。草稿和待复核不在里面。'],
        ['外币怎么显示？', '按原币列示，另给折 HKD 列；不同币种不会直接相加。'],
    ],
],
];
$G_EN = [
'sales' => [
    'name' => 'Sales',
    'what' => 'Everything you issue to customers: quote → order → invoice → payment. Credit notes reverse.',
    'flow' => [
        ['Customers', '?p=customers', 'Create the customer once; later invoices pick it from a list.'],
        ['Quotes', '?p=quotes', 'Quote the customer. Once accepted, use "Convert to invoice" to copy the lines.'],
        ['Sales orders', '?p=sales-orders', 'Only for staged delivery. Orders are recorded, not posted; invoice each fulfilled part.'],
        ['Invoices', '?p=invoices', 'The official document. Draft → review → post; only posted invoices hit revenue and receivables.'],
        ['Receipts', '?p=receipts', 'Apply the money received against invoices; the balance drops to zero.'],
        ['Credit notes', '?p=credit-notes', 'Returns or allowances. Pick the original invoice; posting reduces its balance.'],
        ['Recurring invoices', '?p=recurring-invoices', 'Fixed monthly income (subscriptions). "Generate now" creates a draft.'],
    ],
    'fields' => [
        ['Customer', 'Required. If missing, use "+ New customer" to type a name.'],
        ['Payment terms', 'Drives the due date: due on receipt / Net 15 / 30 / 45 / 60.'],
        ['Line items', 'Qty × unit price × (1 − line discount%) = line amount; tax% is computed separately.'],
        ['Overall discount', 'Bottom right; applies to the subtotal and scales tax.'],
        ['Attachments', 'Drop contracts, POs or delivery notes at the bottom; they attach after saving.'],
    ],
    'faq' => [
        ['I made a mistake — what now?', 'Drafts can be edited or deleted. Posted documents must be reversed with a credit note.'],
        ['Why is the post button greyed out?', 'A blocker exists: missing FX rate, tax rate not whitelisted, or multi-currency without a rate.'],
        ['Can I invoice before payment?', 'Yes. Invoicing records a receivable; payment is a separate step.'],
    ],
],
'purchase' => [
    'name' => 'Purchases',
    'what' => 'Everything others issue to you: vendor → bill → payment. Expenses use the same path.',
    'flow' => [
        ['Vendors', '?p=vendors', 'Create the vendor once.'],
        ['Bills', '?p=bills', 'Record the vendor invoice. Draft → review → post; posting hits cost and payables.'],
        ['Expenses', '?p=expenses', 'Small spends without a formal invoice (taxi, stationery).'],
        ['Payments', '?p=payments', 'Apply payment against bills; the balance goes to zero.'],
        ['Recurring bills', '?p=recurring-bills', 'Fixed monthly costs (rent, subscriptions).'],
    ],
    'fields' => [
        ['Vendor', 'Required.'],
        ['Expense account', 'Defaults to 6200; change per line when needed.'],
        ['Tax', 'VAT/GST is computed from the line tax%.'],
    ],
    'faq' => [
        ['Bill vs expense?', 'Bills are for vendor invoices with a document; expenses for small spends without one.'],
        ['Posted the wrong amount?', 'Reverse it and enter a corrected bill.'],
    ],
],
'bank' => [
    'name' => 'Banking',
    'what' => 'Statements, matching, rules and transfers.',
    'flow' => [
        ['Transactions', '?p=bank-transactions', 'All bank lines in one list, filtered by matched or unmatched.'],
        ['Import statement', '?p=bank-import', 'Upload a PDF/CSV statement; lines are parsed and matched.'],
        ['Bank rules', '?p=bank-rules', 'Auto-match by description patterns.'],
        ['Transfer', '?p=bank-transfer', 'Move money between your own accounts.'],
    ],
    'fields' => [
        ['Account', 'Pick the bank account the statement belongs to.'],
        ['Match', 'Link a line to an invoice, bill or entry, or create one on the spot.'],
    ],
    'faq' => [
        ['Why is a line unmatched?', 'No matching document yet — create one, or add a rule.'],
    ],
],
'accounting' => [
    'name' => 'Accounting',
    'what' => 'Journal, reconciliation, period close and audit trail.',
    'flow' => [
        ['Journal', '?p=journal', 'Every entry, document-generated or manual.'],
        ['Settlement', '?p=settle', 'One table showing who owes what and what is unmatched.'],
        ['Period close', '?p=period-close', 'Close the month, run reports, lock the period.'],
        ['Audit log', '?p=audit', 'Every write operation, chained by hash.'],
    ],
    'fields' => [
        ['Entry date', 'Decides the period; reports are dated by this, never by creation time.'],
        ['Accounts', 'Balanced debits and credits; the ledger rejects anything else.'],
    ],
    'faq' => [
        ['Can I edit a posted entry?', 'No. Reverse it and post a corrected one.'],
        ['What does locking do?', 'Blocks any write into that period.'],
    ],
],
'reports' => [
    'name' => 'Reports',
    'what' => 'Every report, all dated by voucher date.',
    'flow' => [
        ['Report centre', '?p=report-center', 'Period overview, every report and the annual pack.'],
        ['Financial statements', '?p=report-statements', 'Position + P&L + cash flow, exportable as PDF.'],
        ['Trial balance', '?p=report-tb', 'Debits, credits and balances of all accounts.'],
        ['General ledger', '?p=report-gl', 'Movement by account; use GL detail for line-by-line.'],
        ['Aging', '?p=report-aging', 'Who owes you, whom you owe, for how long.'],
        ['Profits tax', '?p=tax', 'Two-tier rates and tax payable.'],
    ],
    'fields' => [
        ['Period', 'Defaults to the financial year (LEDU closes 30 April); any range allowed.'],
        ['PDF language', 'Report PDFs pick English / Simplified / Traditional Chinese independently of the UI.'],
        ['CSV export', 'Every report exports, and each export is audited.'],
    ],
    'faq' => [
        ['Report figures differ from documents?', 'Reports only count posted entries; drafts are excluded.'],
        ['How is foreign currency shown?', 'Original currency plus an HKD column; currencies are never summed directly.'],
    ],
],
];
if (lang() === 'en') { $G = $G_EN; }
if (!isset($G[$topic])) { $topic = 'sales'; }
$g = $G[$topic];
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e($g['name']) ?> · <?= e(t('使用说明')) ?></h1>
    <div class="page-sub"><?= e($g['what']) ?></div>
  </div>
  <div class="page-actions">
    <?php foreach ($G as $k => $x): if ($k === $topic) { continue; } ?>
      <a class="btn sm" href="?p=guide&topic=<?= e($k) ?>"><?= e($x['name']) ?></a>
    <?php endforeach; ?>
  </div>
</div>

<?= help_html('guide') ?>

<section class="card" style="margin-bottom:16px">
  <div class="card-head"><h2 class="card-title"><?= e(t('一笔业务从头走到尾')) ?></h2></div>
  <div class="card-body">
    <ol class="guide-steps">
      <?php foreach ($g['flow'] as $i => $s): ?>
        <li>
          <div class="gs-n"><?= $i + 1 ?></div>
          <div class="gs-body">
            <a class="gs-t" href="<?= e($s[1]) ?>"><?= e($s[0]) ?> →</a>
            <div class="gs-d"><?= e($s[2]) ?></div>
          </div>
        </li>
      <?php endforeach; ?>
    </ol>
  </div>
</section>

<section class="card" style="margin-bottom:16px">
  <div class="card-head"><h2 class="card-title"><?= e(t('表单上每个字段是什么意思')) ?></h2></div>
  <div class="table-wrap"><table>
    <thead><tr><th style="width:180px"><?= e(t('字段')) ?></th><th><?= e(t('怎么填')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($g['fields'] as $f): ?>
      <tr><td><b><?= e($f[0]) ?></b></td><td><?= e($f[1]) ?></td></tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</section>

<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('常见问题')) ?></h2></div>
  <div class="card-body">
    <?php foreach ($g['faq'] as $q): ?>
      <details class="faq"><summary><?= e($q[0]) ?></summary><div class="faq-a"><?= e($q[1]) ?></div></details>
    <?php endforeach; ?>
  </div>
</section>
