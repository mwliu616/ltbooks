<?php
/*
 * LtBooks — download.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 受控导出文件下载。文件名走白名单，避免变成任意文件代理。
 */
declare(strict_types=1);

// 与 index.php 保持同一会话名与 Cookie 属性，否则读不到登录状态
ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
require_once __DIR__ . '/lib/i18n.php';
require_once __DIR__ . '/lib/api.php';

if (empty($_SESSION['user'])) {
    http_response_code(403);
    exit(t('未登录'));
}

$f = (string) ($_GET['f'] ?? '');
$backup = (string) ($_GET['backup'] ?? '');
$statement = (int) ($_GET['statement'] ?? 0);
$isBackup = $backup !== '';
$isStatement = $statement > 0;

if ($isStatement) {
    // 原始月结单按导入批次号下载，后端会再次校验归属实体。
    $url = api_base() . '/bank/statement-imports/' . $statement . '/file';
} elseif ($isBackup) {
    // 备份包含完整账套与票据，只有管理员能下载；名称白名单同时阻止路径穿越。
    if (($_SESSION['user']['role'] ?? '') !== 'admin') {
        http_response_code(403);
        exit(t('只有管理员可以下载备份'));
    }
    $f = $backup;
    if (!preg_match('/^ltbooks-(?:[A-Za-z0-9][A-Za-z0-9_-]{0,31}-)?\d{8}T\d{6}Z-[0-9a-f]{8}\.tar\.gz$/', $f)) {
        http_response_code(400);
        exit(t('文件名不合法'));
    }
    $url = api_base() . '/backups/download/' . rawurlencode($f);
} else {
    // 只允许导出接口生成的文件名：export-<kind>-<yyyymmdd>-<hex8>.csv
    if (!preg_match('/^export-[a-z_]+-\d{8}-[0-9a-f]{8}\.csv$/', $f)) {
        http_response_code(400);
        exit(t('文件名不合法'));
    }
    $url = api_base() . '/export/download/' . rawurlencode($f);
}

// 先写入 PHP 临时流再转发，避免大型备份一次性占满 PHP 内存。
$tmp = tmpfile();
if ($tmp === false) {
    http_response_code(500);
    exit(t('无法创建临时下载文件'));
}
$ch = curl_init($url);
$respHeaders = [];
$curlOpts = [
    CURLOPT_FILE         => $tmp,
    CURLOPT_TIMEOUT      => $isBackup ? 600 : 60,
    CURLOPT_HTTPHEADER   => internal_headers(),
    CURLOPT_FAILONERROR  => false,
];
if ($isStatement) {
    // 原样转发后端的 Content-Type 与文件名（csv / xlsx / xls / pdf）。
    $curlOpts[CURLOPT_HEADERFUNCTION] = function ($ch, string $line) use (&$respHeaders): int {
        $pos = strpos($line, ':');
        if ($pos !== false) {
            $respHeaders[strtolower(trim(substr($line, 0, $pos)))] = trim(substr($line, $pos + 1));
        }
        return strlen($line);
    };
}
curl_setopt_array($ch, $curlOpts);
$ok = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($ok === false || $code !== 200) {
    fclose($tmp);
    http_response_code(404);
    if ($isStatement) {
        exit(t('月结单文件不存在或不可下载'));
    }
    exit($isBackup ? t('备份文件不存在或不可下载') : t('文件不存在或已过期'));
}

$size = fstat($tmp)['size'] ?? 0;
if ($isStatement) {
    header('Content-Type: ' . ($respHeaders['content-type'] ?? 'application/octet-stream'));
    header('Content-Disposition: ' . ($respHeaders['content-disposition'] ?? 'attachment'));
} else {
    header('Content-Type: ' . ($isBackup ? 'application/gzip' : 'text/csv; charset=utf-8'));
    header('Content-Disposition: attachment; filename="' . $f . '"');
}
header('Content-Length: ' . $size);
header('Cache-Control: private, no-store');
header('X-Content-Type-Options: nosniff');
rewind($tmp);
while (!feof($tmp)) {
    $chunk = fread($tmp, 1024 * 1024);
    if ($chunk === false) { break; }
    echo $chunk;
    flush();
}
fclose($tmp);
