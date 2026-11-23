<?php
/*
 * LtBooks — precheck.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 提交前预判代理：浏览器 → PHP（会话 + CSRF）→ Python 智能体。
 * 只读审查，不写入任何单据；最终是否提交仍由人决定。
 */
declare(strict_types=1);

ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
require_once __DIR__ . '/lib/auth.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function out(array $data, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

$user = $_SESSION['user'] ?? current_user();
if (!is_array($user)) {
    out(['ok' => false, 'error' => '未登录'], 403);
}
if (empty($_SESSION['user'])) { $_SESSION['user'] = $user; }
if (empty($_SESSION['csrf'])) { $_SESSION['csrf'] = (string) ($user['csrfToken'] ?? ''); }
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    out(['ok' => false, 'error' => '只支持 POST'], 405);
}

$raw = file_get_contents('php://input');
$body = json_decode((string) $raw, true);
if (!is_array($body)) {
    out(['ok' => false, 'error' => '请求格式不正确'], 400);
}
$csrf = (string) ($body['csrf'] ?? '');
$expect = (string) ($_SESSION['csrf'] ?? ($user['csrfToken'] ?? ''));
if ($csrf === '' || $expect === '' || !hash_equals($expect, $csrf)) {
    out(['ok' => false, 'error' => '会话校验失败，请刷新页面后重试'], 403);
}
unset($body['csrf']);
$body['actor'] = (string) ($user['username'] ?? 'owner');

$r = api_post('/agents/precheck', $body, 90);
if (!$r['ok']) {
    out(['ok' => false, 'error' => (string) ($r['error'] ?? '预判失败')], 502);
}
out(['ok' => true, 'data' => $r['data']]);
