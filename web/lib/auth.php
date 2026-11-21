<?php
/*
 * LtBooks — lib/auth.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 会话与权限。服务端强制：未登录不可访问；审计角色不可写。
 * 会话数据保存在 Python 侧的 user_sessions 表，Cookie 只带随机 session_id。
 */
declare(strict_types=1);

require_once __DIR__ . '/api.php';

const COOKIE_SESSION = 'ledu_sid';
// PHP 与后端共用受控附件目录；安装器按实际部署路径注入 LEDU_UPLOAD_DIR。
define('UPLOAD_DIR', getenv('LEDU_UPLOAD_DIR') ?: '/opt/ltbooks/uploads');
const COOKIE_NAME    = 'ledu_user';

function session_cookie_value(): string
{
    return (string) ($_COOKIE[COOKIE_SESSION] ?? '');
}

/** 取当前登录用户；失败返回 null。 */
function current_user(): ?array
{
    $sid = session_cookie_value();
    if ($sid === '') {
        return null;
    }
    $r = api_request('GET', '/auth/me', null, ['X-Ledu-Session: ' . $sid]);
    if (!$r['ok']) {
        return null;
    }
    $u = $r['data']['user'] ?? null;
    if (!$u) {
        return null;
    }
    $u['csrfToken'] = $r['data']['csrfToken'] ?? '';
    return $u;
}

function login_user(string $username, string $password): array
{
    $r = api_post('/auth/login', ['username' => $username, 'password' => $password]);
    if (!$r['ok']) {
        return ['ok' => false, 'error' => (string) ($r['error'] ?? '登录失败')];
    }
    return ['ok' => true, 'data' => $r['data']];
}

function set_session_cookie(string $sid, int $ttlHours = 12): void
{
    setcookie(COOKIE_SESSION, $sid, [
        'expires'  => time() + $ttlHours * 3600,
        'path'     => '/',
        'httponly' => true,
        'secure'   => true,
        'samesite' => 'Lax',
    ]);
}

function clear_session_cookie(): void
{
    setcookie(COOKIE_SESSION, '', [
        'expires'  => time() - 3600,
        'path'     => '/',
        'httponly' => true,
        'secure'   => true,
        'samesite' => 'Lax',
    ]);
}

function logout_user(): void
{
    $sid = session_cookie_value();
    if ($sid !== '') {
        api_post('/auth/logout', ['sessionId' => $sid]);
    }
    clear_session_cookie();
}

function csrf_token(): string
{
    return (string) ($_SESSION['csrf'] ?? '');
}

function csrf_ok(): bool
{
    $sent = (string) ($_POST['_csrf'] ?? '');
    return $sent !== '' && hash_equals(csrf_token(), $sent);
}

function csrf_field(): string
{
    return '<input type="hidden" name="_csrf" value="' . e(csrf_token()) . '">';
}

/** 是否可写（审计角色只读）。 */
function can_write(): bool
{
    $u = current_user();
    return $u !== null && in_array($u['role'] ?? '', ['admin', 'accountant'], true);
}

function require_writer(): void
{
    if (!can_write()) {
        http_response_code(403);
        echo '<div class="errbox"><b>403 禁止操作</b><div>当前角色为只读，不能执行写操作。</div></div>';
        exit;
    }
}
