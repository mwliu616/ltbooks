<?php
/** 年度 PDF 包进度（浏览器拿不到内部令牌，这里代理一下）。 */
declare(strict_types=1);

// 与 index.php 保持同一会话：任务进度只对已登录用户开放
ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
if (empty($_SESSION['user'])) {
    http_response_code(403);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'unauthorized']);
    exit;
}

require_once __DIR__ . '/../lib/api.php';

$token = (string) (getenv('LEDU_API_TOKEN') ?: '');
$job = preg_replace('/[^a-f0-9]/', '', (string) ($_GET['job'] ?? ''));
if ($job === '') { echo json_encode(['error' => 'bad_job']); exit; }
$ch = curl_init(api_base() . '/reports/year-pack/status/' . $job);
curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20,
                        CURLOPT_HTTPHEADER => ['X-Ledu-Token: ' . $token]]);
$body = curl_exec($ch);
$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
header('Content-Type: application/json; charset=utf-8');
http_response_code($code === 200 ? 200 : ($code ?: 500));
echo $body === false ? json_encode(['error' => 'api_unreachable']) : $body;
