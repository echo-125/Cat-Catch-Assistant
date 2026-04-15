// ==UserScript==
// @name         吃瓜网站专用M3U8嗅探器
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  专门针对chigua.com/51cg1.com等网站的M3U8嗅探器
// @author       Claude Code
// @match        https://chigua.com/*
// @match        https://blade.qtkezmpl.cc/*
// @match        https://51cg1.com/*
// @match        https://*.51cg1.com/*
// @match        https://b5vow.yggihubp.com/*
// @match        https://*.yggihubp.com/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    console.log('[M3U8嗅探器] 脚本已加载 v1.0');

    // 存储捕获的链接
    const capturedUrls = new Set();
    const capturedNames = new Set(); // 基于文件名去重

    // 最小时长（秒）- 低于此时长的视频将被过滤
    const MIN_DURATION = 60;

    // 获取M3U8视频时长
    async function getM3U8Duration(url) {
        try {
            // blob URL无法直接获取，跳过
            if (url.startsWith('blob:')) {
                return -1; // 返回-1表示无法检测
            }

            const response = await fetch(url);
            const content = await response.text();

            let totalDuration = 0;
            const lines = content.split('\n');

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i].trim();
                if (line.startsWith('#EXTINF:')) {
                    const match = line.match(/#EXTINF:([\d.]+)/);
                    if (match) {
                        totalDuration += parseFloat(match[1]);
                    }
                }
            }

            return totalDuration;
        } catch (error) {
            console.error('[M3U8嗅探器] 获取时长失败:', error);
            return -1; // 返回-1表示获取失败
        }
    }

    // 格式化时长
    function formatDuration(seconds) {
        if (seconds < 0) return '未知';
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

    // 创建结果面板
    function createPanel() {
        const panel = document.createElement('div');
        panel.id = 'm3u8-panel';
        panel.innerHTML = `
            <style>
                #m3u8-panel {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    width: 600px;
                    max-height: 500px;
                    background: white;
                    border: 2px solid #4CAF50;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    z-index: 999999;
                    font-family: Arial, sans-serif;
                    overflow: hidden;
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
                }
                #m3u8-panel-content {
                    padding: 15px;
                    max-height: 400px;
                    overflow-y: auto;
                }
                .m3u8-item {
                    background: #f5f5f5;
                    padding: 10px;
                    margin: 8px 0;
                    border-radius: 4px;
                    border-left: 3px solid #4CAF50;
                    word-break: break-all;
                }
                .m3u8-item button {
                    background: #4CAF50;
                    color: white;
                    border: none;
                    padding: 5px 10px;
                    border-radius: 3px;
                    cursor: pointer;
                    margin-top: 5px;
                    margin-right: 5px;
                }
                .log-item {
                    font-size: 12px;
                    color: #666;
                    margin: 5px 0;
                    padding: 5px;
                    background: #f9f9f9;
                    border-radius: 3px;
                }
                .panel-controls {
                    display: flex;
                    gap: 10px;
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
                }
            </style>
            <div id="m3u8-panel-header">
                <span>M3U8嗅探器 v1.0</span>
                <span id="m3u8-panel-close">×</span>
            </div>
            <div id="m3u8-panel-content">
                <p>等待捕获链接...</p>
            </div>
            <div class="panel-controls">
                <button id="m3u8-scan-btn">🔍 扫描页面</button>
                <button id="m3u8-clear-btn">🗑️ 清空</button>
            </div>
        `;

        document.body.appendChild(panel);

        // 关闭按钮
        document.getElementById('m3u8-panel-close').onclick = () => {
            panel.style.display = 'none';
        };

        // 扫描按钮
        document.getElementById('m3u8-scan-btn').onclick = () => {
            deepScan();
        };

        // 清空按钮
        document.getElementById('m3u8-clear-btn').onclick = () => {
            capturedUrls.clear();
            capturedNames.clear();
            document.getElementById('m3u8-panel-content').innerHTML = '<p>等待捕获链接...</p>';
            addLog('已清空列表');
        };

        return panel;
    }

    // 添加日志
    function addLog(message) {
        const contentEl = document.getElementById('m3u8-panel-content');
        if (!contentEl) return;

        const logItem = document.createElement('div');
        logItem.className = 'log-item';
        logItem.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        contentEl.appendChild(logItem);
    }

    // 添加M3U8链接到面板
    async function addM3U8Url(url) {
        // 提取文件名用于去重
        const urlName = url.split('/').pop().split('?')[0];

        // 基于文件名去重（避免同一视频的不同参数版本重复显示）
        if (capturedNames.has(urlName)) {
            console.log('[M3U8嗅探器] 重复文件名，跳过:', urlName);
            return false;
        }

        // 额外检查：如果是blob URL，检查是否已有对应的真实URL
        if (url.startsWith('blob:')) {
            // 如果已经有真实URL，跳过blob URL
            if (capturedNames.size > 0 && !urlName.includes('-')) {
                console.log('[M3U8嗅探器] 跳过blob URL（已有真实URL）:', urlName);
                return false;
            }
        }

        capturedUrls.add(url);
        capturedNames.add(urlName);

        const contentEl = document.getElementById('m3u8-panel-content');
        if (!contentEl) return false;

        // 移除"等待捕获"提示
        const waiting = contentEl.querySelector('p');
        if (waiting && waiting.textContent === '等待捕获链接...') {
            waiting.remove();
        }

        const item = document.createElement('div');
        item.className = 'm3u8-item';

        // 显示加载中状态
        item.innerHTML = `
            <div><strong>📹 M3U8链接</strong> <span class="duration-loading">⏳ 检测时长中...</span></div>
            <div style="font-size: 12px; color: #666; margin: 5px 0;">${urlName}</div>
            <div style="font-size: 11px; color: #999; word-break: break-all;">${url}</div>
            <button class="copy-btn">复制链接</button>
            <button class="open-btn" style="background: #FF5722;">打开链接</button>
        `;

        contentEl.insertBefore(item, contentEl.firstChild);
        addLog('捕获到M3U8链接: ' + urlName);

        // 异步获取时长
        const duration = await getM3U8Duration(url);
        const durationStr = formatDuration(duration);

        // 更新时长显示
        const durationEl = item.querySelector('.duration-loading');
        if (durationEl) {
            if (duration < 0) {
                durationEl.textContent = `⏱️ 时长: ${durationStr}`;
                durationEl.style.color = '#999';
            } else if (duration < MIN_DURATION) {
                durationEl.textContent = `⚠️ 时长: ${durationStr} (过短，可能是广告)`;
                durationEl.style.color = '#ff9800';
                item.style.opacity = '0.6';
                addLog(`过滤短视频: ${urlName} (${durationStr})`);
            } else {
                durationEl.textContent = `✅ 时长: ${durationStr}`;
                durationEl.style.color = '#4CAF50';
                durationEl.style.fontWeight = 'bold';
            }
        }

        // 复制按钮
        item.querySelector('.copy-btn').onclick = () => {
            const title = document.title.replace(/[<>:"/\\|?*]/g, '_').substring(0, 50);
            const text = `${url}|${title}`;
            navigator.clipboard.writeText(text).then(() => {
                alert(`已复制！\n\n文件名: ${title}\n链接: ${url.substring(0, 50)}...`);
                addLog('已复制: ' + title);
            });
        };

        // 打开按钮
        item.querySelector('.open-btn').onclick = () => {
            window.open(url);
        };

        return true;
    }

    // 深度扫描页面
    function deepScan() {
        addLog('开始深度扫描...');

        // 1. 扫描HTML
        const html = document.documentElement.outerHTML;
        console.log('[M3U8嗅探器] HTML长度:', html.length);

        // 2. 尝试多种正则表达式
        const patterns = [
            /https?:\/\/[^\s"'`<>]+\.m3u8[^\s"'`<>]*/gi,
            /["'](https?:\/\/[^"']+\.m3u8[^"']*)["']/gi,
            /url\s*[:=]\s*["'](https?:\/\/[^"']+\.m3u8[^"']*)["']/gi,
        ];

        patterns.forEach((pattern, index) => {
            const matches = html.match(pattern);
            if (matches) {
                console.log(`[M3U8嗅探器] 正则${index}找到:`, matches.length);
                matches.forEach(url => {
                    // 清理URL
                    url = url.replace(/^["']|["']$/g, '').replace(/[;,)\]}>'"`]+$/, '');
                    if (url.includes('.m3u8')) {
                        console.log('[M3U8嗅探器] 提取到:', url);
                        addM3U8Url(url);
                    }
                });
            }
        });

        // 3. 扫描所有script标签
        const scripts = document.querySelectorAll('script');
        console.log('[M3U8嗅探器] Script标签数量:', scripts.length);

        scripts.forEach((script, i) => {
            const content = script.textContent || script.innerHTML;
            if (content) {
                patterns.forEach(pattern => {
                    const matches = content.match(pattern);
                    if (matches) {
                        matches.forEach(url => {
                            url = url.replace(/^["']|["']$/g, '').replace(/[;,)\]}>'"`]+$/, '');
                            if (url.includes('.m3u8')) {
                                console.log(`[M3U8嗅探器] Script ${i} 找到:`, url);
                                addM3U8Url(url);
                            }
                        });
                    }
                });
            }
        });

        // 4. 扫描video元素
        const videos = document.querySelectorAll('video');
        console.log('[M3U8嗅探器] Video元素数量:', videos.length);
        videos.forEach((video, i) => {
            const src = video.src || video.currentSrc;
            if (src) {
                console.log(`[M3U8嗅探器] Video ${i}:`, src);
                addM3U8Url(src);
            }
        });

        // 5. 扫描window对象
        try {
            for (let key in window) {
                try {
                    const value = String(window[key]);
                    if (value.includes('.m3u8')) {
                        const matches = value.match(/https?:\/\/[^\s"'`<>]+\.m3u8[^\s"'`<>]*/gi);
                        if (matches) {
                            matches.forEach(url => {
                                console.log('[M3U8嗅探器] Window.' + key + '找到:', url);
                                addM3U8Url(url);
                            });
                        }
                    }
                } catch(e) {}
            }
        } catch(e) {}

        addLog('深度扫描完成');
    }

    // 拦截所有可能的请求
    function interceptAllRequests() {
        // 1. XHR
        const originalXHROpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            const urlStr = String(url);
            if (urlStr.includes('.m3u8')) {
                console.log('[M3U8嗅探器] XHR捕获:', urlStr);
                addM3U8Url(urlStr);
            }
            return originalXHROpen.apply(this, arguments);
        };

        // 2. Fetch
        const originalFetch = window.fetch;
        window.fetch = function(url, options) {
            const urlStr = String(url);
            if (urlStr.includes('.m3u8')) {
                console.log('[M3U8嗅探器] Fetch捕获:', urlStr);
                addM3U8Url(urlStr);
            }
            return originalFetch.apply(this, arguments);
        };

        // 3. 动态创建script标签
        const originalCreateElement = document.createElement;
        document.createElement = function(tagName) {
            const element = originalCreateElement.call(document, tagName);

            if (tagName.toLowerCase() === 'script') {
                const originalSetAttribute = element.setAttribute;
                element.setAttribute = function(name, value) {
                    if (name === 'src' && String(value).includes('.m3u8')) {
                        console.log('[M3U8嗅探器] Script.src捕获:', value);
                        addM3U8Url(String(value));
                    }
                    return originalSetAttribute.call(this, name, value);
                };
            }

            return element;
        };

        console.log('[M3U8嗅探器] 请求拦截已启用');
    }

    // 监听DOM变化
    function observeDOM() {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // 检查video元素
                        if (node.tagName === 'VIDEO') {
                            const src = node.src || node.currentSrc;
                            if (src) {
                                console.log('[M3U8嗅探器] 动态Video捕获:', src);
                                addM3U8Url(src);
                            }
                        }

                        // 检查script元素
                        if (node.tagName === 'SCRIPT') {
                            const src = node.src;
                            if (src && src.includes('.m3u8')) {
                                console.log('[M3U8嗅探器] 动态Script捕获:', src);
                                addM3U8Url(src);
                            }
                        }

                        // 检查子元素
                        const videos = node.querySelectorAll && node.querySelectorAll('video');
                        if (videos) {
                            videos.forEach(video => {
                                const src = video.src || video.currentSrc;
                                if (src) {
                                    console.log('[M3U8嗅探器] 子元素Video捕获:', src);
                                    addM3U8Url(src);
                                }
                            });
                        }
                    }
                });
            });
        });

        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });

        console.log('[M3U8嗅探器] DOM监听已启用');
    }

    // 主函数
    function main() {
        // 竉即启用拦截
        interceptAllRequests();

        // 等待DOM加载
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                createPanel();
                addLog('脚本已加载');
                observeDOM();

                // 延迟扫描
                setTimeout(deepScan, 2000);
                setTimeout(deepScan, 5000);
                setTimeout(deepScan, 10000);
            });
        } else {
            createPanel();
            addLog('脚本已加载');
            observeDOM();
            deepScan();
        }
    }

    main();

})();
