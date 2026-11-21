<?php
/*
 * LtBooks — pay-json.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 核销浮窗取数的 JSON 出口。
 * 独立文件，不经 index.php 的布局，避免把 HTML 混进 JSON。
 */
declare(strict_types=1);

ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
require_once __DIR__ . '/lib/api.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

if (empty($_SESSION['user'])) {
    http_response_code(403);
    echo json_encode(['ok' => false, 'error' => '未登录']);
    exit;
}

$type = (string) ($_GET['type'] ?? '');
$id   = (int) ($_GET['id'] ?? 0);
$kind = (string) ($_GET['kind'] ?? 'received');
if (!$id) {
    echo json_encode(['ok' => false, 'error' => '缺少 ID']);
    exit;
}

switch ($type) {
    case 'payment':
        $path = '/payments/' . (in_array($kind, ['received', 'made'], true) ? $kind : 'received') . '/' . $id;
        break;
    case 'invoice':
        $path = '/invoices/' . $id;
        break;
    case 'bill':
        $path = '/bills/' . $id;
        break;
    default:
        echo json_encode(['ok' => false, 'error' => '未知类型']);
        exit;
}

$r = api_get($path);
echo json_encode(
    $r['ok'] ? ['ok' => true, 'data' => $r['data']] : ['ok' => false, 'error' => (string) ($r['error'] ?? '查询失败')],
    JSON_UNESCAPED_UNICODE
);
