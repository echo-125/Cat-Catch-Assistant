// ==UserScript==
// @name         猫抓助手
// @namespace    http://tampermonkey.net/
// @version      1.4
// @description  自动点击播放按钮、跳过广告，拦截广告跳转，并提取M3U8视频链接（带时长检测）
// @author       Claude Code
// @match        https://rouva4.xyz/*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    console.log('[猫抓助手] 脚本已加载 v1.4');

    // 配置
    const CONFIG = {
        autoClickPlay: true,        // 自动点击播放按钮
        autoSkipAd: true,           // 自动跳过广告
        adWaitTime: 6000,           // 广告等待时间（毫秒）
        showResult: true,           // 显示结果面板
        filterKeywords: ['ad', 'ads', 'adv', 'advertisement', 'silent-basis'], // 广告关键词
        minDuration: 90,            // 最小时长（秒），低于此值的视频将被过滤
        retryTimes: 3,              // 重试次数
        retryInterval: 1000,        // 重试间隔（毫秒）
    };

    // 存储捕获的链接
    let capturedUrls = new Set();

    // 面板状态
    let isMinimized = false;
    let panelElement = null;

    // 创建结果面板
    function createResultPanel() {
        const panel = document.createElement('div');
        panel.id = 'm3u8-result-panel';
        panel.innerHTML = `
            <style>
                #m3u8-result-panel {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    width: 500px;
                    max-height: 600px;
                    background: white;
                    border: 2px solid #4CAF50;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    z-index: 999999;
                    font-family: Arial, sans-serif;
                    overflow: hidden;
                    transition: all 0.3s ease;
                }
                #m3u8-result-panel.minimized {
                    width: 60px;
                    height: 60px;
                    max-height: 60px;
                    border-radius: 50%;
                    cursor: pointer;
                }
                #m3u8-panel-header {
                    background: #4CAF50;
                    color: white;
                    padding: 12px;
                    font-weight: bold;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                #m3u8-panel-close {
                    cursor: pointer;
                    font-size: 20px;
                    color: white;
                }
                #m3u8-panel-minimize {
                    cursor: pointer;
                    font-size: 18px;
                    color: white;
                    margin-right: 10px;
                }
                #m3u8-panel-content {
                    padding: 15px;
                    max-height: 450px;
                    overflow-y: auto;
                }
                .m3u8-url-item {
                    background: #f5f5f5;
                    padding: 10px;
                    margin: 8px 0;
                    border-radius: 4px;
                    border-left: 3px solid #4CAF50;
                    word-break: break-all;
                }
                .m3u8-url-item.target {
                    border-left-color: #FF5722;
                    background: #fff3e0;
                }
                .m3u8-url-item.filtered {
                    border-left-color: #999;
                    background: #f0f0f0;
                    opacity: 0.6;
                }
                .m3u8-url-item button {
                    background: #4CAF50;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 3px;
                    cursor: pointer;
                    margin-top: 5px;
                    margin-right: 5px;
                }
                .m3u8-url-item button:hover {
                    background: #45a049;
                }
                .duration-badge {
                    display: inline-block;
                    background: #2196F3;
                    color: white;
                    padding: 2px 8px;
                    border-radius: 12px;
                    font-size: 11px;
                    margin-left: 5px;
                }
                .duration-badge.short {
                    background: #ff9800;
                }
                #m3u8-status {
                    padding: 10px;
                    background: #e3f2fd;
                    border-bottom: 1px solid #ddd;
                    font-size: 14px;
                }
                .log-item {
                    font-size: 12px;
                    color: #666;
                    margin: 5px 0;
                    padding: 5px;
                    background: #f9f9f9;
                    border-radius: 3px;
                }
                #m3u8-minimized-icon {
                    display: none;
                    width: 60px;
                    height: 60px;
                    background: #4CAF50;
                    border-radius: 50%;
                    align-items: center;
                    justify-content: center;
                    font-size: 24px;
                    color: white;
                    cursor: pointer;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                }
                #m3u8-minimized-icon.show {
                    display: flex;
                }
                .panel-controls {
                    display: flex;
                    gap: 10px;
                    margin-top: 10px;
                    padding: 10px;
                    background: #f5f5f5;
                    border-top: 1px solid #ddd;
                }
                .panel-controls button {
                    flex: 1;
                    padding: 8px;
                    background: #2196F3;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 13px;
                }
                .panel-controls button:hover {
                    background: #1976D2;
                }
                .panel-controls button.resniff {
                    background: #FF5722;
                }
                .panel-controls button.resniff:hover {
                    background: #E64A19;
                }
            </style>
            <div id="m3u8-minimized-icon" title="点击展开">🐱</div>
            <div id="m3u8-panel-full">
                <div id="m3u8-panel-header">
                    <span>猫抓助手 v1.4</span>
                    <div>
                        <span id="m3u8-panel-minimize" title="最小化">−</span>
                        <span id="m3u8-panel-close" title="关闭">×</span>
                    </div>
                </div>
                <div id="m3u8-status">正在监控...</div>
                <div id="m3u8-panel-content">
                    <p>等待捕获链接...</p>
                </div>
                <div class="panel-controls">
                    <button id="m3u8-resniff-btn" class="resniff">🔄 重新嗅探</button>
                    <button id="m3u8-clear-btn">🗑️ 清空列表</button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);

        panelElement = panel;

        // 关闭按钮
        document.getElementById('m3u8-panel-close').onclick = () => {
            panel.style.display = 'none';
        };

        // 最小化按钮
        document.getElementById('m3u8-panel-minimize').onclick = () => {
            minimizePanel();
        };

        // 最小化图标点击展开
        document.getElementById('m3u8-minimized-icon').onclick = () => {
            expandPanel();
        };

        // 重新嗅探按钮
        document.getElementById('m3u8-resniff-btn').onclick = () => {
            resniff();
        };

        // 清空列表按钮
        document.getElementById('m3u8-clear-btn').onclick = () => {
            clearResults();
        };

        return panel;
    }

    // 最小化面板
    function minimizePanel() {
        if (!panelElement) return;

        isMinimized = true;
        panelElement.classList.add('minimized');
        document.getElementById('m3u8-panel-full').style.display = 'none';
        document.getElementById('m3u8-minimized-icon').classList.add('show');

        addLog('面板已最小化');
    }

    // 展开面板
    function expandPanel() {
        if (!panelElement) return;

        isMinimized = false;
        panelElement.classList.remove('minimized');
        document.getElementById('m3u8-panel-full').style.display = 'block';
        document.getElementById('m3u8-minimized-icon').classList.remove('show');
    }

    // 重新嗅探
    async function resniff() {
        addLog('开始重新嗅探...');
        updateStatus('正在重新嗅探...');

        // 清空之前的链接
        capturedUrls.clear();

        // 清空面板内容
        const contentEl = document.getElementById('m3u8-panel-content');
        if (contentEl) {
            contentEl.innerHTML = '<p>等待捕获链接...</p>';
        }

        // 重新执行主流程
        if (CONFIG.autoClickPlay) {
            const playClicked = await clickPlayButton();

            if (playClicked && CONFIG.autoSkipAd) {
                await clickSkipAdButton();
            }
        }
    }

    // 清空结果
    function clearResults() {
        capturedUrls.clear();
        const contentEl = document.getElementById('m3u8-panel-content');
        if (contentEl) {
            contentEl.innerHTML = '<p>等待捕获链接...</p>';
        }
        addLog('已清空列表');
    }

    // 更新状态
    function updateStatus(message) {
        const statusEl = document.getElementById('m3u8-status');
        if (statusEl) {
            statusEl.textContent = message;
        }
        console.log('[猫抓助手]', message);
    }

    // 添加日志
    function addLog(message) {
        const contentEl = document.getElementById('m3u8-panel-content');
        if (!contentEl) {
            // 面板还未创建，只输出到控制台
            console.log('[猫抓助手]', message);
            return;
        }

        const logItem = document.createElement('div');
        logItem.className = 'log-item';
        logItem.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        contentEl.appendChild(logItem);
    }

    // 格式化时长
    function formatDuration(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);

        if (h > 0) {
            return `${h}小时${m}分${s}秒`;
        } else if (m > 0) {
            return `${m}分${s}秒`;
        } else {
            return `${s}秒`;
        }
    }

    // 获取M3U8视频时长
    async function getM3U8Duration(url) {
        try {
            const response = await fetch(url);
            const content = await response.text();

            let totalDuration = 0;
            const lines = content.split('\n');

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i].trim();

                // 查找 #EXTINF 标签
                if (line.startsWith('#EXTINF:')) {
                    const match = line.match(/#EXTINF:([\d.]+)/);
                    if (match) {
                        totalDuration += parseFloat(match[1]);
                    }
                }
            }

            return totalDuration;
        } catch (error) {
            console.error('获取时长失败:', error);
            return 0;
        }
    }

    // 获取网页标题
    function getPageTitle() {
        // 尝试多种方式获取标题
        const titleSelectors = [
            'h1',
            'title',
            '[class*="title"]',
            '[class*="video-title"]'
        ];

        for (const selector of titleSelectors) {
            const element = document.querySelector(selector);
            if (element && element.textContent.trim()) {
                // 清理标题（移除特殊字符）
                return element.textContent.trim()
                    .replace(/[<>:"/\\|?*]/g, '_')
                    .substring(0, 50); // 限制长度
            }
        }

        // 使用页面标题
        return document.title
            .replace(/[<>:"/\\|?*]/g, '_')
            .substring(0, 50);
    }

    // 添加URL到结果面板
    async function addUrlToPanel(url, isTarget = false) {
        const contentEl = document.getElementById('m3u8-panel-content');
        if (!contentEl) return;

        const item = document.createElement('div');
        item.className = `m3u8-url-item ${isTarget ? 'target' : ''}`;

        const urlName = url.split('/').pop().split('?')[0];

        // 获取时长
        const duration = await getM3U8Duration(url);
        const durationStr = formatDuration(duration);
        const isShort = duration > 0 && duration < CONFIG.minDuration;

        // 更新样式
        if (isShort) {
            item.classList.add('filtered');
        }

        const urlType = isTarget ? '✅ 目标链接 (index.jpg)' : '📹 视频链接';
        const durationBadge = duration > 0
            ? `<span class="duration-badge ${isShort ? 'short' : ''}">${durationStr}</span>`
            : '<span class="duration-badge" style="background:#999">未知时长</span>';

        const filterNote = isShort
            ? `<div style="color: #ff9800; font-size: 11px; margin-top: 3px;">⚠️ 时长不足${CONFIG.minDuration}秒，可能是广告</div>`
            : '';

        item.innerHTML = `
            <div><strong>${urlType}</strong>${durationBadge}</div>
            <div style="font-size: 12px; color: #666; margin: 5px 0;">${urlName}</div>
            <div style="font-size: 11px; color: #999; word-break: break-all;">${url.substring(0, 150)}${url.length > 150 ? '...' : ''}</div>
            ${filterNote}
            <button class="copy-btn" data-url="${url}">复制链接</button>
            ${isTarget && !isShort ? '<button class="open-btn" style="background: #FF5722;">打开链接</button>' : ''}
        `;

        // 添加事件监听
        item.querySelector('.copy-btn').onclick = function() {
            copyUrlWithInfo(url, duration);
        };

        if (isTarget && !isShort) {
            const openBtn = item.querySelector('.open-btn');
            if (openBtn) {
                openBtn.onclick = function() {
                    window.open(url);
                };
            }
        }

        contentEl.insertBefore(item, contentEl.firstChild);

        return { duration, isShort };
    }

    // 复制链接和文件名
    function copyUrlWithInfo(url, duration) {
        const title = getPageTitle();

        // 格式：URL|文件名（方便GUI批量导入）
        const text = `${url}|${title}`;

        navigator.clipboard.writeText(text).then(() => {
            alert(`已复制！\n\n文件名: ${title}\n链接: ${url.substring(0, 50)}...`);
            addLog('已复制: ' + title);
        }).catch(err => {
            console.error('复制失败:', err);
            alert('复制失败，请手动复制');
        });
    }

    // 检查是否为广告链接
    function isAdUrl(url) {
        const urlLower = url.toLowerCase();
        return CONFIG.filterKeywords.some(keyword => urlLower.includes(keyword));
    }

    // 检查是否为目标链接（index.jpg）
    function isTargetUrl(url) {
        const urlLower = url.toLowerCase();
        return urlLower.includes('index.jpg') || urlLower.includes('index.m3u8');
    }

    // 拦截广告跳转
    function blockAdRedirects() {
        // 保存原始 URL
        const originalURL = window.location.href;
        const originalDomain = window.location.hostname;

        // 1. 拦截 window.open（阻止弹窗）
        const originalWindowOpen = window.open;
        window.open = function(url, target, features) {
            console.log('[猫抓助手] 拦截 window.open:', url);
            setTimeout(() => addLog('拦截广告弹窗: ' + url.substring(0, 50)), 0);
            return null; // 返回 null 而不是打开新窗口
        };

        // 2. 使用定时器监控 URL 变化（核心功能：防止广告覆盖页面）
        let lastURL = window.location.href;
        let isJumpingBack = false; // 防止重复跳转

        setInterval(() => {
            if (isJumpingBack) return; // 正在跳回中，跳过检查

            const currentURL = window.location.href;
            const currentDomain = window.location.hostname;

            // 检测到跨域跳转
            if (currentDomain !== originalDomain) {
                console.log('[猫抓助手] 检测到跨域跳转:', currentURL);
                console.log('[猫抓助手] 正在阻止并跳回原页面...');
                setTimeout(() => addLog('检测到广告跳转，已阻止'), 0);

                isJumpingBack = true;

                // 立即跳回原页面
                try {
                    // 方法1: 使用 history.back() 返回
                    window.history.back();

                    // 方法2: 如果 history.back() 失败，100ms 后强制跳回
                    setTimeout(() => {
                        if (window.location.hostname !== originalDomain) {
                            console.log('[猫抓助手] history.back() 失败，强制跳回原 URL');
                            window.location.href = originalURL;
                        }
                        isJumpingBack = false;
                    }, 100);
                } catch (e) {
                    console.error('阻止跳转失败:', e);
                    isJumpingBack = false;
                }
            }

            lastURL = currentURL;
        }, 50); // 每 50ms 检查一次，更快响应

        // 3. 拦截 beforeunload 事件（阻止页面跳转）
        window.addEventListener('beforeunload', function(e) {
            // 检查是否有正在进行的视频播放
            const video = document.querySelector('video');
            if (video && !video.paused) {
                e.preventDefault();
                e.returnValue = '视频正在播放，确定要离开吗？';
                return e.returnValue;
            }
        });

        // 4. 拦截 document.write（防止覆盖整个页面）
        const originalDocumentWrite = document.write;
        document.write = function(content) {
            // 检查是否包含 iframe 或跳转脚本
            if (content && (
                content.includes('<iframe') ||
                content.includes('window.location') ||
                content.includes('document.location')
            )) {
                console.log('[猫抓助手] 拦截 document.write (包含广告内容)');
                setTimeout(() => addLog('拦截广告写入'), 0);
                return;
            }
            return originalDocumentWrite.apply(document, arguments);
        };

        // 5. 拦截所有点击事件，阻止广告链接跳转（捕获阶段，优先级最高）
        document.addEventListener('click', function(e) {
            let target = e.target;

            // 向上查找最近的 <a> 标签
            while (target && target.tagName !== 'A') {
                target = target.parentElement;
            }

            if (target && target.tagName === 'A') {
                const href = target.getAttribute('href');
                if (href) {
                    try {
                        const targetUrl = new URL(href, window.location.href);
                        const targetDomain = targetUrl.hostname;

                        // 如果是跨域链接，阻止跳转
                        if (targetDomain !== originalDomain) {
                            console.log('[猫抓助手] 拦截广告链接点击:', href);
                            setTimeout(() => addLog('拦截广告链接: ' + href.substring(0, 50)), 0);
                            e.preventDefault();
                            e.stopPropagation();
                            return false;
                        }
                    } catch (e) {
                        // URL 解析失败，可能是 javascript: 协议等
                        if (href.startsWith('javascript:')) {
                            // 允许 javascript: 协议的链接
                            return true;
                        }
                    }
                }
            }
        }, true);

        // 6. 移除页面上的广告 iframe
        const removeAdIframes = () => {
            const iframes = document.querySelectorAll('iframe');
            iframes.forEach(iframe => {
                try {
                    const src = iframe.getAttribute('src') || '';

                    // 检查是否是跨域 iframe
                    if (src && !src.includes(originalDomain) && !src.includes('about:blank')) {
                        console.log('[猫抓助手] 移除广告 iframe:', src);
                        iframe.remove();
                        setTimeout(() => addLog('移除广告 iframe'), 0);
                    }
                } catch (e) {
                    // 跨域访问限制，直接移除
                    iframe.remove();
                }
            });
        };

        // 立即执行一次
        removeAdIframes();

        // 定期检查并移除新出现的广告 iframe
        setInterval(removeAdIframes, 2000);

        // 7. 使用 MutationObserver 监控并移除广告元素
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // 检查是否是广告相关的元素
                        if (node.tagName === 'IFRAME' || node.tagName === 'SCRIPT') {
                            const src = node.getAttribute('src') || '';

                            if (src && !src.includes(originalDomain) && !src.includes('about:blank')) {
                                console.log('[猫抓助手] 移除动态加载的广告:', src);
                                node.remove();
                                setTimeout(() => addLog('移除动态广告元素'), 0);
                            }
                        }
                    }
                });
            });
        });

        // 开始监控整个文档
        observer.observe(document.documentElement || document.body, {
            childList: true,
            subtree: true
        });

        console.log('[猫抓助手] 广告拦截已启用');
    }

    // 监听网络请求
    function interceptNetworkRequests() {
        // 拦截 XMLHttpRequest
        const originalXHROpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this.addEventListener('load', function() {
                handleUrl(url);
            });
            return originalXHROpen.apply(this, arguments);
        };

        // 拦截 Fetch
        const originalFetch = window.fetch;
        window.fetch = function(url, options) {
            return originalFetch.apply(this, arguments).then(response => {
                handleUrl(url);
                return response;
            });
        };

        console.log('[猫抓助手] 网络请求拦截已启用');
    }

    // 处理URL
    async function handleUrl(url) {
        if (!url) return;

        const urlStr = url.toString();
        if (urlStr.includes('.m3u8') || urlStr.includes('.jpg') || urlStr.includes('index')) {
            if (!capturedUrls.has(urlStr)) {
                capturedUrls.add(urlStr);

                if (isTargetUrl(urlStr)) {
                    updateStatus('✅ 已找到目标链接！');
                    const result = await addUrlToPanel(urlStr, true);
                    addLog(`找到目标链接: ${urlStr.substring(0, 50)}... (时长: ${formatDuration(result.duration)})`);
                } else if (!isAdUrl(urlStr)) {
                    const result = await addUrlToPanel(urlStr, false);
                    if (result && !result.isShort) {
                        addLog(`捕获链接: ${urlStr.substring(0, 50)}... (时长: ${formatDuration(result.duration)})`);
                    } else if (result && result.isShort) {
                        addLog(`过滤短视频: ${urlStr.substring(0, 50)}... (${formatDuration(result.duration)})`);
                    }
                }
            }
        }
    }

    // 查找并点击播放按钮（带重试）
    async function clickPlayButton() {
        updateStatus('正在查找播放按钮...');

        for (let retry = 0; retry < CONFIG.retryTimes; retry++) {
            console.log(`[猫抓助手] 第 ${retry + 1} 次尝试查找播放按钮`);

            // 先尝试查找 SVG 播放图标
            const svgPaths = document.querySelectorAll('svg path[d*="M8 5v14l11-7z"]');
            for (const path of svgPaths) {
                const svg = path.closest('svg');
                if (svg) {
                    let parent = svg.parentElement;

                    if (parent) {
                        const style = window.getComputedStyle(parent);
                        const hasPlayStyle =
                            style.borderRadius === '50%' ||
                            parent.style.borderRadius === '50%' ||
                            style.cursor === 'pointer' ||
                            parent.onclick;

                        if (hasPlayStyle || parent.tagName === 'BUTTON') {
                            console.log('[猫抓助手] 找到播放按钮（SVG父元素）:', parent.tagName);
                            parent.click();
                            updateStatus('✅ 已点击播放按钮');
                            addLog('已点击播放按钮（' + parent.tagName + '）');
                            return true;
                        }

                        const grandParent = parent.parentElement;
                        if (grandParent) {
                            const gpStyle = window.getComputedStyle(grandParent);
                            if (gpStyle.borderRadius === '50%' ||
                                grandParent.style.borderRadius === '50%' ||
                                gpStyle.cursor === 'pointer') {
                                console.log('[猫抓助手] 找到播放按钮（祖父元素）:', grandParent.tagName);
                                grandParent.click();
                                updateStatus('✅ 已点击播放按钮');
                                addLog('已点击播放按钮（' + grandParent.tagName + '）');
                                return true;
                            }
                        }
                    }
                }
            }

            // 查找圆形播放按钮（通过样式）
            const allDivs = document.querySelectorAll('div');
            for (const div of allDivs) {
                const style = window.getComputedStyle(div);
                if (style.borderRadius === '50%' &&
                    style.display === 'flex' &&
                    div.querySelector('svg path[d*="M8 5v14l11-7z"]')) {
                    console.log('[猫抓助手] 找到圆形播放按钮（div）');
                    div.click();
                    updateStatus('✅ 已点击播放按钮');
                    addLog('已点击播放按钮（圆形div）');
                    return true;
                }
            }

            if (retry < CONFIG.retryTimes - 1) {
                await new Promise(resolve => setTimeout(resolve, CONFIG.retryInterval));
            }
        }

        console.log('[猫抓助手] 未找到播放按钮');
        updateStatus('⚠️ 未找到播放按钮');
        addLog('未找到播放按钮，已最小化面板');
        addLog('点击图标可展开面板，或点击"重新嗅探"按钮');

        // 未找到播放按钮，自动最小化面板
        setTimeout(() => {
            minimizePanel();
        }, 1000);

        return false;
    }

    // 查找并点击跳过广告按钮（带重试）
    async function clickSkipAdButton() {
        updateStatus('等待广告播放...');
        addLog('等待广告播放...');

        await new Promise(resolve => setTimeout(resolve, CONFIG.adWaitTime));

        updateStatus('正在查找跳过广告按钮...');

        for (let retry = 0; retry < CONFIG.retryTimes; retry++) {
            console.log(`[猫抓助手] 第 ${retry + 1} 次尝试查找跳过广告按钮`);

            const skipXPaths = [
                "//button[contains(text(), '跳')]",
                "//button[contains(text(), 'Skip')]",
                "//button[contains(text(), 'skip')]",
                "//button[contains(., '跳')]",
                "//button[contains(., 'Skip')]"
            ];

            for (const xpath of skipXPaths) {
                try {
                    const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                    const button = result.singleNodeValue;

                    if (button && button.offsetParent !== null) {
                        console.log('[猫抓助手] 找到跳过广告按钮:', button.textContent);
                        button.click();
                        updateStatus('✅ 已点击跳过广告按钮');
                        addLog('已点击跳过广告按钮: ' + button.textContent);
                        return true;
                    }
                } catch (e) {
                    console.error('XPath 错误:', e);
                }
            }

            const buttons = document.querySelectorAll('button');
            for (const button of buttons) {
                const text = button.textContent || '';
                if ((text.includes('跳') || text.includes('Skip')) && button.offsetParent !== null) {
                    console.log('[猫抓助手] 找到跳过广告按钮:', text);
                    button.click();
                    updateStatus('✅ 已点击跳过广告按钮');
                    addLog('已点击跳过广告按钮: ' + text);
                    return true;
                }
            }

            if (retry < CONFIG.retryTimes - 1) {
                await new Promise(resolve => setTimeout(resolve, CONFIG.retryInterval));
            }
        }

        console.log('[猫抓助手] 未找到跳过广告按钮');
        updateStatus('⚠️ 未找到跳过广告按钮');
        addLog('未找到跳过广告按钮，请手动点击');
        return false;
    }

    // 主流程
    async function main() {
        console.log('[猫抓助手] 开始执行主流程');

        // 立即启用广告拦截（不需要等待 DOM）
        blockAdRedirects();
        console.log('[猫抓助手] 广告拦截已启用');

        // 等待 DOM 准备好
        if (document.readyState === 'loading') {
            await new Promise(resolve => {
                document.addEventListener('DOMContentLoaded', resolve);
            });
        }

        // DOM 已准备好，创建界面和启动监控
        if (CONFIG.showResult) {
            createResultPanel();
            addLog('脚本已加载 v1.4');
            addLog(`最小时长过滤: ${CONFIG.minDuration}秒`);
        }

        addLog('广告拦截已启用');

        interceptNetworkRequests();
        addLog('网络请求拦截已启用');

        await new Promise(resolve => setTimeout(resolve, 2000));

        if (CONFIG.autoClickPlay) {
            const playClicked = await clickPlayButton();

            if (playClicked && CONFIG.autoSkipAd) {
                await clickSkipAdButton();
            }
        }
    }

    // 立即执行主流程
    main();

})();
