<?php
/**
 * Lt-AI-Books 版本与构建信息。
 *
 * 版本号手工维护（发版时修改）；构建时间取静态资源的最新修改时间，
 * 这样发版时不必改两处，也能直接看出当前部署的是哪一次构建。
 *
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
const LTBOOKS_VERSION = '1.1';
const LTBOOKS_RELEASE_NAME = 'Lt-AI-Books';

/**
 * 返回静态资源的最新构建标记（Ymd.Hi）。
 */
function ltbooks_build(): string
{
    static $build = null;
    if ($build !== null) {
        return $build;
    }
    $latest = 0;
    foreach (['assets/app.css', 'index.php', 'lib/ui.php'] as $f) {
        $p = __DIR__ . '/../' . $f;
        if (is_file($p)) { $latest = max($latest, (int) filemtime($p)); }
    }
    $build = $latest ? date('Ymd.Hi', $latest) : date('Ymd');
    return $build;
}

/**
 * 返回展示用的版本行，例如 “v1.1 · build 20261124.1015”。
 */
function ltbooks_version_line(): string
{
    return 'v' . LTBOOKS_VERSION . ' · build ' . ltbooks_build();
}
