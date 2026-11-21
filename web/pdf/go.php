<?php
/**
 * 导出跳板：先记住这次选的 PDF 语言，再跳到真正的导出地址。
 * 这样「导出 PDF ▾」里选的语言与页面上单张报表的 PDF 按钮始终是同一个语言。
 */
declare(strict_types=1);
$l = (string) ($_GET['l'] ?? 'zh_cn');
if (!in_array($l, ['zh_cn', 'zh_hk', 'en'], true)) { $l = 'zh_cn'; }
$u = (string) ($_GET['u'] ?? '');
if ($u === '' || !str_starts_with($u, '/')) {
    http_response_code(400);
    exit(['zh_cn' => '无效目标', 'zh_hk' => '無效目標', 'en' => 'Invalid target'][$l]);
}
setcookie('ledu_pdf_lang', $l, [
    'expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax', 'secure' => true,
]);
header('Location: /pdf/reports.php?u=' . rawurlencode($u));
exit;
