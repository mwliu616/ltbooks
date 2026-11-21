<?php
/** 处理进度代理（浏览器拿不到内部令牌）。 */
declare(strict_types=1);

// 与 index.php 保持同一会话：进度只对已登录用户开放
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
$tok = preg_replace('/[^a-z0-9]/i', '', (string) ($_GET['tok'] ?? ''));
if ($tok === '') { echo json_encode(['stage' => 'unknown', 'label' => '']); exit; }
$ch = curl_init(api_base() . '/ai/progress/' . $tok);
curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 8,
                        CURLOPT_HTTPHEADER => ['X-Ledu-Token: ' . $token]]);
$body = curl_exec($ch);
curl_close($ch);
header('Content-Type: application/json; charset=utf-8');
echo $body === false ? json_encode(['stage' => 'unknown', 'label' => '']) : $body;
