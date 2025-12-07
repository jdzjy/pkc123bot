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
                        // 特殊处理：ENV_189_COOKIES
                        // 如果遇到这个变量，不生成通用输入框，而是将其值填充到专用卡片中
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
    .then(res => {
        if (!res.ok) {
            throw new Error(`Server error: ${res.status}`);
        }
        return res.json();
    })
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

let logAutoRefreshInterval = null;

function loadLogs() {
    const viewer = document.getElementById('log-viewer');
    if (!viewer) return;

    if (viewer.textContent === '正在加载日志...') {
        viewer.textContent = '加载中...';
    }

    fetch('/api/logs')
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const isAtBottom = viewer.scrollHeight - viewer.scrollTop <= viewer.clientHeight + 50;
                viewer.textContent = data.data || '暂无日志内容';
                if (isAtBottom || viewer.scrollTop === 0) {
                    viewer.scrollTop = viewer.scrollHeight;
                }
            } else {
                viewer.textContent = '读取日志失败: ' + data.error;
            }
        })
        .catch(err => {
            console.error(err);
            if (!logAutoRefreshInterval) {
                viewer.textContent = '请求失败，请检查网络连接。';
            }
        });
}

document.getElementById('auto-refresh-log')?.addEventListener('change', function(e) {
    if (e.target.checked) {
        loadLogs();
        logAutoRefreshInterval = setInterval(loadLogs, 5000);
    } else {
        stopAutoRefresh();
    }
});

function stopAutoRefresh() {
    if (logAutoRefreshInterval) {
        clearInterval(logAutoRefreshInterval);
        logAutoRefreshInterval = null;
    }
    const checkbox = document.getElementById('auto-refresh-log');
    if (checkbox) checkbox.checked = false;
}