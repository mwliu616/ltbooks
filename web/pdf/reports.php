<?php
/** 报表 PDF 代理：带内部令牌取流后输出，浏览器可直接预览/打印。 */
declare(strict_types=1);

// 与 index.php 保持同一会话：未登录不得取任何报表或原始附件
ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();

// 报错文案跟随 PDF 语言（由 /pdf/go.php 写入的 Cookie 决定）
$_pdfLang = (string) ($_COOKIE['ledu_pdf_lang'] ?? 'zh_cn');
$_PT = [
    'zh_cn' => ['未登录', '不允许的路径', '生成失败：', '生成失败：报表服务未返回文件'],
    'zh_hk' => ['未登錄', '不允許的路徑', '生成失敗：', '生成失敗：報表服務未返回文件'],
    'en'    => ['Not signed in', 'Path not allowed', 'Generation failed: ',
               'Generation failed: the report service returned no file'],
][$_pdfLang] ?? ['未登录', '不允许的路径', '生成失败：', '生成失败：报表服务未返回文件'];

if (empty($_SESSION['user'])) {
    http_response_code(403);
    exit($_PT[0]);
}

require_once __DIR__ . '/../lib/api.php';

$token = (string) (getenv('LEDU_API_TOKEN') ?: '');
$path = (string) ($_GET['u'] ?? '');
// 只允许调用报表与单据 PDF 端点，避免变成任意代理
if (!preg_match('#^/reports/(pdf|statements/pdf|statements)#', $path)
    && !preg_match('#^/tax/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/doc-files/\d+/raw$#', $path)
    && !preg_match('#^/invoices/\d+/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/bills/\d+/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/quotes/\d+/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/credit-notes/\d+/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/orders/\d+/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/payments/(received|made)/\d+/pdf(\?[\w=&%.\-]*)?$#', $path)
    && !preg_match('#^/company/letterhead/pdf(\?[\w=&%.\-]*)?$#', $path)) {
    http_response_code(400);
    exit($_PT[1]);
}
$url = api_base() . $path;
$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 120,
    CURLOPT_HTTPHEADER => ['X-Ledu-Token: ' . $token],
]);
$body = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
$type = (string) curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
curl_close($ch);

if ($body === false || $code !== 200) {
    // 上游的报错（缺汇率、附件不存在、期间锁定…）原样转出去，
    // 别一律显示「生成失败」——那句话对排查没有任何帮助。
    $j = json_decode((string) $body, true);
    $msg = is_array($j) ? (string) ($j['message'] ?? $j['error'] ?? '') : '';
    http_response_code($code >= 400 ? $code : 500);
    header('Content-Type: text/plain; charset=utf-8');
    exit($msg !== '' ? $_PT[2] . $msg : $_PT[3]);
}
header('Content-Type: ' . ($type ?: 'application/pdf'));
header('Content-Length: ' . strlen($body));
header('Content-Disposition: inline');
echo $body;
