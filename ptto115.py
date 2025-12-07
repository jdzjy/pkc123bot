import os
import time
import json
import logging
import hashlib
import requests
from dotenv import load_dotenv

# --- P115Client 升级部分 ---
from p115client import P115Client
# 引入异常类
from p115client.exception import P115AuthenticationError

# 假设 p123client 已经安装
from p123client import P123Client

logger = logging.getLogger(__name__)

# 加载.env文件中的环境变量
load_dotenv(dotenv_path="db/user.env", override=True)
load_dotenv(dotenv_path="sys.env", override=True)

# 安全地获取整数值
def get_int_env(env_name, default_value=0):
    try:
        value = os.getenv(env_name, str(default_value))
        return int(value) if value else default_value
    except (ValueError, TypeError):
        # 这里的 TelegramNotifier 调用需要稍后实例化，为了避免循环引用或未定义，这里仅打印日志
        logger.warning(f"环境变量 {env_name} 值不是有效的整数，使用默认值 {default_value}")
        return default_value

# ======================== 环境变量配置 ========================
version = "1.0.6" # 修正完善版
TG_BOT_TOKEN = os.getenv("ENV_TG_BOT_TOKEN", "")
TG_ADMIN_USER_ID = get_int_env("ENV_TG_ADMIN_USER_ID", 0)

# 秒传功能开关
PTTO123_SWITCH = get_int_env("ENV_PTTO123_SWITCH", 0)
PTTO115_SWITCH = get_int_env("ENV_PTTO115_SWITCH", 0)

# 最大尝试次数
TRY_MAX_COUNT = 999999

try:
    # 读取115 cookies
    COOKIES = os.getenv("ENV_115_COOKIES", "")

    # 读取上传目标目录ID
    PTTO123_UPLOAD_PID = get_int_env("ENV_PTTO123_UPLOAD_PID", 0)
    PTTO115_UPLOAD_PID = get_int_env("ENV_PTTO115_UPLOAD_PID", 0)

except (ValueError, TypeError) as e:
    logger.error(f"环境变量错误：{e}")
    exit(1)

# ======================== 其他固定配置 ========================
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "upload")
SLEEP_AFTER_FILE = 10
SLEEP_AFTER_ROUND = 60

# 数据库/配置目录
DB_DIR = "db"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

# 115 Cookie 缓存文件
COOKIES_FILE = os.path.join(DB_DIR, "115_cookies.txt")

# 全局115客户端
client_115 = None

# ======================== TG 通知类 ========================
class TelegramNotifier:
    def __init__(self, bot_token, user_id):
        self.bot_token = bot_token
        self.user_id = user_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/" if self.bot_token else None

    def send_message(self, message):
        """发送消息"""
        max_retries = 30
        retry_delay = 60

        if not self.bot_token:
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
            except requests.exceptions.RequestException:
                pass

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        return success_count > 0
    
def sync_cookies_to_files(client):
    """
    将当前内存中最新的 Cookie 同步写入到 115_cookies.txt 和 db/user.env
    (白名单清洗版：只提取核心字段，安全地写入配置文件)
    """
    import re
    import os
    
    # 全局变量定义检查
    # 确保 COOKIES_FILE 指向 "db/115_cookies.txt"
    # 如果代码上下文没有定义 COOKIES_FILE，请取消下面这行的注释:
    # COOKIES_FILE = os.path.join("db", "115_cookies.txt")

    if not client:
        return

    try:
        # 1. 获取原始 Cookie 数据（兼容各种类型）
        raw_data = ""
        if hasattr(client.cookies, 'get_dict'):
            # 如果是 CookieJar
            d = client.cookies.get_dict()
            raw_data = "; ".join([f"{k}={v}" for k, v in d.items()])
        elif isinstance(client.cookies, dict):
            # 如果是字典
            raw_data = "; ".join([f"{k}={v}" for k, v in client.cookies.items()])
        else:
            # 如果是字符串或其他
            raw_data = str(client.cookies)

        # 2. 定义115必须的核心字段白名单 (只保留这些，过滤 Set-Cookie 等垃圾)
        target_keys = ['UID', 'CID', 'SEID', 'KID', 'acw_tc']
        
        clean_pairs = []
        
        # 3. 使用正则提取 "Key=Value"
        for key in target_keys:
            # 忽略大小写匹配 Key=Value，排除前面的 Set-Cookie 前缀
            match = re.search(fr'(?:^|[\s;:]){key}=([^;\s]+)', raw_data, re.IGNORECASE)
            if match:
                value = match.group(1)
                # 二次检查：防止值里面包含 Set-Cookie
                if 'Set-Cookie' not in value:
                    clean_pairs.append(f"{key}={value}")

        # 如果没有提取到有效字段，说明数据异常，不执行写入
        if not clean_pairs:
            return

        new_cookies = "; ".join(clean_pairs)

        # 4. 写入本地缓存文件 (db/115_cookies.txt)
        try:
            with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                f.write(new_cookies)
        except Exception as e:
            logger.error(f"写入txt缓存失败: {e}")
        
        # 5. 写入配置文件 (db/user.env)
        env_path = "db/user.env"
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                new_lines = []
                key_found = False
                for line in lines:
                    if line.strip().startswith("ENV_115_COOKIES"):
                        # 使用单引号包裹，确保格式正确
                        new_lines.append(f"ENV_115_COOKIES='{new_cookies}'\n")
                        key_found = True
                    else:
                        new_lines.append(line)
                
                # 如果原文件没有这个变量，追加到末尾
                if not key_found:
                    new_lines.append(f"\nENV_115_COOKIES='{new_cookies}'\n")
                    
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
            except Exception as e:
                logger.error(f"写入user.env失败: {e}")
                
    except Exception as e:
        logger.error(f"同步 Cookie 全局失败: {e}")    

# ======================== 客户端初始化逻辑 ========================
def init_115_client(retry: bool = False) -> P115Client:
    """
    初始化115客户端 (读取时自动清洗脏数据版)
    """
    import time
    import re
    
    cookies = None
    
    # --- 内部清洗函数 ---
    def clean_cookie_str(raw_str):
        if not raw_str: return ""
        # 提取核心字段 (UID, CID, SEID, KID)
        # 这个正则会忽略 Set-Cookie 前缀和换行符，只抓取 Key=Value
        valid_keys = ['UID', 'CID', 'SEID', 'KID', 'acw_tc']
        pairs = []
        for key in valid_keys:
            # 匹配 Key=Value，忽略前面的 Set-Cookie: 或换行
            match = re.search(fr'(?:^|[\s;:]){key}=([^;\s]+)', raw_str, re.IGNORECASE)
            if match: 
                val = match.group(1)
                # 再次防御 Set-Cookie 出现在值中
                if "Set-Cookie" not in val:
                    pairs.append(f"{key}={val}")
        return "; ".join(pairs)
    # --------------------

    # 1. 尝试加载持久化的 cookies
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                raw_data = f.read().strip()
                # 关键：读取后立即清洗
                cookies = clean_cookie_str(raw_data)
                
            if cookies:
                logger.info(f"已加载持久化cookies (清洗后): {cookies[:20]}...")
            else:
                logger.warning("本地缓存文件内容无效，已忽略")
                
        except Exception as e:
            logger.warning(f"读取cookies文件失败：{e}")
            if os.path.exists(COOKIES_FILE):
                os.remove(COOKIES_FILE)
    
    # 2. 尝试使用持久化 cookies 初始化
    if cookies:
        while True:
            try:
                client = P115Client(cookies=cookies, app='web', check_for_relogin=True)
                
                user_info = client.user_my_info()
                sync_cookies_to_files(client_115) 
                
                if isinstance(user_info, dict) and not user_info.get('state'):
                    logger.info("检测到本地cookies已失效，将重新获取")
                    if os.path.exists(COOKIES_FILE):
                        os.remove(COOKIES_FILE)
                    break 
                else:
                    logger.info(f"115客户端初始化成功（使用持久化cookies） | ID: {client.user_id}")
                    return client

            except Exception as e:
                err_str = str(e).lower()
                if "dictionary" in err_str or "sequence" in err_str or "expire" in err_str or "auth" in err_str:
                    logger.warning(f"本地Cookies不可用({e})，删除旧文件")
                    if os.path.exists(COOKIES_FILE):
                        os.remove(COOKIES_FILE)
                    break 
                else:
                    logger.warning(f"cookies检查发生未知异常，5秒后重试：{e}")
                    time.sleep(5) 
                
    # 3. 通过环境变量获取
    try:
        env_cookies = os.getenv("ENV_115_COOKIES", "").strip()
        if not env_cookies:
             raise ValueError("环境变量 ENV_115_COOKIES 未配置")

        logger.info("尝试使用环境变量配置的 Cookie 初始化...")
        # 清洗环境变量中的 Cookie
        clean_env_cookies = clean_cookie_str(env_cookies)
        
        client = P115Client(cookies=clean_env_cookies, app='web', check_for_relogin=True)
        client.user_my_info()

        # 4. 初始化成功，保存到文件
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

CLIENT_ID = os.getenv("ENV_123_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("ENV_123_CLIENT_SECRET", "")

def init_123_client(retry: bool = False) -> P123Client:
    token_path = os.path.join(DB_DIR, "config.txt")
    token = None
    
    # 尝试加载持久化的token
    if os.path.exists(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
            logger.info("已加载持久化token")
        except Exception as e:
            logger.warning(f"读取token文件失败：{e}，将重新获取")
    
    # 尝试使用token初始化客户端
    if token:
        try:
            client = P123Client(token=token)
            res = client.user_info()
            if res.get('code') != 0 or res.get('message') != "ok":
                notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
                notifier.send_message("123 token过期，将重新获取")
                if os.path.exists(token_path):
                    os.remove(token_path)
            else:
                return client
        except Exception as e:
            if "token is expired" in str(e).lower():
                logger.info("检测到token过期，将重新获取")
            else:
                logger.warning(f"token无效或初始化失败：{e}")
            if os.path.exists(token_path):
                os.remove(token_path)
    try:
        client = P123Client(CLIENT_ID, CLIENT_SECRET)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(client.token)
        logger.info("123客户端初始化成功（使用新获取的token）")
        return client
    except Exception as e:
        if not retry:
            logger.error(f"获取token失败：{e}，尝试重试...")
            return init_123_client(retry=True)
        raise

# ======================== 工具函数 ========================

def check_file_size_stability(file_path, check_interval=30, max_attempts=1000):
    """检查文件大小稳定性"""
    for attempt in range(max_attempts):
        size1 = os.path.getsize(file_path)
        time.sleep(check_interval)
        size2 = os.path.getsize(file_path)
        if size1 == size2:
            return True
        logger.warning(f"文件大小不稳定，第 {attempt + 1} 次检查：{file_path}")
    logger.error(f"文件大小不稳定，放弃上传：{file_path}")
    return False

def fast_md5(file_path: str) -> str:
    """快速计算文件MD5"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()

# ======================== 核心逻辑 ========================
def ptto123process():
    global client_115
    notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
    
    if PTTO123_SWITCH and PTTO115_SWITCH:
        order_desc = "先尝试123秒传，再尝试115秒传"
    elif PTTO123_SWITCH:
        order_desc = "只启用123网盘秒传"
    elif PTTO115_SWITCH:
        order_desc = "只启用115网盘秒传"
    else:
        order_desc = "均未启用秒传"

    notifier.send_message(
        f"开始监控本地待上传目录\n"
        f"123网盘秒传：{'开启' if PTTO123_SWITCH else '关闭'}\n"
        f"115网盘秒传：{'开启' if PTTO115_SWITCH else '关闭'}\n"
        f"当前秒传顺序：{order_desc}"
    )
    
    cache = {}
    attempt_count = {}

    while True:
        # 遍历目录
        for root, _, files in os.walk(UPLOAD_DIR):
            for filename in files:
                file_path = os.path.join(root, filename)
                file_key = file_path

                logger.info(f"正在检查文件 {file_path} 的大小稳定性...")
                if not check_file_size_stability(file_path):
                    continue

                try:
                    filesize = os.path.getsize(file_path)
                    logger.info(f"获取到文件 {file_path} 的大小为 {filesize} 字节")
                except FileNotFoundError:
                    if file_key in cache: del cache[file_key]
                    continue

                if file_key not in attempt_count:
                    attempt_count[file_key] = 0
                attempt_count[file_key] += 1
                logger.info(f"正在尝试上传文件（第 {attempt_count[file_key]} 次）：{file_path}")
                
                if file_key not in cache:
                    cache[file_key] = {'md5': '', 'sha1': ''}
                
                # --- 123 网盘秒传逻辑 ---
                if PTTO123_SWITCH:
                    try:
                        client_123 = init_123_client()
                        if not cache[file_key]['md5']:
                            logger.info(f"计算文件MD5：{file_path}")
                            cache[file_key]['md5'] = fast_md5(file_path)
                        
                        logger.info(f"开始尝试123网盘秒传：{file_path}")
                        upload_result = client_123.upload_file_fast(
                            file=file_path,
                            file_md5=cache[file_key]['md5'],
                            file_name=filename,
                            file_size=filesize,
                            parent_id=PTTO123_UPLOAD_PID,
                            duplicate=2,
                            async_=False
                        )

                        if upload_result.get("code") == 0 and upload_result["data"].get("Reuse"):
                            logger.info(f"123网盘秒传成功：{file_path}")
                            if TG_BOT_TOKEN and TG_ADMIN_USER_ID:
                                notifier.send_message(f"本地文件“{filename}”123网盘秒传成功")
                            os.remove(file_path)
                            if file_key in cache: del cache[file_key]
                            if file_key in attempt_count: del attempt_count[file_key]
                            continue
                        else:
                            logger.warning(f"123网盘秒传未成功：{file_path}")
                    except Exception as e:
                        logger.error(f"123网盘操作失败：{e}")

                # --- 115 网盘秒传逻辑 (已升级适配新版p115client) ---
                if PTTO115_SWITCH:
                    try:
                        # 尝试获取客户端，如果初始化失败则跳过本次循环
                        client_115 = init_115_client()
                        if not client_115:
                            logger.warning("115客户端未就绪，跳过本次115秒传尝试")
                        else:
                            logger.info(f"开始尝试115网盘秒传：{file_path}")
                            
                            # 1. 计算 SHA1 (115 秒传必须)
                            if not cache[file_key]['sha1']:
                                sha1_hash = hashlib.sha1()
                                with open(file_path, "rb") as f:
                                    for chunk in iter(lambda: f.read(65536), b""):
                                        sha1_hash.update(chunk)
                                cache[file_key]['sha1'] = sha1_hash.hexdigest().upper()
                                logger.info(f"已计算文件SHA1：{cache[file_key]['sha1']}")
                            
                            # 2. 调用新版API进行秒传探测
                            # 修正：参数名严格使用 filename, filesize, filesha1, pid
                            try:
                                upload_result = client_115.fs_upload_init(
                                    filename=filename,
                                    filesize=filesize,
                                    filesha1=cache[file_key]['sha1'],
                                    pid=PTTO115_UPLOAD_PID
                                )
                            except Exception as e:
                                logger.error(f"115 API调用错误: {e}")
                                # 如果是认证错误，置空客户端以便下次重连
                                client_115 = None 
                                raise

                            # 3. 判断结果
                            # status=2: 极速上传成功 (秒传)
                            # status=1: 需要上传文件流 (本脚本只做秒传，故视为不成功但不报错)
                            if upload_result.get('status') == 2:
                                logger.info(f"115网盘秒传成功：{file_path}（目标目录ID：{PTTO115_UPLOAD_PID}）")
                                if TG_BOT_TOKEN and TG_ADMIN_USER_ID:
                                    notifier.send_message(f"本地文件“{filename}”115网盘秒传成功")
                                os.remove(file_path)
                                if file_key in cache: del cache[file_key]
                                if file_key in attempt_count: del attempt_count[file_key]
                            else:
                                logger.warning(f"115网盘秒传未成功：{file_path} (Status: {upload_result.get('status')}, Pickcode: {upload_result.get('pickcode')})")

                    except Exception as e:
                        logger.error(f"115网盘操作失败：{e}")
                        # 遇到错误不删除文件，等待下一次循环重试

                time.sleep(SLEEP_AFTER_FILE)

        # --- 每轮遍历后也同步一次，作为双重保险 ---
        if client_115:
             sync_cookies_to_files(client_115)
        # -----------------------------------------                

        # 一轮遍历完成
        time.sleep(SLEEP_AFTER_ROUND)

def main():
    ptto123process()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户终止程序")
    except Exception as e:
        logger.error(f"程序异常退出：{e}")