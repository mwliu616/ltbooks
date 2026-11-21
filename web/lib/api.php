<?php
/*
 * LtBooks — lib/api.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 与 Python 后端通信的薄客户端。
 * 后端只监听回环地址；PHP 侧不持有任何数据库凭据。
 */
declare(strict_types=1);

function api_base(): string
{
    $b = getenv('LEDU_API_BASE');
    return rtrim($b !== false && $b !== '' ? $b : 'http://127.0.0.1:8099', '/');
}

/**
 * 构造内部请求头。令牌只有前端服务知道，公网无法伪造，
 * 因此后端可以信任随后附带的角色头。
 */
function internal_headers(array $extraHeaders = []): array
{
    $token = (string) (getenv('LEDU_API_TOKEN') ?: '');
    $headers = ['Accept: application/json'];
    if ($token !== '') {
        $headers[] = 'X-Ledu-Token: ' . $token;
    }
    $u = $_SESSION['user'] ?? null;
    if (is_array($u)) {
        $headers[] = 'X-Ledu-Role: ' . (string) ($u['role'] ?? '');
        $headers[] = 'X-Ledu-User: ' . (string) ($u['username'] ?? '');
    }
    $sid = (string) ($_COOKIE['ledu_sid'] ?? '');
    if ($sid !== '') {
        $headers[] = 'X-Ledu-Session: ' . $sid;
    }
    // 按头名去重（后者覆盖前者）：重复的 X-Ledu-Session 会被服务端合并成
    // "a,b" 这类畸形值，导致会话校验失败——实测踩中过。
    $byName = [];
    foreach (array_merge($headers, $extraHeaders) as $line) {
        $pos = strpos($line, ':');
        $name = $pos === false ? $line : strtolower(trim(substr($line, 0, $pos)));
        $byName[$name] = $line;
    }
    return array_values($byName);
}

function api_request(string $method, string $path, ?array $body = null, array $extraHeaders = [], int $timeout = 120): array
{
    $ch = curl_init(api_base() . $path);
    $headers = internal_headers($extraHeaders);
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_TIMEOUT        => $timeout, // 含 AI 提取或备份恢复，调用方可延长
        CURLOPT_CONNECTTIMEOUT => 5,
    ];
    if ($body !== null) {
        $payload = json_encode($body, JSON_UNESCAPED_UNICODE);
        $headers[] = 'Content-Type: application/json';
        $opts[CURLOPT_POSTFIELDS] = $payload;
    }
    $opts[CURLOPT_HTTPHEADER] = $headers;
    curl_setopt_array($ch, $opts);

    $raw  = curl_exec($ch);
    $err  = curl_error($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($raw === false) {
        return ['ok' => false, 'status' => 0, 'data' => null,
                'error' => '无法连接后端服务：' . $err];
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return ['ok' => false, 'status' => $code, 'data' => null,
                'error' => '后端返回非 JSON 内容'];
    }
    $ok = $code >= 200 && $code < 300;
    return [
        'ok'     => $ok,
        'status' => $code,
        'data'   => $data,
        // 后端不同接口的错误字段名不一致：校验类用 reason，通用用 message，
        // 兜底才是 error —— 都要透出去，否则用户只看到「请求失败」。
        'error'  => $ok ? null : _translate_api_error((string) (
            $data['message'] ?? $data['reason'] ?? $data['error'] ?? '请求失败'
        )),
    ];
}

/** 后端错误消息 i18n：精确查 t()，命中就返回译文，找不到返回原文。 */
function _translate_api_error(string $msg): string
{
    if ($msg === '' || !function_exists('t')) return $msg;
    if (t($msg) !== $msg) return t($msg);
    // 把具体行号归一化后再查一次
    $norm = preg_replace('/第\s*\d+\s*行/', '第 :i 行', $msg);
    if ($norm !== $msg && t($norm) !== $norm) return t($norm);
    return $msg;
}

function api_get(string $path): array
{
    // 报表类接口按当前界面语言取科目名；没带 lang 时补上，
    // 免得界面是中文、科目名却是英文（Interest Income · 4500）。
    if (function_exists('lang') && !preg_match('/(?:^|[?&])lang=/', $path)) {
        $path .= (str_contains($path, '?') ? '&' : '?') . 'lang=' . rawurlencode(lang());
    }
    // 请求内静态缓存 — 消除同一页面里重复拉取 customers/vendors/accounts
    static $_cache = [];
    static $_CACHE_TTL = 120; // 秒
    $meta = ['/customers', '/vendors', '/accounts', '/tax-rates', '/currencies', '/bank-accounts'];
    $key = parse_url($path, PHP_URL_PATH) ?: $path;
    if (in_array($key, $meta, true)) {
        $hit = $_cache[$path] ?? null;
        if ($hit !== null && (time() - $hit['t']) < $_CACHE_TTL) {
            return $hit['v'];
        }
        $v = api_request('GET', $path);
        $_cache[$path] = ['v' => $v, 't' => time()];
        return $v;
    }
    return api_request('GET', $path);
}

function api_post(string $path, array $body = [], int $timeout = 120): array
{
    return api_request('POST', $path, $body, [], $timeout);
}


/**
 * 上传文件到后端并取回解析结果（multipart/form-data）。
 * 用于银行对账单的 CSV / XLSX / XLS / PDF 文件。
 */
function api_upload(string $path, string $field, string $tmpPath, string $filename,
                    array $extra = [], int $timeout = 120): array
{
    if (!is_file($tmpPath)) {
        return ['ok' => false, 'error' => '上传文件不存在'];
    }
    $post = $extra;
    $post[$field] = new CURLFile($tmpPath, mime_content_type($tmpPath) ?: 'application/octet-stream', $filename);

    $ch = curl_init(api_base() . $path);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $post,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => $timeout,
        CURLOPT_HTTPHEADER     => internal_headers(),
    ]);
    $raw = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($raw === false) {
        return ['ok' => false, 'error' => '无法连接后端：' . $err];
    }
    $data = json_decode((string) $raw, true);
    if (!is_array($data)) {
        return ['ok' => false, 'error' => '后端返回非 JSON（HTTP ' . $code . '）'];
    }
    if ($code >= 400 || isset($data['error'])) {
        return ['ok' => false, 'error' => _translate_api_error((string) ($data['message'] ?? $data['error'] ?? '解析失败')),
                'code' => $code, 'errorKind' => (string) ($data['error'] ?? ''),
                'hint' => $data['hint'] ?? null];
    }
    return ['ok' => true, 'data' => $data];
}
