<?php
/*
 * LtBooks — pages/receipts.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
// 收款核销：销售侧的回款入口，复用核销实现但锁定为「收款」方向
$pageDirection = 'received';
require __DIR__ . '/_cash_alloc.php';
