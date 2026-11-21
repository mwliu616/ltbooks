<?php
/*
 * LtBooks — pages/payments.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
// 付款核销：采购侧的付款入口，复用核销实现但锁定为「付款」方向
$pageDirection = 'made';
require __DIR__ . '/_cash_alloc.php';
