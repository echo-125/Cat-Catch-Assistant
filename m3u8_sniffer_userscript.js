// ==UserScript==
// @name         猫抓助手
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  自动点击播放按钮，提取M3U8视频链接，支持多链接和分辨率选择
// @author       Claude Code
// @match        https://rouva4.xyz/*
// @match        https://missav.live/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    // ==================== 常量定义 ====================
    const SELECTORS = {
        PLAY_SVG_PATH: 'svg path[d*="M8 5v14l11-7z"]',
        VIDEO: 'video',
        IFRAME: 'iframe',
        SCRIPT: 'script',
        TITLE: 'h1, title, [class*="title"], [class*="video-title"]'
    };

    const DURATION = {
        MIN_SECONDS: 90,
        RETRY_INTERVAL_MS: 1000,
        INIT_DELAY_MS: 2000,
        FETCH_TIMEOUT_MS: 10000,
        MAX_LOG_ITEMS: 60,
        MAX_RESULT_ITEMS: 80,
        URL_CHECK_MS: 500,
        AD_WAIT_MS: 5000
    };

    const RETRY = { TIMES: 3 };

    const FILTER = {
        AD_KEYWORDS: ['ad', 'ads', 'adv', 'advertisement', 'silent-basis'],
        TARGET_MARKERS: ['index.jpg', 'index.m3u8'],
        PLAYLIST_MARKERS: ['playlist', 'master', 'variant', 'list.m3u8']
    };

    // ==================== 网站配置 ====================
    const SITE_CONFIGS = {
        'rouva4.xyz': {
            needsPlayClick: true,
            useIndexFilter: true,
            multiVideo: false
        }
    };

    // ==================== 状态管理 ====================
    const state = {
        capturedUrls: new Set(),
        pendingUrls: new Set(),
        durationCache: new Map(),
        requestHeaders: new Map(),
        playlistVariants: new Map(), // 存储 playlist 的分辨率变体
        isMinimized: false,
        panelElement: null,
        videoCounter: 0,
        originalDomain: window.location.hostname,
        allowOpenOnce: false,
        isJumpingBack: false
    };

    // 获取当前网站配置
    function getCurrentSiteConfig() {
        const hostname = window.location.hostname;
        for (const [site, config] of Object.entries(SITE_CONFIGS)) {
            if (hostname.includes(site)) return { name: site, config };
        }
        return { name: 'default', config: SITE_CONFIGS['rouva4.xyz'] };
    }

    const currentSite = getCurrentSiteConfig();
    const config = {
        autoClickPlay: currentSite.config.needsPlayClick,
        showResult: true,
        minDuration: DURATION.MIN_SECONDS
    };

    // ==================== 工具函数 ====================
    const log = (msg) => console.log(`[猫抓助手] ${msg}`);

    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[char]));
    }

    function trimContainerChildren(container, selector, maxItems) {
        const items = container.querySelectorAll(selector);
        if (items.length <= maxItems) return;
        for (let i = items.length - 1; i >= maxItems; i--) {
            items[i].remove();
        }
    }

    function renderEmptyResults() {
        const resultEl = document.getElementById('m3u8-result-list');
        if (!resultEl) return;
        resultEl.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">◎</div>
                <div class="empty-state-title">等待捕获链接</div>
                <div class="empty-state-text">播放视频后会自动显示可用的 M3U8 地址</div>
            </div>
        `;
    }

    function formatDuration(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return `${h}小时${m}分${s}秒`;
        if (m > 0) return `${m}分${s}秒`;
        return `${s}秒`;
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // 节流函数
    function throttle(fn, delay) {
        let lastCall = 0;
        return (...args) => {
            const now = Date.now();
            if (now - lastCall >= delay) {
                lastCall = now;
                fn(...args);
            }
        };
    }

    // ==================== M3U8 时长获取 ====================
    function parseM3U8Duration(content) {
        if (!content || typeof content !== 'string') return 0;
        let totalDuration = 0;

        for (const line of content.split('\n')) {
            const match = line.trim().match(/#EXTINF:([\d.]+)/);
            if (match) totalDuration += parseFloat(match[1]);
        }

        return totalDuration;
    }

    // 解析 M3U8 playlist，提取分辨率/码率变体
    function parseM3U8Playlist(content, baseUrl) {
        if (!content || typeof content !== 'string') return null;

        // 检查是否是 master playlist（包含多个流）
        if (!content.includes('#EXT-X-STREAM-INF')) {
            return null; // 不是 master playlist，是普通分片列表
        }

        const variants = [];
        const lines = content.split('\n');

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();

            // 解析 #EXT-X-STREAM-INF 行
            if (line.startsWith('#EXT-X-STREAM-INF:')) {
                const variant = {
                    url: null,
                    bandwidth: 0,
                    resolution: null,
                    codecs: null,
                    frameRate: null
                };

                // 提取属性
                const bandwidthMatch = line.match(/BANDWIDTH=(\d+)/);
                if (bandwidthMatch) variant.bandwidth = parseInt(bandwidthMatch[1]);

                const resolutionMatch = line.match(/RESOLUTION=([\d]+x[\d]+)/);
                if (resolutionMatch) variant.resolution = resolutionMatch[1];

                const codecsMatch = line.match(/CODECS="([^"]+)"/);
                if (codecsMatch) variant.codecs = codecsMatch[1];

                const frameRateMatch = line.match(/FRAME-RATE=([\d.]+)/);
                if (frameRateMatch) variant.frameRate = parseFloat(frameRateMatch[1]);

                // 下一行是 URL
                if (i + 1 < lines.length) {
                    const nextLine = lines[i + 1].trim();
                    if (nextLine && !nextLine.startsWith('#')) {
                        // 处理相对 URL
                        if (nextLine.startsWith('http')) {
                            variant.url = nextLine;
                        } else {
                            // 相对路径，拼接 baseUrl
                            const base = baseUrl.substring(0, baseUrl.lastIndexOf('/') + 1);
                            variant.url = base + nextLine;
                        }
                    }
                }

                if (variant.url) {
                    variants.push(variant);
                }
            }
        }

        return variants.length > 0 ? variants : null;
    }

    // 格式化码率为可读字符串
    function formatBandwidth(bps) {
        if (bps >= 1000000) {
            return `${(bps / 1000000).toFixed(1)} Mbps`;
        } else if (bps >= 1000) {
            return `${(bps / 1000).toFixed(0)} Kbps`;
        }
        return `${bps} bps`;
    }

    // 判断 URL 是否是 playlist 类型
    function isPlaylistUrl(url) {
        const urlLower = url.toLowerCase();
        return FILTER.PLAYLIST_MARKERS.some(m => urlLower.includes(m));
    }

    async function getM3U8Duration(url, content = null) {
        if (content) {
            const parsedDuration = parseM3U8Duration(content);
            if (parsedDuration > 0) {
                state.durationCache.set(url, parsedDuration);
            }
            return parsedDuration;
        }

        if (state.durationCache.has(url)) {
            return state.durationCache.get(url);
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), DURATION.FETCH_TIMEOUT_MS);

        try {
            const response = await fetch(url, { signal: controller.signal });
            const content = await response.text();
            const totalDuration = parseM3U8Duration(content);
            state.durationCache.set(url, totalDuration);
            return totalDuration;
        } catch (error) {
            log(`获取时长失败: ${error.message}`);
            return 0;
        } finally {
            clearTimeout(timeoutId);
        }
    }

    // ==================== 页面标题获取 ====================
    function getPageTitle(videoIndex = null) {
        for (const selector of SELECTORS.TITLE.split(', ')) {
            const el = document.querySelector(selector);
            if (el?.textContent.trim()) {
                let title = el.textContent.trim().replace(/[<>:"/\\|?*]/g, '_').substring(0, 50);
                if (videoIndex !== null && currentSite.config.multiVideo) {
                    title = `${title}_${videoIndex}`;
                }
                return title;
            }
        }
        return document.title.replace(/[<>:"/\\|?*]/g, '_').substring(0, 50);
    }

    // ==================== URL 过滤 ====================
    const isAdUrl = (url) => FILTER.AD_KEYWORDS.some(kw => url.toLowerCase().includes(kw));
    const isTargetUrl = (url) => FILTER.TARGET_MARKERS.some(m => url.toLowerCase().includes(m));

    // ==================== 面板管理 ====================
    function createResultPanel() {
        const panel = document.createElement('div');
        panel.id = 'm3u8-result-panel';
        panel.innerHTML = `
            <style>
                #m3u8-result-panel {
                    position: fixed; top: 20px; right: 20px;
                    width: 420px; height: min(720px, calc(100vh - 40px));
                    background: #ffffff; border: 1px solid rgba(15, 23, 42, 0.08); border-radius: 14px;
                    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
                    z-index: 999999; font-family: "Segoe UI", Arial, sans-serif;
                    overflow: hidden; transition: all 0.3s ease;
                    color: #0f172a;
                    backdrop-filter: blur(10px);
                }
                #m3u8-result-panel.minimized {
                    width: 58px; height: 58px; max-height: 58px;
                    border-radius: 18px; cursor: pointer;
                }
                #m3u8-panel-header {
                    background: linear-gradient(135deg, #0f766e 0%, #0f9f8f 100%);
                    color: white;
                    padding: 14px 16px 12px;
                    display: flex; justify-content: space-between; align-items: center;
                }
                #m3u8-panel-title {
                    display: flex; flex-direction: column; gap: 3px;
                }
                #m3u8-panel-title strong {
                    font-size: 15px; font-weight: 700; letter-spacing: 0;
                }
                #m3u8-panel-title span {
                    font-size: 12px; color: rgba(255,255,255,0.82);
                }
                .panel-btn {
                    width: 30px; height: 30px; border-radius: 9px;
                    display: inline-flex; align-items: center; justify-content: center;
                    cursor: pointer; font-size: 18px; color: white; margin-left: 6px;
                    background: rgba(255,255,255,0.14);
                    transition: background 0.2s ease;
                    user-select: none;
                }
                .panel-btn:hover { background: rgba(255,255,255,0.24); }
                #m3u8-panel-body {
                    display: flex; flex-direction: column; height: calc(100% - 66px);
                    background: #f8fafc;
                }
                #m3u8-status {
                    margin: 12px 12px 10px; padding: 10px 12px; background: #ecfeff;
                    border: 1px solid #bae6fd; border-radius: 10px; font-size: 13px; color: #0f766e;
                }
                #m3u8-panel-main {
                    display: grid; grid-template-rows: minmax(180px, 1fr) 140px;
                    gap: 10px; padding: 0 12px 12px; min-height: 0; flex: 1;
                }
                .panel-section {
                    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
                    min-height: 0; overflow: hidden;
                }
                .panel-section-header {
                    display: flex; justify-content: space-between; align-items: center;
                    padding: 12px 14px 10px; border-bottom: 1px solid #eef2f7;
                    background: #fcfdff;
                }
                .panel-section-title {
                    font-size: 13px; font-weight: 700; color: #0f172a;
                }
                .panel-section-meta {
                    font-size: 11px; color: #64748b;
                }
                .panel-section-body {
                    padding: 10px 12px 12px; overflow-y: auto; max-height: 100%;
                }
                .panel-section-body::-webkit-scrollbar {
                    width: 8px;
                }
                .panel-section-body::-webkit-scrollbar-thumb {
                    background: #cbd5e1; border-radius: 999px;
                }
                .m3u8-url-item {
                    background: #f8fafc; padding: 12px; margin: 0 0 10px;
                    border-radius: 10px; border: 1px solid #dbe4ee;
                    word-break: break-all;
                }
                .m3u8-url-item.target {
                    background: #fff7ed; border-color: #fdba74;
                }
                .m3u8-url-item.playlist {
                    background: #f0fdf4; border-color: #86efac;
                }
                .result-head {
                    display: flex; align-items: center; justify-content: space-between; gap: 10px;
                    margin-bottom: 8px;
                }
                .result-type {
                    font-size: 13px; font-weight: 700; color: #0f172a;
                }
                .result-file {
                    font-size: 12px; color: #475569; margin-bottom: 6px;
                }
                .result-url {
                    font-size: 11px; line-height: 1.5; color: #64748b;
                    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;
                    padding: 8px 9px;
                }
                .result-actions {
                    display: flex; gap: 8px; margin-top: 10px;
                }
                .result-actions button,
                .panel-controls button {
                    border: none; border-radius: 9px; cursor: pointer;
                    font-size: 12px; font-weight: 600; transition: all 0.2s ease;
                }
                .result-actions button {
                    padding: 8px 11px; background: #0f766e; color: white;
                }
                .result-actions button:hover { background: #115e59; }
                .result-actions .open-btn { background: #ea580c; }
                .result-actions .open-btn:hover { background: #c2410c; }
                .duration-badge {
                    display: inline-flex; align-items: center;
                    background: #dbeafe; color: #1d4ed8;
                    padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 700;
                }
                .playlist-badge {
                    display: inline-flex; align-items: center;
                    background: #dcfce7; color: #15803d;
                    padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 700;
                }
                /* 分辨率选择器样式 */
                .variant-list {
                    margin-top: 10px; border-top: 1px solid #e2e8f0;
                    padding-top: 10px;
                }
                .variant-title {
                    font-size: 12px; font-weight: 700; color: #0f172a;
                    margin-bottom: 8px;
                }
                .variant-item {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 10px; margin-bottom: 6px;
                    background: #ffffff; border: 1px solid #e2e8f0;
                    border-radius: 8px; cursor: pointer;
                    transition: all 0.2s ease;
                }
                .variant-item:hover {
                    border-color: #0f766e; background: #f0fdfa;
                }
                .variant-info {
                    display: flex; flex-direction: column; gap: 2px;
                }
                .variant-resolution {
                    font-size: 13px; font-weight: 700; color: #0f172a;
                }
                .variant-meta {
                    font-size: 11px; color: #64748b;
                }
                .variant-copy-btn {
                    padding: 6px 10px; background: #0f766e; color: white;
                    border: none; border-radius: 6px; font-size: 11px;
                    font-weight: 600; cursor: pointer;
                }
                .variant-copy-btn:hover { background: #115e59; }
                .log-item {
                    font-size: 12px; color: #475569; margin: 0 0 8px;
                    padding: 8px 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px;
                    line-height: 1.45;
                }
                #m3u8-minimized-icon {
                    display: none; width: 58px; height: 58px;
                    background: linear-gradient(135deg, #0f766e 0%, #0f9f8f 100%);
                    border-radius: 18px;
                    align-items: center; justify-content: center;
                    font-size: 24px; color: white; cursor: pointer;
                    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
                }
                #m3u8-minimized-icon.show { display: flex; }
                .panel-controls {
                    display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
                    padding: 0 12px 12px;
                }
                .panel-controls button {
                    padding: 10px 12px; background: #e2e8f0; color: #0f172a;
                }
                .panel-controls button:hover { background: #cbd5e1; }
                .panel-controls button.resniff { background: #0f766e; color: white; }
                .panel-controls button.resniff:hover { background: #115e59; }
                .empty-state {
                    display: flex; flex-direction: column; align-items: center; justify-content: center;
                    text-align: center; min-height: 150px; color: #64748b; padding: 20px 12px;
                }
                .empty-state-icon {
                    width: 42px; height: 42px; border-radius: 14px; background: #e2e8f0;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 20px; color: #334155; margin-bottom: 10px;
                }
                .empty-state-title {
                    font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 4px;
                }
                .empty-state-text {
                    font-size: 12px; line-height: 1.5;
                }
            </style>
            <div id="m3u8-minimized-icon" title="点击展开">🐱</div>
            <div id="m3u8-panel-full">
                <div id="m3u8-panel-header">
                    <div id="m3u8-panel-title">
                        <strong>猫抓助手 v2.0</strong>
                        <span>支持多链接和分辨率选择</span>
                    </div>
                    <div>
                        <span id="m3u8-panel-minimize" class="panel-btn" title="最小化">−</span>
                        <span id="m3u8-panel-close" class="panel-btn" title="关闭">×</span>
                    </div>
                </div>
                <div id="m3u8-panel-body">
                    <div id="m3u8-status">正在监控...</div>
                    <div id="m3u8-panel-main">
                        <section class="panel-section">
                            <div class="panel-section-header">
                                <span class="panel-section-title">捕获结果</span>
                                <span class="panel-section-meta">最新结果优先显示</span>
                            </div>
                            <div id="m3u8-result-list" class="panel-section-body"></div>
                        </section>
                        <section class="panel-section">
                            <div class="panel-section-header">
                                <span class="panel-section-title">运行日志</span>
                                <span class="panel-section-meta">保留最近 60 条</span>
                            </div>
                            <div id="m3u8-log-list" class="panel-section-body"></div>
                        </section>
                    </div>
                    <div class="panel-controls">
                        <button id="m3u8-resniff-btn" class="resniff">重新嗅探</button>
                        <button id="m3u8-clear-btn">清空列表</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(panel);
        state.panelElement = panel;
        renderEmptyResults();

        // 事件绑定
        document.getElementById('m3u8-panel-close').onclick = () => panel.style.display = 'none';
        document.getElementById('m3u8-panel-minimize').onclick = minimizePanel;
        document.getElementById('m3u8-minimized-icon').onclick = expandPanel;
        document.getElementById('m3u8-resniff-btn').onclick = resniff;
        document.getElementById('m3u8-clear-btn').onclick = clearResults;

        return panel;
    }

    function minimizePanel() {
        if (!state.panelElement) return;
        state.isMinimized = true;
        state.panelElement.classList.add('minimized');
        document.getElementById('m3u8-panel-full').style.display = 'none';
        document.getElementById('m3u8-minimized-icon').classList.add('show');
        addLog('面板已最小化');
    }

    function expandPanel() {
        if (!state.panelElement) return;
        state.isMinimized = false;
        state.panelElement.classList.remove('minimized');
        document.getElementById('m3u8-panel-full').style.display = 'block';
        document.getElementById('m3u8-minimized-icon').classList.remove('show');
    }

    function updateStatus(message) {
        const el = document.getElementById('m3u8-status');
        if (el) el.textContent = message;
        log(message);
    }

    function addLog(message) {
        const contentEl = document.getElementById('m3u8-log-list');
        if (!contentEl) { log(message); return; }
        const logItem = document.createElement('div');
        logItem.className = 'log-item';
        logItem.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        contentEl.insertBefore(logItem, contentEl.firstChild);
        trimContainerChildren(contentEl, '.log-item', DURATION.MAX_LOG_ITEMS);
    }

    async function addUrlToPanel(url, isTarget = false, duration = 0, variants = null) {
        const contentEl = document.getElementById('m3u8-result-list');
        if (!contentEl) return;
        const emptyState = contentEl.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        const item = document.createElement('div');
        const isPlaylist = variants && variants.length > 0;
        item.className = `m3u8-url-item ${isTarget ? 'target' : ''} ${isPlaylist ? 'playlist' : ''}`;

        const urlName = url.split('/').pop().split('?')[0];
        const durationStr = formatDuration(duration);

        const urlType = isTarget ? '目标链接' : (isPlaylist ? '播放列表' : '视频链接');
        const durationBadge = duration > 0
            ? `<span class="duration-badge">${durationStr}</span>`
            : '<span class="duration-badge" style="background:#e2e8f0;color:#475569">未知时长</span>';

        const playlistBadge = isPlaylist
            ? `<span class="playlist-badge">${variants.length}个分辨率</span>`
            : '';

        // 构建分辨率选择列表
        let variantListHtml = '';
        if (isPlaylist) {
            // 按带宽降序排列
            const sortedVariants = [...variants].sort((a, b) => b.bandwidth - a.bandwidth);

            variantListHtml = `
                <div class="variant-list">
                    <div class="variant-title">选择分辨率：</div>
                    ${sortedVariants.map((v, idx) => {
                        const resolution = v.resolution || '未知';
                        const bandwidth = formatBandwidth(v.bandwidth);
                        const frameRate = v.frameRate ? `${v.frameRate}fps` : '';
                        const meta = [bandwidth, frameRate].filter(Boolean).join(' · ');

                        return `
                            <div class="variant-item" data-url="${escapeHtml(v.url)}">
                                <div class="variant-info">
                                    <span class="variant-resolution">${resolution}</span>
                                    <span class="variant-meta">${meta}</span>
                                </div>
                                <button class="variant-copy-btn">复制</button>
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        }

        item.innerHTML = `
            <div class="result-head">
                <span class="result-type">${isTarget ? '◎' : (isPlaylist ? '☰' : '●')} ${urlType}</span>
                <div>${durationBadge}${playlistBadge}</div>
            </div>
            <div class="result-file">${escapeHtml(urlName)}</div>
            <div class="result-url">${escapeHtml(url.substring(0, 220))}${url.length > 220 ? '...' : ''}</div>
            ${variantListHtml}
            <div class="result-actions">
                <button class="copy-btn" data-url="${escapeHtml(url)}">复制链接</button>
                ${isTarget ? '<button class="open-btn">打开链接</button>' : ''}
            </div>
        `;

        item.querySelector('.copy-btn').onclick = () => copyUrlWithInfo(url, duration);

        // 绑定分辨率复制按钮事件
        if (isPlaylist) {
            item.querySelectorAll('.variant-item').forEach(variantItem => {
                const variantUrl = variantItem.dataset.url;
                const copyBtn = variantItem.querySelector('.variant-copy-btn');

                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    copyUrlWithInfo(variantUrl, 0);
                };

                // 点击整行也复制
                variantItem.onclick = () => copyUrlWithInfo(variantUrl, 0);
            });
        }

        if (isTarget) {
            item.querySelector('.open-btn')?.addEventListener('click', () => {
                state.allowOpenOnce = true;
                window.open(url, '_blank', 'noopener,noreferrer');
            });
        }

        contentEl.insertBefore(item, contentEl.firstChild);
        trimContainerChildren(contentEl, '.m3u8-url-item', DURATION.MAX_RESULT_ITEMS);
    }

    function buildRequestHeaders(url, headers = {}) {
        const normalized = {};
        for (const [key, value] of Object.entries(headers || {})) {
            if (key && value) {
                normalized[String(key).toLowerCase()] = String(value);
            }
        }

        const pageUrl = window.location.href;
        const pageOrigin = window.location.origin;
        if (!normalized.origin) normalized.origin = pageOrigin;
        if (!normalized.referer) normalized.referer = pageUrl;

        state.requestHeaders.set(url, normalized);
        return normalized;
    }

    function extractFetchHeaders(inputHeaders) {
        if (!inputHeaders) return {};

        if (inputHeaders instanceof Headers) {
            return Object.fromEntries(inputHeaders.entries());
        }

        if (Array.isArray(inputHeaders)) {
            return Object.fromEntries(inputHeaders);
        }

        if (typeof inputHeaders === 'object') {
            return { ...inputHeaders };
        }

        return {};
    }

    function copyUrlWithInfo(url, duration) {
        const title = getPageTitle(currentSite.config.multiVideo ? state.videoCounter : null);
        const headers = buildRequestHeaders(url, state.requestHeaders.get(url));
        const headersJson = JSON.stringify(headers);
        const text = `${url}|${title}|${headersJson}`;
        navigator.clipboard.writeText(text).then(() => {
            alert(`已复制！\n\n文件名: ${title}\n请求头: ${headersJson}\n链接: ${url.substring(0, 50)}...`);
            addLog('已复制: ' + title);
        }).catch(() => alert('复制失败，请手动复制'));
    }

    async function resniff() {
        addLog('开始重新嗅探...');
        updateStatus('正在重新嗅探...');
        state.capturedUrls.clear();
        state.pendingUrls.clear();
        state.durationCache.clear();
        state.requestHeaders.clear();
        state.playlistVariants.clear();
        state.videoCounter = 0;
        renderEmptyResults();

        if (config.autoClickPlay) {
            const playClicked = await clickPlayButton();
            if (playClicked && config.autoSkipAd) await clickSkipAdButton();
        }
    }

    function clearResults() {
        state.capturedUrls.clear();
        state.pendingUrls.clear();
        state.durationCache.clear();
        state.requestHeaders.clear();
        state.playlistVariants.clear();
        renderEmptyResults();
        addLog('已清空列表');
    }

    // ==================== 广告拦截 ====================
    function blockAdRedirects() {
        // 拦截 window.open
        const originalOpen = window.open;
        window.open = (url) => {
            if (state.allowOpenOnce) {
                state.allowOpenOnce = false;
                return originalOpen.call(window, url, '_blank', 'noopener,noreferrer');
            }
            log(`拦截 window.open: ${url}`);
            setTimeout(() => addLog('拦截广告弹窗: ' + url?.substring(0, 50)), 0);
            return null;
        };

        // URL 变化监控
        setInterval(() => {
            if (state.isJumpingBack) return;
            if (window.location.hostname !== state.originalDomain) {
                log('检测到跨域跳转: ' + window.location.href);
                setTimeout(() => addLog('检测到广告跳转，已阻止'), 0);
                state.isJumpingBack = true;
                window.history.back();
                setTimeout(() => {
                    if (window.location.hostname !== state.originalDomain) {
                        window.location.href = state.originalURL;
                    }
                    state.isJumpingBack = false;
                }, 100);
            }
        }, DURATION.URL_CHECK_MS);

        // 拦截 document.write
        const originalWrite = document.write;
        document.write = function(content) {
            if (content?.includes('<iframe') || content?.includes('window.location') || content?.includes('document.location')) {
                log('拦截 document.write (包含广告内容)');
                setTimeout(() => addLog('拦截广告写入'), 0);
                return;
            }
            return originalWrite.apply(document, arguments);
        };

        // 点击事件拦截
        document.addEventListener('click', (e) => {
            let target = e.target;
            while (target && target.tagName !== 'A') target = target.parentElement;
            if (target?.tagName === 'A') {
                const href = target.getAttribute('href');
                if (href && !href.startsWith('javascript:')) {
                    try {
                        const targetDomain = new URL(href, window.location.href).hostname;
                        if (targetDomain !== state.originalDomain) {
                            log('拦截广告链接点击: ' + href);
                            setTimeout(() => addLog('拦截广告链接: ' + href.substring(0, 50)), 0);
                            e.preventDefault();
                            e.stopPropagation();
                        }
                    } catch {}
                }
            }
        }, true);

        log('广告拦截已启用');
    }

    // ==================== 网络请求拦截 ====================
    function interceptNetworkRequests() {
        const originalXHRSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
        XMLHttpRequest.prototype.setRequestHeader = function(key, value) {
            if (!this._m3u8RequestHeaders) this._m3u8RequestHeaders = {};
            this._m3u8RequestHeaders[key] = value;
            return originalXHRSetRequestHeader.apply(this, arguments);
        };

        const originalXHROpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this.addEventListener('load', () => {
                const responseText = typeof this.responseText === 'string' ? this.responseText : null;
                handleUrl(url, {
                    responseText,
                    requestHeaders: this._m3u8RequestHeaders || {}
                });
            });
            return originalXHROpen.apply(this, arguments);
        };

        const originalFetch = window.fetch;
        window.fetch = function(url, options) {
            const requestHeaders = extractFetchHeaders(options?.headers);
            return originalFetch.apply(this, arguments).then(response => {
                const urlStr = url?.toString?.() || '';
                if (urlStr.includes('.m3u8')) {
                    response.clone().text()
                        .then(text => handleUrl(url, { responseText: text, requestHeaders }))
                        .catch(() => handleUrl(url, { requestHeaders }));
                } else {
                    handleUrl(url, { requestHeaders });
                }
                return response;
            });
        };

        log('网络请求拦截已启用');
    }

    async function handleUrl(url, options = {}) {
        if (!url) return;
        const urlStr = url.toString();
        const responseText = options.responseText || null;
        buildRequestHeaders(urlStr, options.requestHeaders || {});

        const shouldCapture = currentSite.config.useIndexFilter
            ? urlStr.includes('.m3u8') || urlStr.includes('.jpg') || urlStr.includes('index')
            : urlStr.includes('.m3u8');

        if (!shouldCapture || state.capturedUrls.has(urlStr) || state.pendingUrls.has(urlStr)) {
            return;
        }

        state.pendingUrls.add(urlStr);

        try {
            // 获取 m3u8 内容
            let m3u8Content = responseText;
            if (!m3u8Content) {
                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), DURATION.FETCH_TIMEOUT_MS);
                    const response = await fetch(urlStr, { signal: controller.signal });
                    m3u8Content = await response.text();
                    clearTimeout(timeoutId);
                } catch (e) {
                    log(`获取M3U8内容失败: ${e.message}`);
                }
            }

            // 检查是否是 master playlist
            const variants = parseM3U8Playlist(m3u8Content, urlStr);

            if (variants && variants.length > 0) {
                // 是 master playlist，存储变体信息
                state.playlistVariants.set(urlStr, variants);
                state.capturedUrls.add(urlStr);

                if (currentSite.config.multiVideo) {
                    state.videoCounter++;
                }

                updateStatus('✅ 已找到播放列表！');
                await addUrlToPanel(urlStr, false, 0, variants);
                addLog(`找到播放列表: ${urlStr.substring(0, 50)}... (${variants.length}个分辨率)`);
                return;
            }

            // 普通 m3u8，计算时长
            const duration = await getM3U8Duration(urlStr, m3u8Content);
            const isShort = duration > 0 && duration < config.minDuration;
            const isZero = duration === 0;

            if (isZero || isShort) {
                log(`过滤链接: ${urlStr.substring(0, 50)}... (时长: ${formatDuration(duration)})`);
                return;
            }

            state.capturedUrls.add(urlStr);

            if (currentSite.config.multiVideo && urlStr.includes('.m3u8')) {
                state.videoCounter++;
            }

            if (isTargetUrl(urlStr)) {
                updateStatus('✅ 已找到目标链接！');
                await addUrlToPanel(urlStr, true, duration);
                addLog(`找到目标链接: ${urlStr.substring(0, 50)}... (时长: ${formatDuration(duration)})`);
            } else if (!isAdUrl(urlStr)) {
                await addUrlToPanel(urlStr, false, duration);
                const label = currentSite.config.multiVideo ? `视频${state.videoCounter}: ` : '';
                addLog(`捕获${label}链接: ${urlStr.substring(0, 50)}... (时长: ${formatDuration(duration)})`);
            }
        } finally {
            state.pendingUrls.delete(urlStr);
        }
    }

    // ==================== 播放按钮点击 ====================
    async function clickPlayButton() {
        updateStatus('正在查找播放按钮...');

        for (let retry = 0; retry < RETRY.TIMES; retry++) {
            log(`第 ${retry + 1} 次尝试查找播放按钮`);

            // 查找 SVG 播放图标
            for (const path of document.querySelectorAll(SELECTORS.PLAY_SVG_PATH)) {
                const svg = path.closest('svg');
                if (!svg) continue;

                for (const parent of [svg.parentElement, svg.parentElement?.parentElement]) {
                    if (!parent) continue;
                    const style = window.getComputedStyle(parent);
                    if (style.borderRadius === '50%' || style.cursor === 'pointer' || parent.tagName === 'BUTTON') {
                        parent.click();
                        updateStatus('✅ 已点击播放按钮');
                        addLog(`已点击播放按钮（${parent.tagName}）`);
                        return true;
                    }
                }
            }

            // 查找圆形播放按钮
            for (const div of document.querySelectorAll('div')) {
                const style = window.getComputedStyle(div);
                if (style.borderRadius === '50%' && style.display === 'flex' &&
                    div.querySelector(SELECTORS.PLAY_SVG_PATH)) {
                    div.click();
                    updateStatus('✅ 已点击播放按钮');
                    addLog('已点击播放按钮（圆形div）');
                    return true;
                }
            }

            if (retry < RETRY.TIMES - 1) await sleep(DURATION.RETRY_INTERVAL_MS);
        }

        updateStatus('⚠️ 未找到播放按钮');
        addLog('未找到播放按钮，请手动点击播放');
        return false;
    }

    // ==================== 跳过广告 ====================
    async function clickSkipAdButton() {
        updateStatus('等待广告播放...');
        addLog('等待广告播放...');
        await sleep(DURATION.AD_WAIT_MS);
        updateStatus('正在查找跳过广告按钮...');

        const skipPatterns = ['跳', 'Skip', 'skip'];

        for (let retry = 0; retry < RETRY.TIMES; retry++) {
            log(`第 ${retry + 1} 次尝试查找跳过广告按钮`);

            // XPath 查找
            for (const pattern of skipPatterns) {
                try {
                    const result = document.evaluate(
                        `//button[contains(text(), '${pattern}')]`,
                        document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    );
                    const button = result.singleNodeValue;
                    if (button?.offsetParent !== null) {
                        button.click();
                        updateStatus('✅ 已点击跳过广告按钮');
                        addLog(`已点击跳过广告按钮: ${button.textContent}`);
                        return true;
                    }
                } catch {}
            }

            // 遍历按钮
            for (const button of document.querySelectorAll('button')) {
                const text = button.textContent || '';
                if (skipPatterns.some(p => text.includes(p)) && button.offsetParent !== null) {
                    button.click();
                    updateStatus('✅ 已点击跳过广告按钮');
                    addLog(`已点击跳过广告按钮: ${text}`);
                    return true;
                }
            }

            if (retry < RETRY.TIMES - 1) await sleep(DURATION.RETRY_INTERVAL_MS);
        }

        updateStatus('⚠️ 未找到跳过广告按钮');
        addLog('未找到跳过广告按钮，请手动点击');
        return false;
    }

    // ==================== 主流程 ====================
    async function main() {
        log('脚本已加载 v2.0');
        blockAdRedirects();

        if (document.readyState === 'loading') {
            await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve));
        }

        if (config.showResult) {
            createResultPanel();
            addLog('脚本已加载 v2.0');
            addLog(`当前网站: ${currentSite.name}`);
            addLog(`最小时长过滤: ${config.minDuration}秒`);
            addLog('支持多链接和分辨率选择');
            if (currentSite.config.multiVideo) addLog('多视频模式: 已启用');
        }

        addLog('广告拦截已启用');
        interceptNetworkRequests();
        addLog('网络请求拦截已启用');

        await sleep(DURATION.INIT_DELAY_MS);

        if (config.autoClickPlay) {
            const playClicked = await clickPlayButton();
            if (playClicked && config.autoSkipAd) await clickSkipAdButton();
        } else {
            updateStatus('正在监控M3U8链接...');
            addLog('等待捕获M3U8链接...');
        }
    }

    main();
})();
