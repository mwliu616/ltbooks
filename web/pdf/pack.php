<?php
/** 年度 PDF 包下载（流式，带文件名）。 */
declare(strict_types=1);

// 与 index.php 保持同一会话：未登录不得下载年度报表包
ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
$lang = (string) ($_GET['lang'] ?? ($_COOKIE['ledu_pdf_lang'] ?? ($_SESSION['lang'] ?? 'zh_cn')));
if (!in_array($lang, ['zh_cn', 'zh_hk', 'en'], true)) { $lang = 'zh_cn'; }
$text = [
    'zh_cn' => ['未登录', '缺少任务号', '还没有生成好'],
    'zh_hk' => ['未登錄', '缺少任務號', '還沒有生成好'],
    'en' => ['Not signed in', 'Missing job ID', 'The annual pack is not ready yet'],
][$lang];
if (empty($_SESSION['user'])) {
    http_response_code(403);
    exit($text[0]);
}

require_once __DIR__ . '/../lib/api.php';

$token = (string) (getenv('LEDU_API_TOKEN') ?: '');
$job = preg_replace('/[^a-f0-9]/', '', (string) ($_GET['job'] ?? ''));
if ($job === '') { http_response_code(400); exit($text[1]); }
$ch = curl_init(api_base() . '/reports/year-pack/file/' . $job);
curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 300,
                        CURLOPT_HTTPHEADER => ['X-Ledu-Token: ' . $token]]);
$body = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if ($body === false || $code !== 200) { http_response_code(500); exit($text[2]); }
header('Content-Type: application/zip');
header('Content-Length: ' . strlen($body));
header('Content-Disposition: attachment; filename="annual-pack-' . $job . '.zip"');
echo $body;
