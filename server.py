from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import sys
import time
import secrets
import logging
import asyncio
import threading
from urllib.parse import unquote
from tg_login import TelegramLogin
from bot189 import Cloud189, ENV_189_CLIENT_ID, ENV_189_CLIENT_SECRET

try:
    from get_download_url_by_path import get_download_url_by_path
    from get_download_url_by_path_xiaohao import get_download_url_by_path_xiaohao
except ImportError:
    get_download_url_by_path = lambda x: None
    get_download_url_by_path_xiaohao = lambda x, y: None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

LOG_FILE_PATH = os.path.join('db', 'log', 'log.log')
ENV_FILE_PATH = os.path.join('db', 'user.env')
TEMPLATE_ENV_PATH = 'templete.env'
ENV_WEB_PASSPORT = os.getenv("ENV_WEB_PASSPORT", "admin")
ENV_WEB_PASSWORD = os.getenv("ENV_WEB_PASSWORD", "123456")

os.makedirs('db', exist_ok=True)

tg_login_handler = TelegramLogin(session_name="default_session")
tg_loop = asyncio.new_event_loop()

def run_async(coro):
    return tg_loop.run_until_complete(coro)

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

t = threading.Thread(target=start_background_loop, args=(tg_loop,), daemon=True)
t.start()

def run_async_safe(coro):
    if not tg_loop.is_running():
        logger.error("后台事件循环未运行！")
        return {"success": False, "message": "后台服务错误"}
    future = asyncio.run_coroutine_threadsafe(coro, tg_loop)
    try:
        return future.result(timeout=30)
    except Exception as e:
        logger.error(f"异步执行错误: {e}")
        return {"success": False, "message": str(e)}

@app.route('/api/tg/status', methods=['GET'])
def get_tg_status():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        info = run_async_safe(tg_login_handler.get_user_info())
        return jsonify(info)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/tg/login/start', methods=['POST'])
def tg_login_start():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    phone = request.json.get('phone')
    if not phone: return jsonify({'success': False, 'message': '请输入手机号'})
    
    res = run_async_safe(tg_login_handler.api_step_1_send_code(phone))
    return jsonify(res)

@app.route('/api/tg/login/verify', methods=['POST'])
def tg_login_verify():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    code = request.json.get('code')
    if not code: return jsonify({'success': False, 'message': '请输入验证码'})
    
    res = run_async_safe(tg_login_handler.api_step_2_verify_code(code))
    return jsonify(res)

@app.route('/api/tg/login/password', methods=['POST'])
def tg_login_password():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    password = request.json.get('password')
    if not password: return jsonify({'success': False, 'message': '请输入密码'})
    
    res = run_async_safe(tg_login_handler.api_step_3_password(password))
    return jsonify(res)

@app.route('/api/tg/logout', methods=['POST'])
def tg_logout():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    run_async_safe(tg_login_handler.logout())
    return jsonify({'success': True})

# [保留] 天翼云盘 - 手动保存 Cookie
@app.route('/api/189/cookie/save', methods=['POST'])
def save_189_cookie():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    
    cookie_str = request.json.get('cookie')
    if not cookie_str:
        return jsonify({'success': False, 'msg': 'Cookie 不能为空'})
        
    return save_cookie_to_env(cookie_str)

def save_cookie_to_env(cookie_str):
    env_lines = []
    if os.path.exists(ENV_FILE_PATH):
        with open(ENV_FILE_PATH, 'r', encoding='utf-8') as f:
            env_lines = f.readlines()
    
    new_lines = []
    found = False
    for line in env_lines:
        if line.startswith('ENV_189_COOKIES='):
            new_lines.append(f'ENV_189_COOKIES="{cookie_str}"\n')
            found = True
        else:
            new_lines.append(line)
    
    if not found:
        new_lines.append(f'\n# 天翼云盘 Cookie (手动)\nENV_189_COOKIES="{cookie_str}"\n')
        
    try:
        with open(ENV_FILE_PATH, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return jsonify({'success': True, 'status': 'confirmed', 'msg': 'Cookie 已保存，请重启服务生效'})
    except Exception as e:
        return jsonify({'success': False, 'status': 'error', 'msg': f'保存配置失败: {e}'})

@app.route('/api/logs', methods=['GET'])
def get_logs():
    if not session.get('logged_in'): 
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if not os.path.exists(LOG_FILE_PATH):
            return jsonify({'success': True, 'data': '暂无日志文件 (日志可能尚未生成)'})
            
        lines = []
        try:
            with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                lines = all_lines[-500:]
        except UnicodeDecodeError:
            with open(LOG_FILE_PATH, 'r', encoding='gbk', errors='ignore') as f:
                all_lines = f.readlines()
                lines = all_lines[-500:]
                
        return jsonify({'success': True, 'data': ''.join(lines)})
    except Exception as e:
        logger.error(f"读取日志失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/env', methods=['GET'])
def get_env():
    template_structure = {}
    template_order = []
    current_section = '默认配置'
    current_comment = ''
    
    target_file = ENV_FILE_PATH if os.path.exists(ENV_FILE_PATH) else TEMPLATE_ENV_PATH

    if not os.path.exists(target_file):
        return jsonify({'sections': {}, 'order': []})

    with open(target_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith('#=') or line.startswith('# ='): continue

            if line.startswith('# ') and not line.startswith('## '):
                section_name = line[2:].strip()
                if set(section_name).issubset(set('=-* ')): continue
                current_section = section_name
                if current_section not in template_structure:
                    template_structure[current_section] = []
                    template_order.append(current_section)
                current_comment = ''
            elif line.startswith('#'):
                if line.startswith('## '): current_comment = line[3:]
                else: current_comment = line[1:].strip()
            elif '=' in line and not line.startswith('#'):
                try:
                    key, value = line.split('=', 1)
                    config_item = {'key': key.strip(), 'value': value.strip(), 'comment': current_comment}
                    if current_section not in template_structure:
                        template_structure[current_section] = []
                        template_order.append(current_section)
                    template_structure[current_section].append(config_item)
                    current_comment = ''
                except ValueError: continue
                
    return jsonify({'sections': template_structure, 'order': template_order})

@app.route('/api/env', methods=['POST'])
def save_env():
    data = request.json
    try:
        with open(ENV_FILE_PATH, 'w', encoding='utf-8') as f:
            for section, items in data.items():
                f.write(f'# {section}\n')
                for item in items:
                    if item.get("comment"): f.write(f'## {item["comment"]}\n')
                    f.write(f'{item["key"]}={item["value"]}\n')
                f.write('\n')
        
        global tg_login_handler
        tg_login_handler = TelegramLogin(session_name="default_session")
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Save error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('username') == ENV_WEB_PASSPORT and data.get('password') == ENV_WEB_PASSWORD:
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/logout', methods=['GET', 'POST'])
def logout():
    session.pop('logged_in', None)
    if request.method == 'POST': return jsonify({'success': True})
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    if session.get('logged_in'): return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login_page'))
    return render_template('index.html')

@app.route('/d/<path:file_path>')
def handle_direct_download(file_path):
    try:
        full_path = f"/{file_path}"
        download_url = get_download_url_by_path(full_path)
        if download_url: return redirect(download_url, code=302)
        return jsonify({'error': "文件未找到"}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/xiaohao1/<path:file_path>')
def handle_direct_download_xiaohao1(file_path):
    try:
        query_part = request.query_string.decode('utf-8')
        full_file_path = f"{file_path}?{query_part}" if query_part else file_path
        full_path = f"/{unquote(full_file_path)}"
        download_url = get_download_url_by_path_xiaohao(full_path, 1)
        if download_url: return redirect(download_url, code=302)
        return jsonify({'error': "文件未找到"}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/xiaohao2/<path:file_path>')
def handle_direct_download_xiaohao2(file_path):
    try:
        query_part = request.query_string.decode('utf-8')
        full_file_path = f"{file_path}?{query_part}" if query_part else file_path
        full_path = f"/{unquote(full_file_path)}"
        download_url = get_download_url_by_path_xiaohao(full_path, 2)
        if download_url: return redirect(download_url, code=302)
        return jsonify({'error': "文件未找到"}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/restart', methods=['POST'])
def restart_server():
    if not session.get('logged_in'): return jsonify({'error': 'Unauthorized'}), 401
    
    def restart_thread():
        time.sleep(1) 
        logger.info("收到重启请求，正在退出程序...")
        os._exit(1) 

    threading.Thread(target=restart_thread).start()
    return jsonify({'success': True, 'message': '服务正在重启...'}) 

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=12366, debug=False)