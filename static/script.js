document.addEventListener('DOMContentLoaded', function() {
    const envForm = document.getElementById('env-form');
    const navItems = document.querySelectorAll('.nav-item');
    const panes = document.querySelectorAll('.section-pane');
    const pageTitle = document.getElementById('page-title');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            navItems.forEach(n => n.classList.remove('active'));
            panes.forEach(p => p.classList.remove('active'));
            
            item.classList.add('active');
            const target = item.dataset.target;
            document.getElementById(`section-${target}`).classList.add('active');
            pageTitle.textContent = item.querySelector('span').textContent + '配置';

            if(target === 'tg') {
                checkTgStatus();
            }
            if(target === 'logs') {
                loadLogs();
            } else {
                stopAutoRefresh();
            }            
        });
    });

    function getTargetSection(sectionName) {
        const name = sectionName.toLowerCase();
        if (name.includes('web') || name.includes('登录') || name.includes('admin')) return 'web';
        if (name.includes('tg') || name.includes('telegram') || name.includes('机器人')) return 'tg';
        if (name.includes('123')) return '123';
        if (name.includes('115')) return '115';
        if (name.includes('天翼') || name.includes('189')) return 'ty';
        if (name.includes('log') || name.includes('日志')) return 'logs';
        return 'other';
    }

    showLoading();

    fetch('/api/env')
        .then(res => res.json())
        .then(data => {
            const sections = data.sections;
            const order = data.order;
            order.forEach(sectionName => {
                const targetId = getTargetSection(sectionName);
                const container = document.getElementById(`section-${targetId}`);
                if (container) {
                    const group = document.createElement('div');
                    group.className = 'config-group';
                    const header = document.createElement('h3');
                    header.textContent = sectionName;
                    group.appendChild(header);

                    sections[sectionName].forEach(item => {
                        if (item.key === 'ENV_189_COOKIES') {
                            const manualInput = document.getElementById('ty-manual-cookie');
                            if (manualInput) {
                                manualInput.value = item.value || '';
                            }
                            return; 
                        }

                        const div = document.createElement('div');
                        div.className = 'config-item';
                        const label = document.createElement('label');
                        label.textContent = item.key;
                        div.appendChild(label);

                        if (item.comment) {
                            const comment = document.createElement('div');
                            comment.className = 'comment' + (item.comment.includes('必填') ? ' required' : '');
                            comment.innerHTML = item.comment.replace('必填：', '<i class="fas fa-asterisk"></i> ');
                            div.appendChild(comment);
                        }

                        const input = document.createElement('input');
                        input.type = item.key.toLowerCase().includes('password') || item.key.toLowerCase().includes('token') ? 'password' : 'text';
                        input.value = item.value || '';
                        input.dataset.section = sectionName;
                        input.dataset.key = item.key;
                        input.dataset.comment = item.comment || '';
                        
                        if(item.key === 'ENV_PHONE_NUMBER') {
                            document.getElementById('tg-phone-input').value = item.value;
                        }

                        div.appendChild(input);
                        group.appendChild(div);
                    });
                    
                    if (group.children.length > 1) {
                        container.appendChild(group);
                    }
                }
            });

            const tgSection = document.getElementById('section-tg');
            const loginDashboard = document.getElementById('tg-login-dashboard');
            loginDashboard.style.display = 'block';
            tgSection.insertBefore(loginDashboard, tgSection.firstChild);
            
            hideLoading();
            checkTgStatus();
        })
        .catch(err => {
            console.error(err);
            hideLoading();
            showNotification('配置加载失败', 'error');
        });

    envForm.addEventListener('submit', (e) => {
        e.preventDefault();
        showLoading();
        const formData = {};
        document.querySelectorAll('input[data-key]').forEach(input => {
            const sec = input.dataset.section;
            if (!formData[sec]) formData[sec] = [];
            formData[sec].push({
                key: input.dataset.key,
                value: input.value,
                comment: input.dataset.comment
            });
        });

        fetch('/api/env', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(formData)
        })
        .then(res => res.json())
        .then(data => {
            hideLoading();
            if (data.success) {
                if(confirm('配置已保存成功！\n是否立即重启服务以使新配置生效？')) {
                    restartService(true); 
                } else {
                    showNotification('保存成功 (未重启)', 'success');
                }
            } else {
                showNotification('保存失败', 'error');
            }
        });
    });
});

function checkTgStatus() {
    fetch('/api/tg/status')
        .then(res => res.json())
        .then(data => {
            document.getElementById('tg-status-loading').style.display = 'none';
            if (data.status === 'logged_in') {
                document.getElementById('tg-logged-in').style.display = 'block';
                document.getElementById('tg-login-form').style.display = 'none';
                document.getElementById('tg-user-name').textContent = `${data.first_name} (@${data.username || '无用户名'})`;
                document.getElementById('tg-user-phone').textContent = data.phone;
            } else {
                document.getElementById('tg-logged-in').style.display = 'none';
                document.getElementById('tg-login-form').style.display = 'block';
                resetTgLogin();
            }
        })
        .catch(() => {
            document.getElementById('tg-status-loading').textContent = '状态检查失败';
        });
}

function tgSendCode() {
    const phone = document.getElementById('tg-phone-input').value;
    if (!phone) return showNotification('请输入手机号', 'error');
    
    showLoading();
    fetch('/api/tg/login/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({phone})
    }).then(res => res.json()).then(data => {
        hideLoading();
        if (data.success) {
            showNotification('验证码已发送', 'success');
            document.getElementById('step-phone').style.display = 'none';
            document.getElementById('step-code').style.display = 'block';
        } else {
            showNotification(data.message, 'error');
        }
    });
}

function tgVerifyCode() {
    const code = document.getElementById('tg-code-input').value;
    if (!code) return showNotification('请输入验证码', 'error');

    showLoading();
    fetch('/api/tg/login/verify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code})
    })
    .then(res => res.json())
    .then(data => {
        hideLoading();
        if (data.success) {
            if (data.status === 'logged_in') {
                showNotification('登录成功！', 'success');
                setTimeout(checkTgStatus, 1000);
            } else if (data.status === '2fa_required') {
                document.getElementById('step-code').style.display = 'none';
                document.getElementById('step-password').style.display = 'block';
                showNotification('请输入两步验证密码', 'success');
            }
        } else {
            showNotification('错误: ' + data.message, 'error');
        }
    })
    .catch(err => {
        hideLoading();
        showNotification('请求失败: ' + err.message, 'error');
    });
}

function tgVerifyPassword() {
    const password = document.getElementById('tg-password-input').value;
    if (!password) return showNotification('请输入密码', 'error');

    showLoading();
    fetch('/api/tg/login/password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password})
    }).then(res => res.json()).then(data => {
        hideLoading();
        if (data.success) {
            checkTgStatus();
            showNotification('登录成功！', 'success');
        } else {
            showNotification(data.message, 'error');
        }
    });
}

function tgLogout() {
    if(!confirm('确定要注销TG账号吗？session文件将被删除。')) return;
    showLoading();
    fetch('/api/tg/logout', {method: 'POST'})
        .then(res => res.json())
        .then(() => {
            hideLoading();
            checkTgStatus();
            showNotification('已注销', 'success');
        });
}

function resetTgLogin() {
    document.getElementById('step-phone').style.display = 'block';
    document.getElementById('step-code').style.display = 'none';
    document.getElementById('step-password').style.display = 'none';
    document.getElementById('tg-code-input').value = '';
    document.getElementById('tg-password-input').value = '';
}

function saveTyCookie() {
    const cookie = document.getElementById('ty-manual-cookie').value;
    if (!cookie) return showNotification('Cookie 不能为空', 'error');
    
    showLoading();
    fetch('/api/189/cookie/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ cookie })
    })
    .then(res => res.json())
    .then(data => {
        hideLoading();
        if (data.success) {
            showNotification(data.msg, 'success');
            setTimeout(() => restartService(), 1500);
        } else {
            showNotification(data.msg, 'error');
        }
    });
}

function showLoading() { document.getElementById('loading').classList.add('show'); }
function hideLoading() { document.getElementById('loading').classList.remove('show'); }
function showNotification(msg, type) {
    const n = document.getElementById('notification');
    n.textContent = msg;
    n.className = `notification ${type}`;
    n.style.display = 'block';
    setTimeout(() => {
        n.style.display = 'none';
        n.className = 'notification';
    }, 3000);
}

function restartService(skipConfirm = true) {
    if (!skipConfirm) {
        if (!confirm('确定要重启服务吗？重启期间网站将短暂无法访问。')) return;
    }
    
    showLoading();
    fetch('/api/restart', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            showNotification('服务正在重启，请稍候刷新页面...', 'success');
            document.body.style.pointerEvents = 'none';
            document.body.style.opacity = '0.7';
            setTimeout(() => {
                location.reload();
            }, 5000);
        })
        .catch(err => {
            hideLoading();
            showNotification('重启请求发送失败', 'error');
            document.body.style.pointerEvents = 'auto';
            document.body.style.opacity = '1';
        });
}

// ================= 实时日志流系统 (SSE Real-time) =================

let eventSource = null;
let logBuffer = []; // 缓冲池，避免高频渲染卡顿
let isRenderPending = false;

// 启动实时日志
function startLogStream() {
    const viewer = document.getElementById('log-viewer');
    const btn = document.getElementById('btn-log-switch');
    
    // 防止重复开启
    if (eventSource) return;

    if (viewer) {
        viewer.innerHTML = ''; // 清空旧日志
        viewer.innerHTML = '<div class="log-system-msg"><i class="fas fa-satellite-dish fa-spin"></i> 正在建立实时连接...</div>';
    }

    // 建立 SSE 连接
    eventSource = new EventSource('/api/stream_logs');

    // 1. 接收消息
    eventSource.onmessage = function(event) {
        // 将新消息放入缓冲池
        logBuffer.push(event.data);
        
        // 如果没有渲染任务在排队，则发起一次渲染
        if (!isRenderPending) {
            requestAnimationFrame(processLogBuffer);
            isRenderPending = true;
        }
    };

    // 2. 错误处理
    eventSource.onerror = function(err) {
        console.error("SSE Error:", err);
        eventSource.close();
        eventSource = null;
        if (viewer) {
            const errDiv = document.createElement('div');
            errDiv.className = 'log-line error-line';
            errDiv.innerHTML = '<span class="log-badge tag-other">SYSTEM</span> 连接已断开，请点击“开始实时”重连';
            viewer.appendChild(errDiv);
        }
        updateLogBtnState(false);
    };

    updateLogBtnState(true);
}

// 关闭实时日志
function stopLogStream() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    updateLogBtnState(false);
    
    const viewer = document.getElementById('log-viewer');
    if(viewer) {
        const div = document.createElement('div');
        div.className = 'log-line';
        div.style.borderLeft = "3px solid #777";
        div.style.opacity = "0.7";
        div.innerHTML = '<span class="log-badge tag-other">PAUSED</span> 实时流已暂停';
        viewer.appendChild(div);
        viewer.scrollTop = viewer.scrollHeight;
    }
}

// 切换开关
function toggleLogStream() {
    if (eventSource) {
        stopLogStream();
    } else {
        startLogStream();
    }
}

// 更新按钮文字
function updateLogBtnState(isRunning) {
    const btn = document.getElementById('btn-log-switch');
    if (!btn) return;
    
    if (isRunning) {
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-success');
        btn.innerHTML = '<i class="fas fa-pause"></i> 暂停实时';
        // 自动滚动开关：默认开启
        document.getElementById('auto-scroll-log').disabled = false;
    } else {
        btn.classList.remove('btn-success');
        btn.classList.add('btn-secondary');
        btn.innerHTML = '<i class="fas fa-play"></i> 开始实时';
    }
}

// 批量处理缓冲区日志 (性能优化核心)
function processLogBuffer() {
    const viewer = document.getElementById('log-viewer');
    if (!viewer || logBuffer.length === 0) {
        isRenderPending = false;
        return;
    }

    // 移除初始的加载提示
    const loader = viewer.querySelector('.log-system-msg');
    if (loader) loader.remove();

    const fragment = document.createDocumentFragment();
    const filterValue = document.getElementById('logFilter').value;
    const hideWerkzeug = document.getElementById('hide-werkzeug').checked;

    // 取出缓冲区所有数据
    const batch = logBuffer.splice(0, logBuffer.length);

    batch.forEach(line => {
        if (!line.trim()) return;
        const el = createLogLineElement(line, filterValue, hideWerkzeug);
        fragment.appendChild(el);
    });

    viewer.appendChild(fragment);

    // 限制 DOM 节点数量，防止内存泄漏 (保留最近 2000 行)
    while (viewer.children.length > 2000) {
        viewer.removeChild(viewer.firstChild);
    }

    // 自动滚动
    if (document.getElementById('auto-scroll-log').checked) {
        viewer.scrollTop = viewer.scrollHeight;
    }

    isRenderPending = false;
    
    // 如果处理完这一批，缓冲区又有新数据了，继续处理
    if (logBuffer.length > 0) {
        requestAnimationFrame(processLogBuffer);
        isRenderPending = true;
    }
}

// 创建单行日志 DOM (解析逻辑)
function createLogLineElement(line, filterValue, hideWerkzeug) {
    // 正则解析：时间 - 模块 - 级别 - 内容
    const logRegex = /^(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:,\d+)?)\s-\s(\S+)\s-\s([A-Z]+)\s-\s(.*)$/;
    
    let category = 'other';
    let level = 'INFO';
    let timeStr = '';
    let msgStr = line;
    let isFormatted = false;

    const match = line.match(logRegex);
    if (match) {
        isFormatted = true;
        timeStr = match[1].split(',')[0]; // 去掉毫秒
        category = match[2];
        level = match[3];
        msgStr = match[4];
    } else {
        // 失败回退逻辑
        if (line.includes('werkzeug')) category = 'werkzeug';
        else if (line.includes('bot115')) category = 'bot115';
        else if (line.includes('bot189')) category = 'bot189';
        else if (line.includes('quark')) category = 'quark';
        
        if (line.includes('ERROR') || line.includes('Traceback')) level = 'ERROR';
        else if (line.includes('WARNING')) level = 'WARNING';
    }

    // 判断显隐
    let isHidden = false;
    if (filterValue !== 'all') {
        if (category !== filterValue && !category.includes(filterValue)) isHidden = true;
    } else {
        if (hideWerkzeug && (category === 'werkzeug' || line.includes(' /api/'))) isHidden = true;
    }

    const div = document.createElement('div');
    div.className = `log-entry level-${level} item-${category}`;
    if (isHidden) div.classList.add('hidden');

    if (isFormatted) {
        let modClass = 'mod-other';
        if (category.includes('115')) modClass = 'mod-115';
        else if (category.includes('189')) modClass = 'mod-189';
        else if (category.includes('quark')) modClass = 'mod-quark';
        else if (category.includes('main')) modClass = 'mod-main';
        else if (category.includes('mp')) modClass = 'mod-mp';
        else if (category.includes('werkzeug')) modClass = 'mod-web';

        // 高亮关键词
        let safeMsg = escapeHtml(msgStr)
            .replace(/(Successfully|Success|成功|完成|✅)/gi, '<span style="color:#67c23a;font-weight:bold;">$1</span>')
            .replace(/(Failed|Fail|Error|失败|错误|❌)/gi, '<span style="color:#f56c6c;font-weight:bold;">$1</span>')
            .replace(/(\/s\/[a-zA-Z0-9]+)/g, '<span style="color:#e6a23c;">$1</span>'); // 高亮链接Key

        div.innerHTML = `
            <span class="log-time">${timeStr}</span>
            <span class="log-badge ${modClass}">${category}</span>
            <span class="log-msg">${safeMsg}</span>
        `;
    } else {
        // Traceback 或非标准行
        if (level === 'ERROR' || line.trim().startsWith('Traceback') || line.trim().startsWith('File "')) {
            div.classList.add('log-traceback');
        }
        div.textContent = line;
    }
    
    return div;
}

// 纯前端筛选应用 (切换下拉框时调用)
function applyLogFilter() {
    const filterValue = document.getElementById('logFilter').value;
    const hideWerkzeug = document.getElementById('hide-werkzeug').checked;
    
    // 遍历当前 DOM 中所有日志行进行显隐切换
    const entries = document.querySelectorAll('.log-entry');
    entries.forEach(row => {
        let isHidden = false;
        
        // 从 class 中提取 category
        let category = 'other';
        row.classList.forEach(c => { if(c.startsWith('item-')) category = c.replace('item-', ''); });

        if (filterValue !== 'all') {
            if (category !== filterValue && !category.includes(filterValue)) isHidden = true;
        } else {
            if (hideWerkzeug && (category === 'werkzeug' || category === 'other')) {
                // 简单判定：如果是 werkzeug 或者是 other 且包含 HTTP 动词
                if (category === 'werkzeug' || row.textContent.includes('HTTP/1.')) isHidden = true;
            }
        }

        if (isHidden) row.classList.add('hidden');
        else row.classList.remove('hidden');
    });
    
    // 筛选后滚动到底部
    const viewer = document.getElementById('log-viewer');
    if (document.getElementById('auto-scroll-log').checked) {
        viewer.scrollTop = viewer.scrollHeight;
    }
}

// 当用户切换到日志 Tab 时，自动开启流
const logsTabBtn = document.querySelector('button[data-target="logs"]');
if(logsTabBtn) {
    logsTabBtn.addEventListener('click', () => {
        // 延迟一点点，确保 DOM 切换完成
        setTimeout(() => {
            if(!eventSource) startLogStream();
        }, 100);
    });
}

// 页面卸载或切换 Tab 时可以考虑关闭流节省资源 (可选，这里暂时不加，保持后台监控)
// window.addEventListener('beforeunload', stopLogStream);

function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
