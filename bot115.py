# --- START OF FILE bot115.py ---

import requests
import os
import logging
from bs4 import BeautifulSoup
import time
import sqlite3
import json
import re
import schedule
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlsplit, parse_qs, urlparse, unquote
from p115client import P115Client
from p115client.exception import P115OSError, P115AuthenticationError

# === 尝试导入 Selenium ===
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_INSTALLED = True
except ImportError:
    SELENIUM_INSTALLED = False

try:
    from p115client import check_response
except ImportError:
    from p115client.tool import check_response
try:
    from p115client.tool import normalize_attr as normalize_attr_simple
except ImportError:
    # 兼容旧版本或直接定义一个简单的
    def normalize_attr_simple(attr):
        return attr

from dotenv import load_dotenv


class TransferResult:
    """
    智能结果类
    success: 用于 if 判断（兼容旧逻辑）
    message: 用于显示给用户的文字
    skipped: 【新】用于代码逻辑判断是否跳过
    """
    def __init__(self, success: bool, message: str = "", skipped: bool = False):
        self.success = success
        self.message = message
        self.skipped = skipped  

    def __bool__(self):
        return self.success

    def __str__(self):
        return self.message

logger = logging.getLogger(__name__)
banbenhao = "1.3.17" # 版本号：集成 ed2k 离线下载与 Telegraph 深度解析

# 加载.env文件中的环境变量
load_dotenv(dotenv_path="db/user.env", override=True)
load_dotenv(dotenv_path="sys.env", override=True)

# 配置部分
def get_int_env(env_name, default_value=0):
    try:
        value = os.getenv(env_name, str(default_value))
        return int(value) if value else default_value
    except (ValueError, TypeError):
        logger.warning(f"环境变量 {env_name} 值不是有效的整数，使用默认值 {default_value}")
        return default_value

CHANNEL_URL = os.getenv("ENV_115_TG_CHANNEL", "")
COOKIES = os.getenv("ENV_115_COOKIES", "")
UPLOAD_TARGET_PID = get_int_env("ENV_UPLOAD_PID", 0)
UPLOAD_TRANSFER_PID = get_int_env("ENV_115_UPLOAD_PID", 0)

TG_BOT_TOKEN = os.getenv("ENV_TG_BOT_TOKEN", "")
TG_ADMIN_USER_ID = get_int_env("ENV_TG_ADMIN_USER_ID", 0)

# 清理任务配置参数
CLEAN_TARGET_PID = os.getenv("ENV_115_CLEAN_PID", "0,0")
TRASH_PASSWORD = get_int_env("ENV_115_TRASH_PASSWORD", 0)

# === HDHive 配置 ===
HDHIVE_USERNAME = os.getenv("ENV_HDHIVE_USERNAME", "")
HDHIVE_PASSWORD = os.getenv("ENV_HDHIVE_PASSWORD", "")
HDHIVE_MAX_POINTS = get_int_env("ENV_HDHIVE_MAX_POINTS", 2) # 单个资源允许的最大积分消耗
HDHIVE_SESSION_FILE = os.path.join("db", "hdhive_session.json")

# 全局变量记录本次运行消耗的积分
hdhive_points_consumed_this_run = 0

# 数据库文件路径
DB_DIR = "db"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)
DATABASE_FILE = os.path.join(DB_DIR, "TG_monitor-115.db")
COOKIES_FILE = os.path.join(DB_DIR, "115_cookies.txt") 
CHECK_INTERVAL = get_int_env("ENV_CHECK_INTERVAL", 5)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
]
RETRY_TIMES = 3
TIMEOUT = 15

# 全局115客户端
client_115 = None

# 统计
stats = {
    "total_files": 0
}
# === HDHive 初始化标记 ===
HDHIVE_INIT_DONE = False

# === 类定义 ===

class TelegramNotifier:
    def __init__(self, bot_token, user_id):
        self.bot_token = bot_token
        self.user_id = user_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/" if self.bot_token else None

    def send_message(self, message):
        """向指定用户发送消息"""
        max_retries = 3
        retry_delay = 5

        if not self.bot_token:
            logger.error("未设置bot_token，跳过发送消息")
            return False
        if not message:
            return False
            
        success_count = 0
        params = {
            "chat_id": self.user_id,
            "text": message
        }

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{self.base_url}sendMessage",
                    params=params,
                    timeout=15
                )
                response.raise_for_status()
                result = response.json()
                if result.get("ok", False):
                    logger.info(f"消息已发送")
                    success_count += 1
                    break
                else:
                    logger.error(f"发送失败: {result}")
            except requests.exceptions.RequestException as e:
                logger.error(f"发送异常，重试中: {str(e)}")

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        return success_count > 0

class HDHiveManager:
    """HDHive 管理类"""
    def __init__(self, notifier=None):
        self.base_url = "https://hdhive.com"
        self.notifier = notifier
        self.cookies = {}
        self.tokens = {} 
        self.load_session()

    def load_session(self):
        """加载本地保存的会话信息"""
        if os.path.exists(HDHIVE_SESSION_FILE):
            try:
                with open(HDHIVE_SESSION_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cookies = data.get('cookies', {})
                    self.tokens = data.get('tokens', {})
                    for c in self.cookies.get('list', []):
                         if 'expiry' in c: c['expiry'] = int(c['expiry'])
            except Exception as e:
                logger.warning(f"加载 HDHive 会话失败: {e}")

    def save_session(self, driver_cookies):
        """保存会话信息"""
        try:
            tokens = {}
            cookie_dict = {}
            for c in driver_cookies:
                name = c.get('name')
                value = c.get('value')
                cookie_dict[name] = value
                if name == 'token':
                    tokens['token'] = value
                elif name == 'csrf_access_token':
                    tokens['csrf'] = value
            
            self.cookies = {'list': driver_cookies, 'dict': cookie_dict}
            self.tokens = tokens
            
            with open(HDHIVE_SESSION_FILE, 'w', encoding='utf-8') as f:
                json.dump({'cookies': self.cookies, 'tokens': self.tokens}, f)
            logger.info("HDHive 会话已保存")
        except Exception as e:
            logger.error(f"保存 HDHive 会话失败: {e}")

    def _create_driver(self):
        """创建配置好的 Chrome Driver"""
        if not SELENIUM_INSTALLED:
            raise ImportError("Selenium 未安装")
        
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--log-level=3') 
        chrome_options.add_argument(f'user-agent={USER_AGENTS[0]}')
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)
        return driver

    def login(self, driver):
        """在已有 driver 上执行登录动作"""
        if not HDHIVE_USERNAME or not HDHIVE_PASSWORD:
            logger.warning("[HDHive] 未配置 HDHive 用户名或密码，跳过登录")
            return False

        logger.info(f"[HDHive] 正在尝试登录... 用户: {HDHIVE_USERNAME}")
        try:
            driver.get(f"{self.base_url}/login")
            time.sleep(3)

            cookies = driver.get_cookies()
            if "token" in [c['name'] for c in cookies]:
                logger.info("[HDHive] Cookie 有效，无需重新登录")
                self.save_session(cookies)
                return True

            wait = WebDriverWait(driver, 10)
            username_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input[name='username']")))
            password_input = driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
            
            username_input.clear()
            username_input.send_keys(HDHIVE_USERNAME)
            password_input.clear()
            password_input.send_keys(HDHIVE_PASSWORD)
            
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_btn)
            
            logger.info("[HDHive] 提交登录，等待跳转...")
            time.sleep(5)
            cookies = driver.get_cookies()
            if "token" in [c['name'] for c in cookies] or driver.current_url == self.base_url:
                logger.info("[HDHive] 登录成功")
                self.save_session(cookies)
                return True
            else:
                logger.error(f"[HDHive] 登录失败，当前页面: {driver.current_url}")
                raise Exception("登录表单提交后未检测到有效 Session")

        except Exception as e:
            msg = f"HDHive 登录异常: {str(e)}"
            logger.error(msg)
            if self.notifier: self.notifier.send_message(f"⚠️ {msg}")
            return False

    def force_login(self):
        """强制启动一个新的浏览器实例进行登录"""
        if not SELENIUM_INSTALLED: return False
        
        driver = None
        try:
            logger.info("[HDHive] 启动独立浏览器实例进行登录修复...")
            driver = self._create_driver()
            # 先注入旧 Cookie 尝试
            driver.get(self.base_url)
            if self.cookies.get('list'):
                for c in self.cookies['list']:
                    try:
                        clean = {k: v for k, v in c.items() if k in ['name', 'value', 'path', 'domain', 'secure', 'expiry']}
                        if 'domain' not in clean: clean['domain'] = '.hdhive.com'
                        driver.add_cookie(clean)
                    except: pass
            
            return self.login(driver)
        except Exception as e:
            logger.error(f"[HDHive] 强制登录流程异常: {e}")
            return False
        finally:
            if driver: driver.quit()

    def check_in(self, report=False):
        """
        每日签到 / 保活检测
        :param report: 是否强制汇报结果（用于每日定时任务）
        """
        # 快速检查配置
        if not (HDHIVE_USERNAME and HDHIVE_PASSWORD) and not self.cookies:
            return

        if not HDHIVE_USERNAME or not HDHIVE_PASSWORD:
            return

        # 1. 如果完全没有 Token，先登录
        if not self.tokens.get('token'):
            logger.info("[HDHive] 本地无 Token，尝试立即登录...")
            if self.force_login():
                self.load_session()
            else:
                return

        # 2. 准备请求
        url = f"{self.base_url}/api/customer/user/checkin"
        headers = {
            "authority": "hdhive.com",
            "method": "POST",
            "path": "/api/customer/user/checkin",
            "scheme": "https",
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {self.tokens.get('token')}",
            "content-type": "application/json",
            "cookie": f"token={self.tokens.get('token')}; csrf_access_token={self.tokens.get('csrf')}",
            "origin": self.base_url,
            "referer": f"{self.base_url}/",
            "user-agent": USER_AGENTS[0],
            "x-csrf-token": self.tokens.get('csrf')
        }

        # 3. 执行请求（带重试逻辑）
        try:
            resp = requests.post(url, headers=headers, timeout=10)
            
            # === 处理 Token 失效 (关键保活逻辑) ===
            if resp.status_code in [401, 403]:
                logger.warning(f"[HDHive] 令牌已失效 (Status {resp.status_code})，正在执行自动保活/登录...")
                
                if self.force_login():
                    self.load_session()
                    logger.info("[HDHive] 保活成功：令牌已刷新")
                    
                    # 重新尝试签到
                    headers["authorization"] = f"Bearer {self.tokens.get('token')}"
                    headers["cookie"] = f"token={self.tokens.get('token')}; csrf_access_token={self.tokens.get('csrf')}"
                    headers["x-csrf-token"] = self.tokens.get('csrf')
                    resp = requests.post(url, headers=headers, timeout=10)
                else:
                    logger.error("[HDHive] 保活失败：无法重新登录")
                    return
            # ========================================

            data = resp.json()
            if data.get('success'):
                msg = f"✅ HDHive 签到成功: {data.get('message', 'OK')}"
                logger.info(msg)
                if self.notifier: self.notifier.send_message(msg)
            elif "签到过" in str(data.get('message', '')):
                msg = f"✅ [HDHive] 今日已签到 (Session有效)"
                logger.info(msg)
                # 【修改点】如果是每日定时报告，即使已签到也要发通知
                if report and self.notifier:
                    self.notifier.send_message(msg)
            else:
                msg = f"⚠️ [HDHive] 签到状态: {data.get('message')}"
                logger.info(msg)
                # 【修改点】异常状态也汇报
                if report and self.notifier:
                    self.notifier.send_message(msg)
                    
        except Exception as e:
            logger.error(f"[HDHive] 签到/保活请求异常: {e}")

    def parse_resource(self, url, message_url=None):
        """使用 Selenium 解析资源 (增强提取逻辑)"""
        global hdhive_points_consumed_this_run
        
        if not SELENIUM_INSTALLED:
            logger.error("❌ 未安装 Selenium，无法解析 HDHive")
            return []

        # 无配置/无会话时的快速拦截
        if not (HDHIVE_USERNAME and HDHIVE_PASSWORD) and not self.cookies:
            logger.warning(f"❌ [HDHive] 未配置账号密码且无有效会话文件，跳过解析: {url}")
            return []

        logger.info(f"🐝 [HDHive-Debug] 启动解析: {url}")
        driver = None
        found_links = []

        try:
            logger.info("  [HDHive-Debug] 正在启动 Chrome Driver...")
            driver = self._create_driver()
            
            # 注入 Cookie
            driver.get(self.base_url)
            if self.cookies.get('list'):
                for c in self.cookies['list']:
                    try: 
                        clean_cookie = {k: v for k, v in c.items() if k in ['name', 'value', 'path', 'domain', 'secure', 'expiry']}
                        if 'domain' not in clean_cookie: clean_cookie['domain'] = '.hdhive.com'
                        driver.add_cookie(clean_cookie)
                    except: pass
            
            driver.get(url)
            logger.info(f"  [HDHive-Debug] 页面加载完成. Title: '{driver.title}'")

            # 检查登录状态
            page_src = driver.page_source
            if "请先登录" in page_src or "login" in driver.current_url:
                logger.info("  [HDHive-Debug] 检测到未登录状态，尝试执行登录流程...")
                if self.login(driver):
                    logger.info("  [HDHive-Debug] 登录成功，刷新页面...")
                    driver.get(url) 
                else:
                    return []

            # === 尝试解锁 ===
            cost = 0
            try:
                logger.info("  [HDHive-Debug] 正在寻找解锁/支付按钮...")
                wait = WebDriverWait(driver, 8)
                
                xpath = "//button[contains(., '确定解锁') or contains(., '解锁') or contains(., 'Unlock') or contains(., '支付')]"
                button = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                
                if button:
                    logger.info(f"  [HDHive-Debug] 找到按钮: '{button.text.strip()}'")
                    
                    # === 积分检测 logic (正文优先) ===
                    current_page_text = driver.find_element(By.TAG_NAME, "body").text
                    points_match = re.search(r'需要使用\s*(\d+)\s*积分', current_page_text)
                    
                    if points_match:
                        cost = int(points_match.group(1))
                        logger.info(f"  [HDHive-Debug] 从页面提示中检测到费用: {cost} 积分")
                    else:
                        btn_match = re.search(r'(\d+)\s*积分', button.text)
                        if btn_match:
                            cost = int(btn_match.group(1))
                            logger.info(f"  [HDHive-Debug] 从按钮文本检测到费用: {cost} 积分")
                        else:
                            logger.info("  [HDHive-Debug] 未检测到明确的积分扣除提示，可能为免费或已解锁")

                    # === 单次消耗阈值检查 ===
                    source_info = f"\n消息内容: {message_url}" if message_url else ""
                    source_info += f"\n🔗 来源: {url}"

                    if cost > 0 and cost > HDHIVE_MAX_POINTS:
                         msg = f"🛑 [HDHive] 积分拦截: 此资源需 {cost} 积分 (超过单次上限 {HDHIVE_MAX_POINTS}){source_info}"
                         logger.warning(f"  [HDHive-Debug] 积分拦截: {cost} > {HDHIVE_MAX_POINTS}")
                         if self.notifier: self.notifier.send_message(msg)
                         return [] 
                    
                    logger.info("  [HDHive-Debug] 执行点击操作...")
                    driver.execute_script("arguments[0].click();", button)
                    
                    # 检测点击反馈
                    time.sleep(1.5)
                    if "积分不足" in driver.page_source:
                        msg = f"❌ [HDHive] 账户积分不足，无法解锁资源{source_info}"
                        logger.error(f"  [HDHive-Debug] 账户积分不足")
                        if self.notifier: self.notifier.send_message(msg)
                        return []
                        
                    # 等待跳转
                    logger.info("  [HDHive-Debug] 点击完成，等待页面更新...")
                    start_time = time.time()
                    while time.time() - start_time < 15:
                        curr = driver.current_url
                        src = driver.page_source
                        if any(d in curr for d in ['115.com', '115cdn.com', 'anxia.com']): 
                            logger.info(f"  [HDHive-Debug] 检测到目标跳转: {curr}")
                            break
                        if "password=" in src:
                            logger.info("  [HDHive-Debug] 检测到页面已刷新出包含密码的链接")
                            break
                        time.sleep(1)
                    
                    # 只有确实点击并消耗了积分才计费
                    if cost > 0:
                        hdhive_points_consumed_this_run += cost

            except TimeoutException:
                 logger.info("  [HDHive-Debug] 未触发点击流程(未找到按钮或已解锁)，继续尝试提取链接")
                 # 增加额外等待，防止免费资源加载慢
                 time.sleep(2)
            except Exception as e:
                logger.error(f"  [HDHive-Debug] 按钮交互过程异常: {e}")

            # === 提取链接 (增强版) ===
            final_url = driver.current_url
            page_source = driver.page_source
            
            # 1. 检查当前 URL 是否直接就是分享链接
            if any(d in final_url for d in ['115.com', '115cdn.com', 'anxia.com']):
                found_links.append(final_url)
            
            # 2. 正则匹配 (使用宽泛匹配)
            # 匹配 http(s)://...115...com/s/... 直到遇到空格、引号或尖括号
            patterns = [
                r'https?://[^\s"\'<>]*115[^\s"\'<>]*\/s\/[^\s"\'<>]+'
            ]
            
            regex_count = 0
            for p in patterns:
                matches = re.findall(p, page_source)
                if matches:
                    regex_count += len(matches)
                    found_links.extend(matches)
            
            # 3. DOM 扫描 (查找所有 href 属性包含 115 域名的 a 标签)
            try:
                logger.info("  [HDHive-Debug] 正在扫描 DOM 中的 <a> 标签...")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='115.com'], a[href*='115cdn.com'], a[href*='anxia.com']")
                for link in links:
                    href = link.get_attribute('href')
                    if href and '/s/' in href:
                        found_links.append(href)
                        logger.info(f"  [HDHive-Debug] DOM 发现链接: {href}")
            except Exception as e:
                logger.warning(f"  [HDHive-Debug] DOM 扫描异常: {e}")

            logger.info(f"  [HDHive-Debug] 提取链接总数 (去重前): {len(found_links)}")
            
            # 去重并过滤
            valid_links = []
            for link in set(found_links):
                # 再次确认是有效的分享格式
                if '/s/' in link:
                    valid_links.append(link)
            
            if not valid_links:
                logger.warning("  [HDHive-Debug] 未找到任何有效链接")

            # === 独立回复结果 ===
            source_info = f"\n消息内容: {message_url}" if message_url else ""
            source_info += f"\n🔗 来源: {url}"

            if valid_links:
                if cost > 0:
                    reply_msg = f"💰 [HDHive] 解析成功 (消耗 {cost} 积分){source_info}"
                else:
                    reply_msg = f"✅ [HDHive] 解析成功 (免费/已解锁){source_info}"
                
                if self.notifier:
                    self.notifier.send_message(reply_msg)
            else:
                logger.warning(f"  [HDHive-Debug] 解析流程结束，未提取到有效链接")

        except Exception as e:
            logger.error(f"  [HDHive-Debug] 全局解析异常: {e}", exc_info=True)
            if self.notifier:
                 self.notifier.send_message(f"❌ [HDHive] 系统异常: {str(e)[:50]}")
        finally:
            if driver: driver.quit()
            
        return valid_links

# === 新增：HDHive 保活任务 ===
def hdhive_keep_alive(report=False):
    """
    HDHive 定时保活任务 (每30分钟执行)
    :param report: 是否强制发送通知
    """
    try:
        if HDHIVE_USERNAME and HDHIVE_PASSWORD:
            action = "每日签到汇报" if report else "保活检查"
            logger.info(f"🔄 执行 HDHive {action}...")
            notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
            manager = HDHiveManager(notifier)
            # 传递 report 参数
            manager.check_in(report=report) 
    except Exception as e:
        logger.error(f"HDHive 保活任务异常: {e}")

# === 核心函数：115 客户端初始化 (还原版：仅支持 Cookies) ===

def init_115_client(retry: bool = False) -> P115Client:
    """初始化115客户端"""
    import time
    import re
    
    cookies = None
    
    def clean_cookie_str(raw_str):
        if not raw_str: return ""
        valid_keys = ['UID', 'CID', 'SEID', 'KID', 'acw_tc']
        pairs = []
        for key in valid_keys:
            match = re.search(fr'(?:^|[\s;:]){key}=([^;\s]+)', raw_str, re.IGNORECASE)
            if match: 
                val = match.group(1)
                if "Set-Cookie" not in val:
                    pairs.append(f"{key}={val}")
        return "; ".join(pairs)

    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                raw_data = f.read().strip()
                cookies = clean_cookie_str(raw_data)
                
            if cookies:
                logger.info(f"已加载持久化cookies (清洗后): {cookies[:20]}...")
            else:
                logger.warning("本地缓存文件内容无效，已忽略")
        except Exception as e:
            logger.warning(f"读取cookies文件失败：{e}")
            if os.path.exists(COOKIES_FILE):
                os.remove(COOKIES_FILE)
    
    if cookies:
        while True:
            try:
                client = P115Client(cookies=cookies, app='web', check_for_relogin=True)
                user_info = client.user_my_info()
                sync_cookies_to_files(client_115) 
                
                if isinstance(user_info, dict) and not user_info.get('state'):
                     raise P115AuthenticationError("Cookies已失效，需要重新获取")

                logger.info(f"115客户端初始化成功（使用持久化cookies） | ID: {client.user_id}")
                return client

            except Exception as e:
                err_str = str(e).lower()
                if "dictionary" in err_str or "sequence" in err_str or "expire" in err_str or "auth" in err_str or "errno 61" in err_str or "<html" in err_str:
                    logger.warning(f"本地Cookies不可用({e})，删除旧文件")
                    if os.path.exists(COOKIES_FILE):
                        os.remove(COOKIES_FILE)
                    break 
                else:
                    logger.warning(f"cookies检查发生未知异常，5秒后重试：{e}")
                    time.sleep(5) 
                
    try:
        env_cookies = os.getenv("ENV_115_COOKIES", "").strip()
        if not env_cookies:
             raise ValueError("环境变量 ENV_115_COOKIES 未配置")

        logger.info("尝试使用环境变量配置的 Cookie 初始化...")
        clean_env_cookies = clean_cookie_str(env_cookies)
        
        client = P115Client(cookies=clean_env_cookies, app='web', check_for_relogin=True)
        client.user_my_info()

        try:
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                f.write(clean_env_cookies)
        except Exception as write_e:
            logger.error(f"保存Cookie到文件失败: {write_e}")

        logger.info("115客户端初始化成功（使用环境变量）")
        return client

    except Exception as e:
        if not retry:
            logger.error(f"环境变量初始化失败：{e}，尝试重试...")
            return init_115_client(retry=True)
        logger.error(f"115客户端初始化彻底失败：{e}")
        raise

def init_database():
    """初始化数据库"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS messages
                 (msg_id INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, date TEXT, message_url TEXT, target_url TEXT, 
                   transfer_status TEXT, transfer_time TEXT, transfer_result TEXT)''')
    conn.commit()
    conn.close()

def is_message_processed(message_id):
    """
    检查消息是否已处理 
    (修改为使用 Telegram message_id 即 'id' 字段判断，而非 url)
    """
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        # id 字段存储的是 telegram 的 data-post 值，如 "channelname/123"
        result = conn.execute("SELECT 1 FROM messages WHERE id = ?", (message_id,)).fetchone()
        return result is not None
    except Exception as e:
        logger.error(f"查询数据库失败: {e}")
        return False
    finally:
        conn.close()

def save_message(message_id, date, message_url, target_url,
                 status="待转存", result="", transfer_time=None):
    """保存消息到数据库"""
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        conn.execute("INSERT INTO messages (id, date, message_url, target_url, transfer_status, transfer_time, transfer_result) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (message_id, date, message_url, target_url,
                      status, transfer_time or datetime.now().isoformat(), result))
        conn.commit()
        logger.info(f"已记录: {message_id} | 状态: {status}")
    except sqlite3.IntegrityError:
        # 如果 id 已存在（虽然 is_message_processed 应该拦截了，但双重保险）
        conn.execute("UPDATE messages SET transfer_status=?, transfer_result=?, transfer_time=? WHERE id=?",
                     (status, result, transfer_time or datetime.now().isoformat(), message_id))
        conn.commit()
    finally:
        conn.close()

# === 辅助函数 ===

def validate_url(url):
    try:
        parsed = urlparse(url)
        if not parsed.scheme: url = f"https://{url}"
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc: return None
        return url
    except: return None

# === 替换原来的 add_offline_task 函数 ===
def add_offline_task(client, link, pid):
    """
    添加离线任务 (ed2k/magnet)
    返回 TransferResult，携带"已存在"状态
    """
    try:
        payload = {
            'url': link, 'uid': client.user_id,
            'save_path_cid': pid, 'wp_path_id': pid, 'cid': pid
        }
        
        res = None
        if hasattr(client, 'offline_add_url'): res = client.offline_add_url(payload)
        elif hasattr(client, 'offline_add_urls'): res = client.offline_add_urls(payload)
        elif hasattr(client, 'download_add_url'):
             try: res = client.download_add_url(payload)
             except: res = client.download_add_url(url=link, cid=pid)

        if isinstance(res, list) and len(res) > 0: res = res[0]
            
        if isinstance(res, dict):
            if res.get('state'):
                logger.info(f"ed2k离线任务添加成功: {link[:50]}...")
                return TransferResult(True, "✅ ed2k离线任务添加成功", skipped=False)
            
            # 2. 已存在 (skipped=True)
            err_msg = res.get('error_msg') or res.get('message') or str(res)
            if res.get('errNo') == 10008 or '存在' in str(err_msg) or 'exists' in str(err_msg):
                logger.info(f"ed2k离线任务已存在 (跳过): {link[:50]}...")
                return TransferResult(True, "🔄 ed2k离线任务已存在 (跳过)", skipped=True)
                
            logger.error(f"ed2k离线任务添加失败: {err_msg}")
            return TransferResult(False, f"❌ 失败: {err_msg}")
        else:
            return TransferResult(False, f"❌ API异常: {res}")

    except Exception as e:
        logger.error(f"ed2k离线任务添加异常: {e}")
        return TransferResult(False, f"❌ 异常: {str(e)}")

def parse_telegraph_page(url: str) -> list:
    """解析 Telegraph 页面 (支持 ed2k)"""
    try:
        logger.info(f"📄 解析 Telegraph: {url}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        links = []
        # 1. 提取超链接 (http 和 ed2k)
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http'): 
                links.append(href)
            elif href.startswith('ed2k://'):
                links.append(href)
        
        # 2. 扫描纯文本中的 ed2k 链接
        text_content = soup.get_text()
        ed2k_links = re.findall(r'ed2k://\|file\|.+?\|/', text_content, re.IGNORECASE)
        links.extend(ed2k_links)
        
        return list(set(links))
    except Exception as e:
        logger.error(f"Telegraph 解析失败: {e}")
        return []

def parse_hdhive_with_selenium(url: str, message_url=None):
    """解析 HDHive 页面 (代理给 Manager 处理)"""
    notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
    manager = HDHiveManager(notifier)
    return manager.parse_resource(url, message_url)

def get_latest_messages():
    """获取最新消息"""
    try:
        channel_urls = os.getenv("ENV_115_TG_CHANNEL", "").split('|')
        if not channel_urls or channel_urls == ['']:
            logger.warning("未配置ENV_115_TG_CHANNEL环境变量")
            return []
            
        all_new_messages = []
        
        for channel_idx, channel_url in enumerate(channel_urls):
            channel_url = channel_url.strip()
            if not channel_url:
                continue

            if channel_url.startswith('https://t.me/') and '/s/' not in channel_url:
                channel_name = channel_url.split('https://t.me/')[-1]
                channel_url = f'https://t.me/s/{channel_name}'

            logger.info(f"===== 处理频道: {channel_url} =====")
            
            session = requests.Session()
            retry = Retry(total=RETRY_TIMES, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
            session.mount("https://", HTTPAdapter(max_retries=retry))
            headers = {"User-Agent": USER_AGENTS[int(time.time()) % len(USER_AGENTS)]}
            response = session.get(channel_url, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            message_divs = soup.find_all('div', class_='tgme_widget_message')
            total = len(message_divs)
            logger.info(f"共解析到{total}条消息（最新的在最后）")

            channel_new_count = 0 

            for i in range(total):
                msg_index = total - 1 - i
                msg = message_divs[msg_index]
                # data-post 是唯一ID (如 channelname/123)
                data_post = msg.get('data-post', '')
                message_id = data_post if data_post else f"未知ID_{msg_index}"
                
                logger.info(f"检查第{i + 1}新消息（ID: {message_id}）")

                # === 关键修改：使用 message_id 进行去重 ===
                if is_message_processed(message_id):
                    logger.info(f"消息 {message_id} 已处理，跳过")
                    continue
                # ========================================

                time_elem = msg.find('time')
                date_str = time_elem.get('datetime') if time_elem else datetime.now().isoformat()
                link_elem = msg.find('a', class_='tgme_widget_message_date')
                message_url = f"{link_elem.get('href').lstrip('/')}" if link_elem else ''
                
                text_elem = msg.find('div', class_='tgme_widget_message_text')
                message_text = ""
                if text_elem:
                    message_text = text_elem.get_text(strip=True).replace('\n', ' ')
                
                target_urls = extract_target_url(f"{msg}", message_url)
                
                if target_urls:
                    for url in target_urls:
                        # 如果 URL 为空（被拦截），但我们需要标记此消息已处理
                        # 否则下次还会尝试解析
                        if not url:
                            save_message(message_id, date_str, message_url, "BLOCKED", "被拦截/无效")
                            continue

                        # 正常的有效链接
                        all_new_messages.append((message_id, date_str, message_url, url, message_text))
                        channel_new_count += 1
                        logger.info(f"发现新链接: {url}")
            
            logger.info(f"发现{channel_new_count}条新的115分享链接")
        
        all_new_messages.sort(key=lambda x: x[1])
        logger.info(f"===== 所有频道共发现{len(all_new_messages)}条新的115分享链接 =====")
        return all_new_messages

    except requests.exceptions.RequestException as e:
        logger.error(f"网络请求失败: {str(e)[:100]}")
        return []

def extract_target_url(text, message_url=None):
    """提取目标 115 链接 (包含 ed2k 支持)"""
    results = []
    
    # 1. 优先提取 ed2k 链接
    ed2k_pattern = r'ed2k://\|file\|.+?\|/'
    ed2k_matches = re.findall(ed2k_pattern, text, re.IGNORECASE)
    if ed2k_matches:
        results.extend([m.strip() for m in ed2k_matches])

    # 2. 提取 115 分享链接
    p115_pattern = r'https?:\/\/(?:115|115cdn|anxia)\.com\/s\/\w+\?password\=\w+'
    matches = re.findall(p115_pattern, text, re.IGNORECASE | re.DOTALL)
    
    if matches:
        for match in matches:
            results.append(match.strip())
    
    intermediate_links = set()
    
    tg_matches = re.findall(r'https?://telegra\.ph/[^\s"\'<>]+', text, re.IGNORECASE)
    for m in tg_matches:
        v = validate_url(m)
        if v: intermediate_links.add(v)
        
    hd_matches = re.findall(r'https?://(?:www\.)?hdhive\.com/resource/[a-zA-Z0-9]+', text, re.IGNORECASE)
    for m in hd_matches:
        v = validate_url(m)
        if v: intermediate_links.add(v)
        
    for link in intermediate_links:
        parsed_links = []
        if 'telegra.ph' in link:
            parsed_links = parse_telegraph_page(link)
        elif 'hdhive.com' in link:
            # 传递 message_url，HDHive 保持原样仅提取 115 分享
            parsed_links = parse_hdhive_with_selenium(link, message_url)
            # 如果解析结果为空（例如被拦截），返回 [None] 以便上层处理记录
            if not parsed_links:
                results.append(None)

        if parsed_links:
            for pl in parsed_links:
                pl = pl.strip()
                # 检查是否为 ed2k
                if pl.startswith('ed2k://'):
                    results.append(pl)
                else:
                    # 检查是否为 115 链接
                    pl_matches = re.findall(p115_pattern, pl, re.IGNORECASE)
                    if pl_matches:
                        for pm in pl_matches:
                            results.append(pm.strip())
                            logger.info(f"🔗 从中间页 {link} 解析出 115 链接: {pm.strip()}")

    # 结果去重
    valid_links = list(dict.fromkeys([r for r in results if r]))
    if None in results:
        valid_links.append(None)
        
    return valid_links

def parse_share_link(link):
    """从链接中解析 share_code 和 receive_code"""
    match = re.search(r'https?:\/\/(?:115|115cdn|anxia)\.com\/s\/(\w+)\?password\=(\w+)', link, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return match.group(1), match.group(2)

# === 替换原来的 transfer_shared_link 函数 ===
def transfer_shared_link(client: P115Client, share_url: str, target_pid: int):
    """
    转存 115 分享链接 (原生请求版 + 智能结果返回)
    """
    import json, requests, time, re
    
    if not share_url or not isinstance(share_url, str):
        return TransferResult(False, "无效链接")
    share_url = share_url.strip()

    # ed2k 分流 -> 直接返回 add_offline_task 的结果对象
    if share_url.startswith('ed2k://'):
        return add_offline_task(client, share_url, target_pid)
    
    if share_url.startswith('magnet:?'):
        return TransferResult(False, "磁力链已忽略")

    def get_cookie_str(c):
        if isinstance(c, str): raw = c
        elif hasattr(c, 'get_dict'): raw = "; ".join([f"{k}={v}" for k, v in c.get_dict().items()])
        else: raw = str(c)
        
        valid_keys = ['UID', 'CID', 'SEID', 'KID', 'acw_tc']
        pairs = []
        for key in valid_keys:
            # === 优化点：兼容 key="value" 格式，并排除分号和引号 ===
            match = re.search(fr'(?:^|[\s;]){key}=(?:"?)([^;"\s]+)(?:"?)', raw, re.IGNORECASE)
            if match: 
                val = match.group(1)
                if "Set-Cookie" not in val and "HttpOnly" not in val:
                    pairs.append(f"{key}={val}")
        return "; ".join(pairs)

    try:
        clean_cookie = get_cookie_str(client.cookies)
        share_info = parse_share_link(share_url)
        if not share_info: return TransferResult(False, "链接格式错误")
        share_code, receive_code = share_info
        
        # 获取文件列表 (逻辑不变)
        file_ids = []
        offset = 0
        limit = 100 
        while True:
            url = "https://webapi.115.com/share/snap"
            params = {"share_code": share_code, "receive_code": receive_code, "offset": offset, "limit": limit}
            headers = {"User-Agent": USER_AGENTS[0], "Cookie": clean_cookie, "Referer": "https://115.com/", "Origin": "https://115.com"}
            try:
                r = requests.get(url, params=params, headers=headers, timeout=10)
                resp = r.json()
            except Exception as e:
                return TransferResult(False, f"网络异常: {e}")

            if not resp.get('state'):
                return TransferResult(False, f"获取列表失败: {resp.get('error', '未知')}")
                
            data = resp.get('data', {})
            count = data.get('count', 0)
            file_list = data.get('list', [])
            if not file_list: break
            for item in file_list:
                fid = item.get('fid') or item.get('cid')
                if fid: file_ids.append(fid)
            if len(file_ids) >= count: break
            offset += len(file_list)
            time.sleep(0.3)

        if not file_ids:
            return TransferResult(False, "无有效文件")

        # 执行转存
        BATCH_SIZE = 50
        total_success = 0
        url_rec = "https://webapi.115.com/share/receive"
        headers_rec = {
            "User-Agent": USER_AGENTS[0], "Cookie": clean_cookie, 
            "Content-Type": "application/x-www-form-urlencoded", "Referer": "https://115.com/", "Origin": "https://115.com"
        }

        for i in range(0, len(file_ids), BATCH_SIZE):
            batch = file_ids[i : i + BATCH_SIZE]
            file_id_str = ",".join(map(str, batch))
            payload = {"user_id": client.user_id, "share_code": share_code, "receive_code": receive_code, "file_id": file_id_str, "cid": str(target_pid)}
            try:
                r = requests.post(url_rec, data=payload, headers=headers_rec, timeout=15)
                res_json = r.json()
                if res_json.get('state') or "无需重复" in res_json.get('error', ''):
                    total_success += len(batch)
            except: pass
            time.sleep(1)

        if total_success == len(file_ids):
            return TransferResult(True, f"✅ 115网盘转存成功")
        elif total_success > 0:
            return TransferResult(True, f"⚠️ 115网盘部分转存 ({total_success}/{len(file_ids)})")
        else:
            return TransferResult(False, "❌ 115网盘转存全部失败")

    except Exception as e:
        logger.error(f"115网盘转存异常: {e}")
        return TransferResult(False, f"❌ 异常: {str(e)}")

def print_progress(msg, indent=0):
    """带缩进的进度输出"""
    prefix = "  " * indent
    logger.info(f"{prefix}[{time.strftime('%H:%M:%S')}] {msg}")

def transfer_and_clean():
    """递归转移文件并清理空目录"""
    global stats
    if not client_115:
        init_115_client()
    client = client_115

    def recursive_transfer(current_pid: int, depth=0):
        try:
            dir_info = client.fs_files(cid=current_pid, limit=1)
            dir_name = f"目录#{current_pid}"
            if dir_info.get("path"):
                 dir_name = dir_info["path"][-1]["name"]
        except:
            dir_name = f"目录#{current_pid}"
        
        print_progress(f"扫描目录: {dir_name} ({current_pid})", depth)

        items = []
        offset = 0
        limit = 1000
        while True:
            try:
                resp = client.fs_files(cid=current_pid, limit=limit, offset=offset)
                check_response(resp)
                data = resp.get("data", [])
                if isinstance(data, dict):
                    page_items = data.get("list", [])
                else:
                    page_items = data
                items.extend(page_items)
                if len(page_items) < limit: break
                offset += limit
                print_progress(f"  读取分页: {offset / limit + 1}", depth + 1)
            except Exception as e:
                print_progress(f"⚠️ 获取目录内容失败: {str(e)}", depth + 1)
                break

        print_progress(f"发现 {len(items)} 个项目", depth + 1)

        files = [item for item in items if not normalize_attr_simple(item)["is_dir"]]
        dirs = [item for item in items if normalize_attr_simple(item)["is_dir"]]

        for i, file in enumerate(files, 1):
            normalized = normalize_attr_simple(file)
            file_name = normalized.get("name", f"文件#{normalized['id']}")
            progress = f"{i}/{len(files)}"
            try:
                move_resp = client.fs_move(normalized["id"], UPLOAD_TARGET_PID)
                if not move_resp.get('state'):
                     raise P115OSError(move_resp.get('error'))
                print_progress(f"✅ 移动文件: {file_name} ({progress})", depth + 1)
                stats["total_files"] += 1
            except Exception as e:
                print_progress(f"❌ 移动失败: {file_name} ({progress}) - {str(e)}", depth + 1)
            time.sleep(0.2)

        for directory in dirs:
            dir_id = normalize_attr_simple(directory)["id"]
            if dir_id == UPLOAD_TARGET_PID: continue
            recursive_transfer(dir_id, depth + 1)

        try:
            after_resp = client.fs_files(cid=current_pid, limit=10)
            check_response(after_resp)
            data_after = after_resp.get("data", [])
            items_after = data_after.get("list", []) if isinstance(data_after, dict) else data_after

            if (not items_after
                    and current_pid != UPLOAD_TARGET_PID
                    and current_pid != UPLOAD_TRANSFER_PID):
                del_resp = client.fs_delete(current_pid)
                check_response(del_resp)
                print_progress(f"🗑️ 删除空目录: {dir_name} ({current_pid})", depth)
                time.sleep(1)
        except Exception as e:
            print_progress(f"⚠️ 删除目录失败: {dir_name} ({current_pid}) - {str(e)}", depth)

    if UPLOAD_TRANSFER_PID == 0:
        raise ValueError("转移目录ID不能为0")

    logger.info("===== 开始文件转移和目录清理 =====")
    logger.info(f"源目录: {UPLOAD_TRANSFER_PID}")
    logger.info(f"目标目录: {UPLOAD_TARGET_PID}")
    try:
        recursive_transfer(UPLOAD_TRANSFER_PID)
    except KeyboardInterrupt:
        logger.warning("\n⚠️ 操作被用户中断")
    finally:
        logger.info("===== 操作完成 =====")
        logger.info(f"程序自启动后共转存文件数: {stats['total_files']}")

def clean_task():
    """执行清理任务"""
    target_pids = [pid.strip() for pid in CLEAN_TARGET_PID.split(",") if pid.strip()]
    if not target_pids:
        logger.warning("未配置有效目标文件夹ID，不执行清理操作")
        return

    if not client_115:
        init_115_client()
    client = client_115

    try:
        for cid in target_pids:
            logger.info(f"开始清理文件夹 {cid} 内的内容...")
            offset = 0
            limit = 100
            while True:
                try:
                    resp = client.fs_files(cid=cid, limit=limit, offset=offset)
                    check_response(resp)
                    data = resp.get("data", [])
                    contents = data.get("list", []) if isinstance(data, dict) else data
                    if not contents:
                        logger.info(f"文件夹 {cid} 内无内容，清理完成")
                        break
                    for item in contents:
                        normalized_item = normalize_attr_simple(item)
                        item_id = normalized_item.get("id")
                        item_name = normalized_item.get("name", "未知名称")
                        if not item_id: continue
                        try:
                            logger.info(f"删除: {item_name} (ID: {item_id})")
                            client.fs_delete(item_id)
                            time.sleep(0.5)
                        except Exception as e:
                            logger.error(f"删除 {item_name} 失败: {str(e)}")
                    if len(contents) < limit:
                        logger.info(f"文件夹 {cid} 内容已全部清理")
                        break
                    offset += limit
                except Exception as e:
                    logger.error(f"获取文件夹 {cid} 内容失败: {str(e)}")
                    break

        logger.info("开始清空回收站...")
        try:
            client.fs_recyclebin_clean(password=TRASH_PASSWORD)
        except AttributeError:
            client.recyclebin_clean(password=TRASH_PASSWORD)
        logger.info("回收站清空完成")
    except Exception as e:
         logger.error(f"清理任务异常: {e}")

def tg_115monitor():
    # 引用全局变量
    global client_115, HDHIVE_INIT_DONE
    
    init_database()
    client = init_115_client()
    client_115 = client

    notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
    logger.info(f"===== 开始检查 115（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）=====")
    
    # HDHive 保活任务初始化 (仅执行一次)
    if not HDHIVE_INIT_DONE:
        try:
            if HDHIVE_USERNAME and HDHIVE_PASSWORD:
                logger.info("⚙️ 初始化 HDHive 保活与签到任务...")
                
                # 任务1: 每30分钟保活 (静默执行，仅首次成功通知)
                schedule.every(30).minutes.do(hdhive_keep_alive, report=False)
                
                # 任务2: 每天 09:00 强制执行并汇报 (无论成功还是已签到，都发消息)
                schedule.every().day.at("01:00").do(hdhive_keep_alive, report=True)
                
                # 立即执行一次 (启动时静默检查)
                hdhive_keep_alive(report=False)
            else:
                logger.info("未配置 HDHive 账号，跳过保活初始化")
        except Exception as e:
            logger.error(f"HDHive 初始化失败: {e}")
        finally:
            HDHIVE_INIT_DONE = True

    # 执行定时任务 (HDHive保活)
    schedule.run_pending()
    
    new_messages = get_latest_messages()
    
    if new_messages:
        for msg in new_messages:
            message_id, date_str, message_url, target_url, message_text = msg
            logger.info(f"处理新消息: {message_id} | {target_url}")

            # 调用转存 (TransferResult 对象)
            result = transfer_shared_link(client, target_url, UPLOAD_TRANSFER_PID)
            
            # 直接使用 result.message 获取详细文案
            if result:
                status = "处理成功"
                result_msg = f"{result.message}\n消息内容: {message_url}\n链接: {target_url}"
            else:
                status = "处理失败"
                result_msg = f"{result.message}\n消息内容: {message_url}\n链接: {target_url}"

            notifier.send_message(result_msg)
            save_message(message_id, date_str, message_url, target_url, status, result_msg)
    else:
        logger.info("未发现新的115分享链接")
        
    sync_cookies_to_files(client)

def sync_cookies_to_files(client):
    import re
    import os
    if not client: return
    try:
        raw_data = ""
        if hasattr(client.cookies, 'get_dict'):
            d = client.cookies.get_dict()
            raw_data = "; ".join([f"{k}={v}" for k, v in d.items()])
        elif isinstance(client.cookies, dict):
            raw_data = "; ".join([f"{k}={v}" for k, v in client.cookies.items()])
        else:
            raw_data = str(client.cookies)

        target_keys = ['UID', 'CID', 'SEID', 'KID', 'acw_tc']
        clean_pairs = []
        for key in target_keys:
            match = re.search(fr'(?:^|[\s;:]){key}=([^;\s]+)', raw_data, re.IGNORECASE)
            if match:
                value = match.group(1)
                if 'Set-Cookie' not in value:
                    clean_pairs.append(f"{key}={value}")

        if not clean_pairs: return
        new_cookies = "; ".join(clean_pairs)

        try:
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write(new_cookies)
        except Exception as e:
            logger.error(f"写入txt缓存失败: {e}")
        
        env_path = "db/user.env"
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                new_lines = []
                key_found = False
                for line in lines:
                    if line.strip().startswith("ENV_115_COOKIES"):
                        new_lines.append(f"ENV_115_COOKIES='{new_cookies}'\n")
                        key_found = True
                    else:
                        new_lines.append(line)
                if not key_found:
                    new_lines.append(f"\nENV_115_COOKIES='{new_cookies}'\n")
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
            except Exception as e:
                logger.error(f"写入user.env失败: {e}")
    except Exception as e:
        logger.error(f"同步 Cookie 全局失败: {e}")

def main():
    # schedule.every().day.at("04:00").do(clean_task)
    try:       
        while True:
            tg_115monitor()
            time.sleep(CHECK_INTERVAL * 60)
    except KeyboardInterrupt:
        logger.info("程序已停止")
    except Exception as e:
        logger.error(f"程序异常终止: {str(e)}")

if __name__ == "__main__":
    
    main()
