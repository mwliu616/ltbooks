<?php
/** 财务分析文件受控代理：只允许固定导出 endpoint 与白名单参数。 */
declare(strict_types=1);

ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();

$lang = (string) ($_GET['lang'] ?? $_SESSION['lang'] ?? 'zh_cn');
if (!in_array($lang, ['zh_cn', 'zh_hk', 'en'], true)) { $lang = 'zh_cn'; }
$text = [
    'zh_cn' => ['login' => '未登录', 'params' => '导出参数无效', 'failed' => '文件生成失败', 'invalid' => '报表服务未返回有效的 PDF 或 DOCX 文件'],
    'zh_hk' => ['login' => '未登錄', 'params' => '匯出參數無效', 'failed' => '文件生成失敗', 'invalid' => '報表服務未返回有效的 PDF 或 DOCX 文件'],
    'en' => ['login' => 'Not signed in', 'params' => 'Invalid export parameters', 'failed' => 'File generation failed', 'invalid' => 'The report service did not return a valid PDF or DOCX file'],
][$lang];
if (empty($_SESSION['user'])) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    exit($text['login']);
}

require_once __DIR__ . '/../lib/api.php';

$format = (string) ($_GET['format'] ?? 'pdf');
$period = (string) ($_GET['period'] ?? 'this_month');
if (!in_array($format, ['pdf', 'docx'], true)
    || !in_array($period, ['this_month', 'month', 'calendar_year', 'fiscal_year', 'inception', 'custom'], true)) {
    http_response_code(400);
    header('Content-Type: text/plain; charset=utf-8');
    exit($text['params']);
}
$params = ['format' => $format, 'period' => $period, 'lang' => $lang,
           'ai' => (string) ($_GET['ai'] ?? '0') === '1' ? '1' : '0'];
foreach (['month', 'year', 'from', 'to'] as $key) {
    $value = trim((string) ($_GET[$key] ?? ''));
    if ($value === '') { continue; }
    $pattern = $key === 'month' ? '/^\d{4}-\d{2}$/' : ($key === 'year' ? '/^\d{4}$/' : '/^\d{4}-\d{2}-\d{2}$/');
    if (!preg_match($pattern, $value)) {
        http_response_code(400);
        header('Content-Type: text/plain; charset=utf-8');
        exit($text['params']);
    }
    $params[$key] = $value;
}

$ch = curl_init(api_base() . '/reports/analysis/export?' . http_build_query($params));
$disposition = '';
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 5,
    CURLOPT_TIMEOUT => 300,
    CURLOPT_HTTPHEADER => internal_headers([
        'Accept: application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/json',
    ]),
    CURLOPT_HEADERFUNCTION => static function ($curl, $line) use (&$disposition): int {
        if (stripos($line, 'Content-Disposition:') === 0) {
            $candidate = trim(substr($line, strlen('Content-Disposition:')));
            if (preg_match('/^(inline|attachment); filename="?[A-Za-z0-9._-]+"?$/i', $candidate)) {
                $disposition = $candidate;
            }
        }
        return strlen($line);
    },
]);
$body = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($body === false || $code !== 200) {
    $json = json_decode((string) $body, true);
    $message = is_array($json) ? (string) ($json['message'] ?? $json['error'] ?? '') : '';
    http_response_code($code >= 400 && $code < 500 ? $code : 500);
    header('Content-Type: text/plain; charset=utf-8');
    exit($text['failed'] . ($message !== '' ? '：' . $message : ''));
}
$valid = $format === 'pdf' ? str_starts_with($body, '%PDF') : str_starts_with($body, "PK\x03\x04");
if (!$valid) {
    http_response_code(502);
    header('Content-Type: text/plain; charset=utf-8');
    exit($text['invalid']);
}

header('Content-Type: ' . ($format === 'pdf'
    ? 'application/pdf'
    : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'));
header('Content-Disposition: ' . ($disposition !== '' ? $disposition
    : ($format === 'pdf' ? 'inline' : 'attachment') . '; filename="LtBooks-Financial-Analysis.' . $format . '"'));
header('Content-Length: ' . strlen($body));
header('Cache-Control: private, no-store');
header('X-Content-Type-Options: nosniff');
echo $body;
