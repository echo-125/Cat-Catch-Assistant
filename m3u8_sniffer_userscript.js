// ==UserScript==
// @name         猫抓助手
// @namespace    http://tampermonkey.net/
// @version      1.6
// @description  自动点击播放按钮、跳过广告，拦截广告跳转，并提取M3U8视频链接（带时长检测）
// @author       Claude Code
// @match        https://rouva4.xyz/*
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
        AD_WAIT_MS: 6000,
        RETRY_INTERVAL_MS: 1000,
        URL_CHECK_MS: 100,
        IFRAME_CLEAN_MS: 2000,
        INIT_DELAY_MS: 2000,
        FETCH_TIMEOUT_MS: 10000
    };

    const RETRY = { TIMES: 3 };

    const FILTER = {
        AD_KEYWORDS: ['ad', 'ads', 'adv', 'advertisement', 'silent-basis'],
        TARGET_MARKERS: ['index.jpg', 'index.m3u8']
    };

    // ==================== 网站配置 ====================
    const SITE_CONFIGS = {
        'rouva4.xyz': {
            needsPlayClick: true,
            needsAdSkip: true,
            useIndexFilter: true,
            multiVideo: false
        }
    };

    // ==================== 状态管理 ====================
    const state = {
        capturedUrls: new Set(),
        isMinimized: false,
        panelElement: null,
        videoCounter: 0,
        isJumpingBack: false,
        originalDomain: window.location.hostname,
        originalURL: window.location.href
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
        autoSkipAd: currentSite.config.needsAdSkip,
        showResult: true,
        minDuration: DURATION.MIN_SECONDS
    };

    // ==================== 工具函数 ====================
    const log = (msg) => console.log(`[猫抓助手] ${msg}`);

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
    async function getM3U8Duration(url) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), DURATION.FETCH_TIMEOUT_MS);

        try {
            const response = await fetch(url, { signal: controller.signal });
            const content = await response.text();
            let totalDuration = 0;

            for (const line of content.split('\n')) {
                const match = line.trim().match(/#EXTINF:([\d.]+)/);
                if (match) totalDuration += parseFloat(match[1]);
            }
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
                    width: 500px; max-height: 600px;
                    background: white; border: 2px solid #4CAF50; border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    z-index: 999999; font-family: Arial, sans-serif;
                    overflow: hidden; transition: all 0.3s ease;
                }
                #m3u8-result-panel.minimized {
                    width: 60px; height: 60px; max-height: 60px;
                    border-radius: 50%; cursor: pointer;
                }
                #m3u8-panel-header {
                    background: #4CAF50; color: white;
                    padding: 12px; font-weight: bold;
                    display: flex; justify-content: space-between; align-items: center;
                }
                .panel-btn { cursor: pointer; font-size: 18px; color: white; margin-right: 10px; }
                #m3u8-panel-close { font-size: 20px; margin-right: 0; }
                #m3u8-panel-content { padding: 15px; max-height: 450px; overflow-y: auto; }
                .m3u8-url-item {
                    background: #f5f5f5; padding: 10px; margin: 8px 0;
                    border-radius: 4px; border-left: 3px solid #4CAF50;
                    word-break: break-all;
                }
                .m3u8-url-item.target { border-left-color: #FF5722; background: #fff3e0; }
                .m3u8-url-item.filtered { border-left-color: #999; background: #f0f0f0; opacity: 0.6; }
                .m3u8-url-item button {
                    background: #4CAF50; color: white; border: none;
                    padding: 5px 10px; border-radius: 3px; cursor: pointer;
                    margin-top: 5px; margin-right: 5px;
                }
                .m3u8-url-item button:hover { background: #45a049; }
                .duration-badge {
                    display: inline-block; background: #2196F3; color: white;
                    padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 5px;
                }
                #m3u8-status {
                    padding: 10px; background: #e3f2fd;
                    border-bottom: 1px solid #ddd; font-size: 14px;
                }
                .log-item {
                    font-size: 12px; color: #666; margin: 5px 0;
                    padding: 5px; background: #f9f9f9; border-radius: 3px;
                }
                #m3u8-minimized-icon {
                    display: none; width: 60px; height: 60px;
                    background: #4CAF50; border-radius: 50%;
                    align-items: center; justify-content: center;
                    font-size: 24px; color: white; cursor: pointer;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                }
                #m3u8-minimized-icon.show { display: flex; }
                .panel-controls {
                    display: flex; gap: 10px; margin-top: 10px;
                    padding: 10px; background: #f5f5f5; border-top: 1px solid #ddd;
                }
                .panel-controls button {
                    flex: 1; padding: 8px; background: #2196F3; color: white;
                    border: none; border-radius: 4px; cursor: pointer; font-size: 13px;
                }
                .panel-controls button:hover { background: #1976D2; }
                .panel-controls button.resniff { background: #FF5722; }
                .panel-controls button.resniff:hover { background: #E64A19; }
            </style>
            <div id="m3u8-minimized-icon" title="点击展开">🐱</div>
            <div id="m3u8-panel-full">
                <div id="m3u8-panel-header">
                    <span>猫抓助手 v1.6</span>
                    <div>
                        <span id="m3u8-panel-minimize" class="panel-btn" title="最小化">−</span>
                        <span id="m3u8-panel-close" class="panel-btn" title="关闭">×</span>
                    </div>
                </div>
                <div id="m3u8-status">正在监控...</div>
                <div id="m3u8-panel-content"><p>等待捕获链接...</p></div>
                <div class="panel-controls">
                    <button id="m3u8-resniff-btn" class="resniff">🔄 重新嗅探</button>
                    <button id="m3u8-clear-btn">🗑️ 清空列表</button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);
        state.panelElement = panel;

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
        const contentEl = document.getElementById('m3u8-panel-content');
        if (!contentEl) { log(message); return; }
        const logItem = document.createElement('div');
        logItem.className = 'log-item';
        logItem.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        contentEl.appendChild(logItem);
    }

    async function addUrlToPanel(url, isTarget = false, duration = 0) {
        const contentEl = document.getElementById('m3u8-panel-content');
        if (!contentEl) return;

        const item = document.createElement('div');
        item.className = `m3u8-url-item ${isTarget ? 'target' : ''}`;

        const urlName = url.split('/').pop().split('?')[0];
        const durationStr = formatDuration(duration);

        const urlType = isTarget ? '✅ 目标链接 (index.jpg)' : '📹 视频链接';
        const durationBadge = duration > 0
            ? `<span class="duration-badge">${durationStr}</span>`
            : '<span class="duration-badge" style="background:#999">未知时长</span>';

        item.innerHTML = `
            <div><strong>${urlType}</strong>${durationBadge}</div>
            <div style="font-size: 12px; color: #666; margin: 5px 0;">${urlName}</div>
            <div style="font-size: 11px; color: #999; word-break: break-all;">${url.substring(0, 150)}${url.length > 150 ? '...' : ''}</div>
            <button class="copy-btn" data-url="${url}">复制链接</button>
            ${isTarget ? '<button class="open-btn" style="background: #FF5722;">打开链接</button>' : ''}
        `;

        item.querySelector('.copy-btn').onclick = () => copyUrlWithInfo(url, duration);
        if (isTarget) {
            item.querySelector('.open-btn')?.addEventListener('click', () => window.open(url));
        }

        contentEl.insertBefore(item, contentEl.firstChild);
    }

    function copyUrlWithInfo(url, duration) {
        const title = getPageTitle(currentSite.config.multiVideo ? state.videoCounter : null);
        const text = `${url}|${title}`;
        navigator.clipboard.writeText(text).then(() => {
            alert(`已复制！\n\n文件名: ${title}\n链接: ${url.substring(0, 50)}...`);
            addLog('已复制: ' + title);
        }).catch(() => alert('复制失败，请手动复制'));
    }

    async function resniff() {
        addLog('开始重新嗅探...');
        updateStatus('正在重新嗅探...');
        state.capturedUrls.clear();
        const contentEl = document.getElementById('m3u8-panel-content');
        if (contentEl) contentEl.innerHTML = '<p>等待捕获链接...</p>';

        if (config.autoClickPlay) {
            const playClicked = await clickPlayButton();
            if (playClicked && config.autoSkipAd) await clickSkipAdButton();
        }
    }

    function clearResults() {
        state.capturedUrls.clear();
        const contentEl = document.getElementById('m3u8-panel-content');
        if (contentEl) contentEl.innerHTML = '<p>等待捕获链接...</p>';
        addLog('已清空列表');
    }

    // ==================== 广告拦截 ====================
    function blockAdRedirects() {
        // 拦截 window.open
        const originalOpen = window.open;
        window.open = (url) => {
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

        // 移除广告 iframe
        const removeAdIframes = throttle(() => {
            document.querySelectorAll(SELECTORS.IFRAME).forEach(iframe => {
                const src = iframe.getAttribute('src') || '';
                if (src && !src.includes(state.originalDomain) && !src.includes('about:blank')) {
                    iframe.remove();
                    setTimeout(() => addLog('移除广告 iframe'), 0);
                }
            });
        }, 500);

        removeAdIframes();
        setInterval(removeAdIframes, DURATION.IFRAME_CLEAN_MS);

        // MutationObserver
        new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        const src = node.getAttribute?.('src') || '';
                        if ((node.tagName === 'IFRAME' || node.tagName === 'SCRIPT') &&
                            src && !src.includes(state.originalDomain) && !src.includes('about:blank')) {
                            node.remove();
                            setTimeout(() => addLog('移除动态广告元素'), 0);
                        }
                    }
                }
            }
        }).observe(document.documentElement, { childList: true, subtree: true });

        log('广告拦截已启用');
    }

    // ==================== 网络请求拦截 ====================
    function interceptNetworkRequests() {
        const originalXHROpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this.addEventListener('load', () => handleUrl(url));
            return originalXHROpen.apply(this, arguments);
        };

        const originalFetch = window.fetch;
        window.fetch = function(url, options) {
            return originalFetch.apply(this, arguments).then(response => {
                handleUrl(url);
                return response;
            });
        };

        log('网络请求拦截已启用');
    }

    async function handleUrl(url) {
        if (!url) return;
        const urlStr = url.toString();

        const shouldCapture = currentSite.config.useIndexFilter
            ? urlStr.includes('.m3u8') || urlStr.includes('.jpg') || urlStr.includes('index')
            : urlStr.includes('.m3u8');

        if (shouldCapture && !state.capturedUrls.has(urlStr)) {
            // 先获取时长，过滤短视频
            const duration = await getM3U8Duration(url);
            const isShort = duration > 0 && duration < config.minDuration;
            const isZero = duration === 0;

            // 过滤：时长为0或过短的链接不显示
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
        addLog('未找到播放按钮，已最小化面板');
        setTimeout(minimizePanel, 1000);
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
        log('脚本已加载 v1.6');
        blockAdRedirects();

        if (document.readyState === 'loading') {
            await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve));
        }

        if (config.showResult) {
            createResultPanel();
            addLog('脚本已加载 v1.6');
            addLog(`当前网站: ${currentSite.name}`);
            addLog(`最小时长过滤: ${config.minDuration}秒`);
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
