<?php
/** 代理后端 PDF：带内部令牌取流后原样输出，浏览器可直接预览/打印。 */
declare(strict_types=1);

// 与 index.php 保持同一会话：未登录不得下载发票 PDF
ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
$lang = (string) ($_GET['lang'] ?? ($_COOKIE['ledu_pdf_lang'] ?? ($_SESSION['lang'] ?? 'zh_cn')));
if (!in_array($lang, ['zh_cn', 'zh_hk', 'en'], true)) { $lang = 'zh_cn'; }
$text = [
    'zh_cn' => ['未登录', '缺少发票 ID', 'PDF 生成失败'],
    'zh_hk' => ['未登錄', '缺少發票 ID', 'PDF 生成失敗'],
    'en' => ['Not signed in', 'Missing invoice ID', 'PDF generation failed'],
][$lang];
if (empty($_SESSION['user'])) {
    http_response_code(403);
    exit($text[0]);
}

require_once __DIR__ . '/../lib/api.php';

$id = (int) ($_GET['id'] ?? 0);
if (!$id) { http_response_code(400); exit($text[1]); }

$token = (string) (getenv('LEDU_API_TOKEN') ?: '');
$ch = curl_init(api_base() . '/invoices/' . $id . '/pdf?lang=' . rawurlencode($lang));
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 60,
    CURLOPT_HTTPHEADER => ['X-Ledu-Token: ' . $token],
]);
$pdf = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($pdf === false || $code !== 200) {
    http_response_code(500);
    exit($text[2]);
}
header('Content-Type: application/pdf');
header('Content-Disposition: inline; filename="invoice-' . $id . '.pdf"');
header('Content-Length: ' . strlen($pdf));
echo $pdf;
