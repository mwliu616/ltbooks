<?php
/**
 * 记账凭证 PDF（预览/打印）
 *
 *   /pdf/voucher.php?id=349             单张凭证（含附件页）
 *   /pdf/voucher.php?from=…&to=…        区间内全部凭证，按日期+凭证号排序
 *   /pdf/voucher.php?q=LEDU-JE-…        按关键字筛选
 *
 * 逻辑：登录校验 → 拼 API 路径 → 带内部令牌取流 → 原样输出 PDF。
 * 一张凭证一页，附件按登记顺序跟在它后面。
 */
declare(strict_types=1);
ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
require_once __DIR__ . '/../lib/api.php';

$lang = (string) ($_GET['lang'] ?? ($_COOKIE['ledu_pdf_lang'] ?? ($_SESSION['lang'] ?? 'zh_cn')));
if (!in_array($lang, ['zh_cn', 'zh_hk', 'en'], true)) { $lang = 'zh_cn'; }
$text = [
    'zh_cn' => ['未登录', '生成失败：', '生成失败：凭证服务未返回文件'],
    'zh_hk' => ['未登錄', '生成失敗：', '生成失敗：憑證服務未返回文件'],
    'en' => ['Not signed in', 'Generation failed: ', 'Generation failed: the voucher service returned no file'],
][$lang];
if (empty($_SESSION['user'])) {
    http_response_code(403);
    exit($text[0]);
}

$id = (int) ($_GET['id'] ?? 0);
if ($id > 0) {
    $path = '/journal/' . $id . '/voucher.pdf?lang=' . urlencode($lang);
} else {
    $qs = ['lang=' . urlencode($lang)];
    if (($_GET['from'] ?? '') !== '') { $qs[] = 'from=' . urlencode((string) $_GET['from']); }
    if (($_GET['to'] ?? '') !== '') { $qs[] = 'to=' . urlencode((string) $_GET['to']); }
    if (($_GET['q'] ?? '') !== '') { $qs[] = 'q=' . urlencode((string) $_GET['q']); }
    if (($_GET['ids'] ?? '') !== '') { $qs[] = 'ids=' . urlencode((string) $_GET['ids']); }
    $path = '/journal/vouchers.pdf?' . implode('&', $qs);
}

$ch = curl_init(api_base() . $path);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 180,
    CURLOPT_HTTPHEADER => [
        'X-Ledu-Token: ' . (string) (getenv('LEDU_API_TOKEN') ?: ''),
        'X-Ledu-Role: ' . (string) ($_SESSION['user']['role'] ?? 'accountant'),
    ],
]);
$body = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
$type = (string) curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
curl_close($ch);

if ($body === false || $code !== 200) {
    $j = json_decode((string) $body, true);
    $msg = is_array($j) ? (string) ($j['message'] ?? $j['error'] ?? '') : '';
    http_response_code($code >= 400 ? $code : 500);
    header('Content-Type: text/plain; charset=utf-8');
    exit($msg !== '' ? $text[1] . $msg : $text[2]);
}
header('Content-Type: application/pdf');
header('Content-Length: ' . strlen($body));
header('Content-Disposition: inline');
header('X-Content-Type-Options: nosniff');
echo $body;
