from operator import inv
from pickle import NONE
import requests
import os
import shutil
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import time
import sqlite3
from datetime import datetime, timedelta
from datetime import time as time_datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from p123client import P123Client
# 尝试引入工具函数，如果新版位置改变则做兼容
try:
    from p123client import check_response
except ImportError:
    # 如果 check_response 不在顶层，定义一个简单的兼容函数或查找正确路径
    def check_response(resp):
        if resp.get("code") != 0:
            raise Exception(resp.get("message") or "Unknown Error")
from urllib.parse import urlsplit, parse_qs
import re
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import schedule
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from collections import defaultdict
from content_check import check_porn_content
try:
    from pyrogram import Client, filters, idle 
except ImportError:
    logging.error("未安装 pyrogram，人形模块将无法启动。请 pip install pyrogram tgcrypto")

# 设置httpx日志级别为WARNING，避免INFO级别的输出
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
logging.getLogger("telebot").setLevel(logging.ERROR)

version = "8.0.4"  
newest_id = 50
# 加载.env文件中的环境变量
load_dotenv(dotenv_path="db/user.env",override=True)
load_dotenv(dotenv_path="sys.env",override=True)
# 1. 确保日志目录存在
log_dir = os.path.join("db", "log")
os.makedirs(log_dir, exist_ok=True)
class MsFormatter(logging.Formatter):
    # 重写时间格式化方法
    def formatTime(self, record, datefmt=None):
        # 将时间戳转换为包含毫秒的datetime对象
        dt = datetime.fromtimestamp(record.created)
        # 格式化到毫秒（取微秒的前3位）
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # 保留到毫秒
# 使用自定义的Formatter
formatter = MsFormatter(
    fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S.%f'  # 这里可以正常使用%f了
)

root_logger = logging.getLogger()  # 获取根日志器
root_logger.setLevel(logging.INFO)  # 全局日志级别

# ================= [增强版] 屏蔽 Pyrogram Peer id 错误 =================
class IgnorePeerIdError(logging.Filter):
    """
    强力屏蔽 Pyrogram 的 Peer id invalid 错误
    覆盖日志消息本体和异常堆栈详情
    """
    def filter(self, record):
        # 1. 检查日志的主体消息 (使用 getMessage 获取完整格式化后的字符串)
        if "Peer id invalid" in record.getMessage():
            return False

        # 2. 检查异常堆栈信息
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            # 直接检查异常对象的值
            if exc_value and "Peer id invalid" in str(exc_value):
                return False
            #以此防万一，检查堆栈文本
            if "Peer id invalid" in str(exc_traceback):
                return False
                
        return True

# 定义需要屏蔽的 Logger 列表 (精准打击)
target_loggers = [
    "pyrogram", 
    "pyrogram.dispatcher", 
    "pyrogram.session.session",
    "asyncio"
]

# 循环应用过滤器
for logger_name in target_loggers:
    logging.getLogger(logger_name).addFilter(IgnorePeerIdError())

# 额外保险：尝试给根 Logger 也加上（防止有漏网之鱼冒泡上来）
logging.getLogger().addFilter(IgnorePeerIdError())

# ================= 新增代码结束 =================

if __name__ == "__mp_main__":
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "log.log"),
        when='D',          # 每天轮转
        interval=1,        # 间隔1天
        backupCount=3,     # 最多保留3天日志
        encoding='utf-8',
        atTime=time_datetime(0, 0, 1)
    )
    # 获取当前日期
    today = datetime.now().date()
    # 计算今天的atTime时间戳
    today_at_time = datetime.combine(today, file_handler.atTime).timestamp()
    # 当前时间戳
    now = datetime.now().timestamp()
    # 如果当前时间在今天的atTime之前，则首次轮转时间为今天atTime
    # 如果当前时间已过今天的atTime，则首次轮转时间为明天atTime
    if now < today_at_time:
        target_rollover = today_at_time
    else:
        target_rollover = datetime.combine(today + timedelta(days=1), file_handler.atTime).timestamp()
    # 强制修正下一次轮转时间
    file_handler.rolloverAt = target_rollover
    
if __name__ == "__main__":
    file_handler = logging.FileHandler(
                        filename=os.path.join(log_dir, "start-log.log"),
                        encoding='utf-8'
                    )
console_handler = logging.StreamHandler()

# 4. 定义全局日志格式（所有日志共用）
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
# 6. 将处理器添加到根日志器（关键：根日志器的配置会被所有子logger继承）
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)
# ----------------------
# 测试：任意模块的logger都会遵循全局配置
# ----------------------
# 示例1：当前模块的logger
logger = logging.getLogger(__name__)
import threading
import concurrent.futures
# 创建大小为1的线程池用于发送消息
reply_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=20)
# 安全地获取整数值，避免异常
def get_int_env(env_name, default_value=0):
    try:
        value = os.getenv(env_name, str(default_value))
        return int(value) if value else default_value
    except (ValueError, TypeError):
        reply_thread_pool.submit(send_message,f"[警告] 环境变量 {env_name} 值不是有效的整数，使用默认值 {default_value}")
        logger.warning(f"环境变量 {env_name} 值不是有效的整数，使用默认值 {default_value}")
        return default_value
CHANNEL_URL = os.getenv("ENV_TG_CHANNEL", "")

AUTO_MAKE_JSON = get_int_env("ENV_AUTO_MAKE_JSON", 1)

#TG BOT的token
TG_BOT_TOKEN = os.getenv("ENV_TG_BOT_TOKEN", "")
#TG 用户ID
TG_ADMIN_USER_ID = get_int_env("ENV_TG_ADMIN_USER_ID", 0)

#是否开启监控功能，1为开启，0为关闭
AUTHORIZATION = get_int_env("ENV_AUTHORIZATION", 0)
#123账号
CLIENT_ID = os.getenv("ENV_123_CLIENT_ID", "")
DIY_LINK_PWD = os.getenv("ENV_DIY_LINK_PWD", "")
#123密码
CLIENT_SECRET = os.getenv("ENV_123_CLIENT_SECRET", "")
FILTER = os.getenv("ENV_FILTER", "")
filter_pattern = re.compile(FILTER, re.IGNORECASE)
#需要转存的123目录ID
UPLOAD_TARGET_PID = get_int_env("ENV_123_UPLOAD_PID", 0)
# 获取需要过滤的后缀名，默认为空，多个用逗号分隔
ENV_EXT_FILTER = os.getenv("ENV_EXT_FILTER", "")
# 预处理为小写列表，例如 ['.nfo', '.jpg', '.png']
SKIP_EXTENSIONS = [ext.strip().lower() for ext in ENV_EXT_FILTER.split(',') if ext.strip()]

UPLOAD_JSON_TARGET_PID = get_int_env("ENV_123_JSON_UPLOAD_PID", 0)
UPLOAD_LINK_TARGET_PID = get_int_env("ENV_123_LINK_UPLOAD_PID", UPLOAD_JSON_TARGET_PID)
USERBOT_HELP = '''═════命令❀描述════

1. 搜索并生成元数据卡片：
发送：-s123 关键词
(例：-s123 权力的游戏)
功能：搜索资源，选择后自动抓取TMDB信息生成精美卡片和JSON。

2. 媒体/链接/JSON转存：
发送：-mc (回复目标消息)
功能：回复一条包含 123链接 或 JSON文件 的消息发送 -mc，自动解析转存并生成战报。'''

DISCLAIMER_TEXT = '''⚠️ 免责声明 & 合规说明

        本工具仅为方便网盘分享与转存，所有资源均来自网络用户的公开分享内容：
        - 开发者非资源的上传者、所有者或版权方，不对资源的合法性、准确性、完整性承担责任。
        - 工具内置AI内容识别机制，自动过滤涉政、色情、暴力等违规资源的分享创建，坚决抵制非法内容传播。

        用户在使用本工具时需知悉：
        - 需自行核实资源版权归属，确保合规使用，避免侵犯第三方权益；
        - 对下载、存储、传播资源可能引发的法律纠纷、数据安全风险（如病毒感染）等，由用户自行承担全部责任；
        - 开发者不对上述风险导致的任何损失承担责任；

        - 如您继续使用本工具，则视为已完整阅读、理解并接受以上所有声明内容。'''
USE_METHOD="🔍 使用方法：\n      1、创建分享请使用 /share 关键词 来搜索文件夹，例如：/share 权力的游戏\n      2、转存分享可直接把123、115、天翼链接转发至此，支持频道中带图片的那种分享\n      3、转存秒传json可直接把json转发至此\n      4、转存秒传链接可直接把秒传链接转发至此\n      5、123批量离线磁力链请直接把磁力链发送至此\n      6、创建完成分享链接后可一键发帖至123资源社区\n      7、123、115、天翼等频道监控转存在后台定时执行\n      8、PT上下载的本地文件无限尝试秒传123或115网盘，以避免运营商制裁，需要配置compose里的路径映射\n      9、访问 http://127.0.0.1:12366/d/file (例如 http://127.0.0.1:12366/d/权力的游戏.mp4) 即可获取123文件下载直链\n      10、支持misaka_danmu_server弹幕服务，当触发302播放时，会自动调用misaka_danmu_server API来下载对应集以及下一集的弹幕\n      11、支持123转存夸克分享（原理是从夸克分享生成秒传给123转存）\n⚠️ 注：以上功能的使用需要在 NasIP:12366（如192.168.1.1:12366）的配置页面完成功能配置"
# 数据库路径（保持不变）
DB_DIR = "db"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)
DATABASE_FILE = os.path.join(DB_DIR, "TG_monitor-123.db")
USER_STATE_DB = os.path.join(DB_DIR, "user_states.db")
CHECK_INTERVAL = get_int_env("ENV_CHECK_INTERVAL", 0)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
]
RETRY_TIMES = 3
TIMEOUT = 15

TOKENSHARE = os.getenv("TOKEN", "")
if TOKENSHARE:
    botshare = telebot.TeleBot(TOKENSHARE)
#TG 用户ID
    TARGET_CHAT_ID_SHARE = get_int_env("TARGET_CHAT_ID", 0)

from share import get_quality
import re
from urllib.parse import urlparse, parse_qs

def check_ext_filter(filename):
    """
    检查文件后缀是否在黑名单中
    返回 True 表示需要跳过，False 表示允许处理
    """
    if not SKIP_EXTENSIONS or not filename:
        return False
    
    # 获取文件后缀（转小写）
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    
    if ext in SKIP_EXTENSIONS:
        return True
    return False

def parse_share_url(share_url):
    """解析分享链接，提取ShareKey和提取码"""
    try:
        # 使用正则表达式匹配分享链接
        pattern = r'(https?://(?:[a-zA-Z0-9-]+\.)*123[a-zA-Z0-9-]*\.[a-z]{2,6}/s/([a-zA-Z0-9\-_]+))'
        match = re.search(pattern, share_url, re.IGNORECASE)

        if match:
            # 完整URL
            full_url = match.group(1)
            # ShareKey
            share_key = match.group(2)
            # 尝试从原始URL查询参数中获取提取码
            parsed = urlparse(share_url)
            query_params = parse_qs(parsed.query)
            share_pwd = query_params.get('pwd', [''])[0]
            return share_key, share_pwd

        logger.warning(f"无法解析分享链接: {share_url}")
        return '', ''
    except Exception as e:
        logger.error(f"解析分享链接失败: {str(e)}")
        return '', ''

def get_formatted_size(size_in_bytes):
    """全局工具：格式化文件大小"""
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024**2:
        return f"{size_in_bytes / 1024:.2f} KB"
    elif size_in_bytes < 1024**3:
        return f"{size_in_bytes / (1024**2):.2f} MB"
    elif size_in_bytes < 1024**4:
        return f"{size_in_bytes / (1024**3):.2f} GB"
    else:
        return f"{size_in_bytes / (1024**4):.2f} TB"

def recursive_count_files(client: P123Client, parent_file_id, share_key, share_pwd):
    """递归获取分享中的文件并统计视频文件数量"""
    logger.info(f"开始递归获取分享中的文件数量，文件夹ID: {parent_file_id}")
    video_extensions = {'.mkv', '.ts', '.mp4', '.avi', '.rmvb', '.wmv', '.m2ts', '.mpg', '.flv', '.rm', '.mov', '.iso'}
    video_count = 0
    try:
        page = 1
        while True:
            # --- 修复：回退到兼容性更好的 share_fs_list ---
            resp = client.share_fs_list({
                "ShareKey": share_key,
                "SharePwd": share_pwd,
                "parentFileId": parent_file_id,
                "limit": 100,
                "Page": page
            })
            check_response(resp)
            data = resp["data"]

            if data and "InfoList" in data:
                for item in data["InfoList"]:
                    if item["Type"] == 1:  # 目录
                        # 递归计算子目录中的视频文件
                        video_count += recursive_count_files(client, item["FileId"], share_key, share_pwd)
                    else:  # 文件
                        # 检查是否为视频文件
                        ext = os.path.splitext(item["FileName"])[1].lower()
                        if ext in video_extensions:
                            video_count += 1
            
            # 检查是否为最后一页
            if not data or len(data.get("InfoList", [])) < 100:
                break            
            page += 1
    except Exception as e:
        logger.error(f"获取文件列表失败（父ID: {parent_file_id}）: {str(e)}")
        raise
    return video_count

def build_share_message(metadata, client, file_id, folder_name, file_name, share_info):
    # 使用元数据美化消息
    #logger.info(get_first_video_file(client, file_id))
    get_quality(file_name)

    poster_url = metadata.get('backdrop', '').strip('` ') or metadata.get('poster', '').strip('` ')
    # 内容类型判断 
    content_type = '📺 电视剧' if 'seasons' in metadata and 'episodes' in metadata else '🎬 电影' 
    # 构建标题行 
    share_message = f"{content_type}｜{metadata.get('title')} ({metadata.get('year')})\n\n" 
    # 评分 
    genres = metadata.get('genres', [])[0] if metadata.get('genres', []) else ''
    share_message += f"⭐️ 评分: {metadata.get('rating')} / 地区: {', '.join(metadata.get('countries', []))} / 类型: {genres[:15]}{'...' if len(genres) > 15 else ''}\n" 
    # 类型 
    #genres = ', '.join(metadata.get('genres', []))
    #share_message += f"📽️ 类型: {genres[:15]}{'...' if len(genres) > 15 else ''}\n" 
    # 地区 
    #share_message += f"🌍 地区: {', '.join(metadata.get('countries', []))}\n" 
    # 语言 
    # share_message += f"🗣 语言: {', '.join(metadata.get('languages', ['未知']))}\n" 
    # 导演 
    if metadata.get('director'): 
        share_message += f"🎬 导演: {metadata.get('director', '')[:10]}{'...' if len(metadata.get('director', '')) > 10 else ''}\n" 
    # 主演 
    share_message += f"👥 主演: {metadata.get('cast', '')[:10]}{'...' if len(metadata.get('cast', '')) > 10 else ''}\n" 
    # 集数（如适用） 
    if 'seasons' in metadata and 'episodes' in metadata: 
        share_message += f"📺 共{metadata.get('seasons')}季 ({metadata.get('episodes')}集)\n" 
    # 简介（使用blockquote） 
    # 从分享链接中解析ShareKey和提取码
    share_key, share_pwd = parse_share_url(share_info['url'])
    share_pwd = share_pwd or share_info.get('password','')  
    # 获取文件夹内文件列表
    files = get_directory_files(client, file_id, folder_name)
    logger.info(f"获取实际文件数量: {len(files)}")
    actual_video_count = recursive_count_files(client, file_id, share_key, share_pwd)
    logger.info(f"获取分享中的文件数量: {actual_video_count}")
    # 定义视频文件扩展名
    video_extensions = {'.mkv', '.ts', '.mp4', '.avi', '.rmvb', '.wmv', '.m2ts', '.mpg', '.flv', '.rm', '.mov', '.iso'}
    # 筛选视频文件
    video_files = []
    for file_info in files:
        filename = file_info["path"]
        ext = os.path.splitext(filename)[1].lower()
        if ext in video_extensions:
            video_files.append(file_info)
    
    if not video_files:
        file_info_text = f"📁 没有找到视频文件 | 实际视频数量: {actual_video_count}"
        file_info_text2 = f"📁 没有找到视频文件"
    else:
        total_files_count = len(video_files)
        total_size = sum(file_info["size"] for file_info in video_files)
        # 计算平均大小
        avg_size = total_size / total_files_count if total_files_count > 0 else 0
        # 格式化文件大小
        if total_size < 1024:
            size_str = f"{total_size} B"
        elif total_size < 1024 * 1024:
            size_str = f"{total_size / 1024:.2f} KB"
        elif total_size < 1024 * 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024):.2f} MB"
        elif total_size < 1024 * 1024 * 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"
        else:
            size_str = f"{total_size / (1024 * 1024 * 1024 * 1024):.2f} TB"

        avg_size_str = get_formatted_size(avg_size)
        file_info_text = f"🎬 视频数量: {total_files_count} | 总大小: {size_str} | 平均大小：{avg_size_str} | 实际视频数量: {actual_video_count} | 已和谐：{total_files_count-actual_video_count}"
        file_info_text2 = f"🎬 视频数量: {total_files_count} | 总大小: {size_str} | 平均大小：{avg_size_str}" 
    share_message2 = share_message
    share_message2 += f"\n📖 简介: <blockquote expandable=\"\">{metadata.get('plot')[:500]}{'...' if len(metadata.get('plot')) > 500 else ''}</blockquote>\n\n{file_info_text2}\n"
    share_message += f"\n📖 简介: <blockquote expandable=\"\">{metadata.get('plot')[:500]}{'...' if len(metadata.get('plot')) > 500 else ''}</blockquote>\n\n{file_info_text}\n" 
    quality = get_quality(get_first_video_file(client, file_id))
    if quality:
        share_message += f"🏷 视频质量: {quality}\n"
        share_message2 += f"🏷 视频质量: {quality}\n"
    share_message += f"🔗 链接: {share_info['url']}{'?pwd=' + share_info['password'] if share_info.get('password') else ''}\n" 
    #share_message += f"🔗 链接: <a href=\"{share_info['url']}{'?pwd=' + share_info['password'] if share_info.get('password') else ''}\" target=\"_blank\" rel=\"noopener\" onclick=\"return confirm('Open this link?\n\n'+this.href);\">查看链接</a>\n"
    share_message += f"🙋 来自123bot自动创建的分享" 
    share_message2 += f"🙋 来自123bot自动创建的分享" 
    return share_message, share_message2, poster_url, files

def get_directory_files(client: P123Client, directory_id, folder_name, current_path="", is_root=True):
    """
    获取目录下的所有文件（使用V2 API）
    directory_id: 目录ID
    folder_name: 文件夹名称
    current_path: 当前路径，用于构建完整的相对路径
    """
    # 对于根目录，commonPath就是folder_name
    # 对于子目录，current_path是相对于commonPath的路径
    if is_root:
        common_path = folder_name
        # 根目录的current_path为空
        current_path = ""
    else:
        common_path = current_path.split('/')[0] if current_path else folder_name

    # 构建当前相对于commonPath的路径
    # 对于根目录，relative_path为空
    # 对于子目录，relative_path是相对于commonPath的路径
    if is_root:
        relative_path = ""
    else:
        relative_path = f"{current_path}/{folder_name}" if current_path else folder_name
        # 移除开头可能的/
        relative_path = relative_path.lstrip('/')
    logger.info(f"获取目录内容 (ID: {directory_id}, commonPath: '{common_path}', 相对路径: '{relative_path}')")
    all_files = []
    OPEN_API_HOST = "https://open-api.123pan.com"
    API_PATHS = {
        'LIST_FILES_V2': '/api/v2/file/list'
    }
    retry_delay = 31  # 重试延迟秒数

    # 使用V2 API获取目录内容
    last_file_id = 0  # 初始值为0
    while True:
        url = f"{OPEN_API_HOST}{API_PATHS['LIST_FILES_V2']}"
        params = {
            "parentFileId": directory_id,
            "trashed": 0,  # 排除回收站文件
            "limit": 100,   # 最大不超过100
            "lastFileId": last_file_id
        }
        headers = {
            "Authorization": f"Bearer {client.token}",
            "Platform": "open_platform",
            "Content-Type": "application/json"
        }

        try:
            logger.info(f"请求目录列表: {url}, 参数: {params}")
            response = requests.get(url, params=params, headers=headers, timeout=30)
            if not response:
                logger.error(f"获取目录列表失败")
                return all_files

            if response.status_code != 200:
                logger.error(f"获取目录列表失败: HTTP {response.status_code}")
                return all_files

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"响应JSON解析失败: {str(e)}")
                logger.error(f"完整响应: {response.text}")
                return all_files

            if data.get("code") != 0:
                error_msg = data.get("message", "未知错误")
                
                # 如果是限流错误，等待后重试
                if "操作频繁" in error_msg or "限流" in error_msg:
                    logger.warning(f"API限流: {error_msg}, 等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    continue
                
                logger.error(f"API错误: {error_msg}")
                return all_files

            # 处理当前页的文件
            for item in data["data"].get("fileList", []):
                # 排除回收站文件
                if item.get("trashed", 1) != 0:
                    continue
                
                # 构建文件相对路径
                item_path = item['filename']
                
                if item["type"] == 0:  # 文件
                    # 构建相对于commonPath的路径（使用/作为分隔符）
                    # 注意：不包含commonPath
                    if relative_path:
                        full_item_path = f"{relative_path}/{item_path}"
                    else:
                        full_item_path = item_path
                    # 确保使用/作为分隔符
                    full_item_path = full_item_path.replace('\\', '/')
                    file_info = {
                        "path": full_item_path,  # 存储相对于commonPath的路径
                        "etag": item["etag"],
                        "size": item["size"]
                    }
                    all_files.append(file_info)
                elif item["type"] == 1:  # 文件夹
                    # 递归获取子目录（添加延迟避免限流）
                    #time.sleep(0.05)  # 增加延迟
                    sub_files = get_directory_files(
                        client,
                        item["fileId"],
                        item['filename'],
                        relative_path,
                        False
                    )
                    all_files.extend(sub_files)

            # 检查是否有更多页面
            last_file_id = data["data"].get("lastFileId", -1)
            #time.sleep(0.05)
            if last_file_id == -1:
                break
                
        except Exception as e:
            logger.error(f"获取目录列表出错: {str(e)}")
            return all_files

    logger.info(f"找到 {len(all_files)} 个文件 (ID: {directory_id})")
    return all_files

# 全局变量（使用安全的方式初始化bot）
# 处理JSON文件转存

import time
# 创建锁对象确保文件依次转存
json_process_lock = threading.Lock()

# 跟踪上次发送消息的时间
last_send_time = 0
RETRY_DELAY = 60  # 重试等待时间（秒）
MAX_RETRIES = 30  # 最大重试次数
# 定义线程池中的发送函数
def send_message(text):
    send_retry_count = 0
    while send_retry_count < MAX_RETRIES:
        try:
            bot.send_message(TG_ADMIN_USER_ID, text)
            logger.info(f"消息 '{text.replace('\n', '').replace('\r', '')[:20]}...' ，已成功发送给用户 {TG_ADMIN_USER_ID}（第{send_retry_count+1}/{MAX_RETRIES}次尝试）")
            break
        except Exception as e:
            logger.error(f"发送回复失败，{RETRY_DELAY}秒后重发，消息：{text}，错误：{str(e)}")
            time.sleep(RETRY_DELAY)
            send_retry_count += 1

def send_message_with_id(chatid, text):
    send_retry_count = 0
    while send_retry_count < MAX_RETRIES:
        try:
            bot.send_message(chatid, text)
            logger.info(f"消息 '{text.replace('\n', '').replace('\r', '')[:20]}...' ，已成功发送给用户 {chatid}（第{send_retry_count+1}/{MAX_RETRIES}次尝试）")
            break
        except Exception as e:
            logger.error(f"发送回复失败，{RETRY_DELAY}秒后重发，消息：{text}，错误：{str(e)}")
            time.sleep(RETRY_DELAY)
            send_retry_count += 1

def send_reply(message, text):
    send_retry_count = 0
    while send_retry_count < MAX_RETRIES:
        try:
            bot.reply_to(message, text)
            logger.info(f"消息 '{text.replace('\n', '').replace('\r', '')[:20]}...' ，已成功发送给用户 {message.chat.id}（第{send_retry_count+1}/{MAX_RETRIES}次尝试）")
            break
        except Exception as e:
            logger.error(f"发送回复失败，{RETRY_DELAY}秒后重发，消息：{text}，错误：{str(e)}")
            time.sleep(RETRY_DELAY)
            send_retry_count += 1

def send_reply_delete(message, text):
    global last_send_time
    current_time = time.time()
    if current_time - last_send_time < 10:
        #logger.info(f"[节流] 10秒内已发送消息，忽略当前消息: {text}")
        return
    # 限制文本长度，保留开头和末尾的200字符
    max_length = 400
    if len(text) > max_length:
        text = text[:200] + '\n     ......\n' + text[-200:]  
    try:
        sent_message = bot.reply_to(message, text)
        # 更新上次发送时间
        last_send_time = current_time
        time.sleep(12)  # 等待10秒后删除消息
        bot.delete_message(chat_id=sent_message.chat.id, message_id=sent_message.message_id)
    except Exception as e:
        logger.error(f"发送回复失败: {str(e)}")
bot = telebot.TeleBot(TG_BOT_TOKEN)
from telebot.types import BotCommand
# 安全初始化TeleBot
while True and __name__ == "__mp_main__":
    try:
        bot = telebot.TeleBot(TG_BOT_TOKEN)
        # 定义命令菜单（包含/start和/share）
        commands = [
            BotCommand("start", "开始使用机器人"),
            BotCommand("share", "创建分享链接"),
            BotCommand("sync189", "天翼转存文件夹秒传到123盘转存文件夹"),
            BotCommand("info", "打印当前账户的信息"),
            BotCommand("add", "添加123监控过滤词，发送/add可查看使用方法"),
            BotCommand("remove", "删除123监控过滤词，发送/remove可查看使用方法")
        ]
        # 设置命令菜单
        bot.set_my_commands(commands)
        logger.info("已设置Bot命令菜单：/start, /share, /info, /add, /remove")
        logger.info("TeleBot初始化成功")
        break  # 初始化成功，退出循环
    except Exception as e:
        logger.error(f"由于网络等原因无法与TG Bot建立通信，30秒后重试...: {str(e)}")
        time.sleep(30)

# 初始化123客户端
def init_123_client(retry: bool = False) -> P123Client:
    import requests
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
        while True:
            try:
                # --- 修正：移除 app='web' 参数 ---
                client = P123Client(token=token)
                # 验证token有效性
                try:
                    # 尝试调用用户信息接口验证
                    res = client.passport_user_info()
                except AttributeError:
                    # 兼容旧版本
                    res = client.user_info()

                # 检查API返回结果是否表示token过期
                if res.get('code') != 0 or res.get('message') != "ok":
                    reply_thread_pool.submit(send_message, "123 token过期，将重新获取")
                    logger.info("检测到token过期，将重新获取")
                    if os.path.exists(token_path):
                        os.remove(token_path)
                    break
                else:
                    logger.info("123客户端初始化成功（使用持久化token）")
                    return client
            except Exception as e:
                if "token is expired" in str(e).lower() or (
                        hasattr(e, 'args') and "token is expired" in str(e.args).lower()):
                    logger.info("检测到token过期，将重新获取")
                    if os.path.exists(token_path):
                        os.remove(token_path)
                    break
                else:
                    logger.warning(f"token健康检查异常，稍后重试：{e}")
                    time.sleep(RETRY_DELAY)
                    # 如果是网络错误等非过期错误，跳出循环让其尝试重新登录或重试
                    break 

    # 通过API接口获取新token
    try:
        # --- 修正：移除 app='web' 参数 ---
        client = P123Client(CLIENT_ID, CLIENT_SECRET)
        
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(client.token)

        logger.info("123客户端初始化成功（使用新获取的token）")
        return client
    except Exception as e:
        if not retry:
            logger.error(f"获取token失败：{e}，尝试重试...")
            return init_123_client(retry=True)
        logger.error(f"获取token失败（已重试）：{e}")
        raise

# 数据库相关函数（保持不变）
def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS messages
                  (msg_id INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, date TEXT, message_url TEXT, target_url TEXT, 
                   transfer_status TEXT, transfer_time TEXT, transfer_result TEXT)''')
    conn.commit()
    conn.close()


def is_message_processed(message_url):
    """检查消息是否已处理（无论转存是否成功）"""
    conn = sqlite3.connect(DATABASE_FILE)
    result = conn.execute("SELECT 1 FROM messages WHERE message_url = ?",
                          (message_url,)).fetchone()
    conn.close()
    return result is not None


def save_message(message_id, date, message_url, target_url,
                 status="待转存", result="", transfer_time=None):
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        conn.execute("INSERT INTO messages (id, date, message_url, target_url, transfer_status, transfer_time, transfer_result) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (message_id, date, message_url, target_url,
                      status, transfer_time or datetime.now().isoformat(), result))
        conn.commit()
        logger.info(f"已记录: {message_id} | {target_url} | 状态: {status}")
    except sqlite3.IntegrityError:
        conn.execute("UPDATE messages SET transfer_status=?, transfer_result=?, transfer_time=? WHERE id=?",
                     (status, result, transfer_time or datetime.now().isoformat(), message_id))
        conn.commit()
    finally:
        conn.close()


# 获取最新消息（保持不变）
def get_latest_messages():
    try:
        # 从环境变量获取多个频道链接
        channel_urls = os.getenv("ENV_TG_CHANNEL", "").split('|')
        if not channel_urls or channel_urls == ['']:
            logger.warning("未设置ENV_TG_CHANNEL环境变量")
            return []
            
        all_new_messages = []
        
        # 对每个频道链接执行获取消息逻辑
        for channel_url in channel_urls:
            channel_url = channel_url.strip()
            if not channel_url:
                continue
                
            # 预处理channel_url，确保格式正确
            if channel_url.startswith('https://t.me/') and '/s/' not in channel_url:
                # 提取频道名称部分
                channel_name = channel_url.split('https://t.me/')[-1]
                # 重构URL，添加/s/
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
            new_messages = []
            for i in range(total):
                msg_index = total - 1 - i
                msg = message_divs[msg_index]
                data_post = msg.get('data-post', '')
                message_id = data_post.split('/')[-1] if data_post else f"未知ID_{msg_index}"
                logger.info(f"检查第{i + 1}新消息（倒数第{i + 1}条，ID: {message_id}）")
                time_elem = msg.find('time')
                date_str = time_elem.get('datetime') if time_elem else datetime.now().isoformat()
                link_elem = msg.find('a', class_='tgme_widget_message_date')
                message_url = f"{link_elem.get('href').lstrip('/')}" if link_elem else ''
                text_elem = msg.find('div', class_='tgme_widget_message_text')
                #print(str(text_elem))
                if text_elem:
                    message_text = text_elem.get_text(separator='\\n', strip=True)
                    target_urls = extract_target_url(f"{msg}")
                    if target_urls:
                        for url in target_urls:
                            # 检查是否有提取码但URL中没有pwd参数
                            pwd_match = re.search(r'提取码\s*[:：]\s*(\w+)', str(text_elem), re.IGNORECASE)
                            if pwd_match and 'pwd=' not in url:
                                pwd = pwd_match.group(1)
                                # 确保URL格式正确，添加pwd参数
                                if '?' in url:
                                    url = f"{url}&pwd={pwd}"
                                else:
                                    url = f"{url}?pwd={pwd}"
                                logger.info(f"已为URL添加提取码: {url}")
                            if not is_message_processed(message_url):
                                new_messages.append((message_id, date_str, message_url, url, message_text))                               
                            else:
                                logger.info(f"第{i + 1}新消息已处理，跳过")
                            #print(f"tg消息链接：{message_url}")
                            #print(f"123链接：{url}")
                    else:
                        if not is_message_processed(message_url):
                            new_messages.append((message_id, date_str, message_url, "", message_text))
                        else:
                            logger.info(f"第{i + 1}新消息已处理，跳过")                       
                        #print("未发现目标123链接")
            new_messages.reverse()
            logger.info(f"发现{len(new_messages)}条新的123分享链接")
            all_new_messages.extend(new_messages)
        
        # 按时间排序所有消息
        all_new_messages.sort(key=lambda x: x[1])
        logger.info(f"===== 所有频道共发现{len(all_new_messages)}条新的123分享链接 =====")
        return all_new_messages
    except requests.exceptions.RequestException as e:
        logger.error(f"网络请求失败: {str(e)[:100]}")
        return []


def extract_target_url(text):
    pattern = r'https?:\/\/(?:www\.)?123(?:\d+|pan)\.\w+\/s\/[\w-]+(?:\?pwd=\w+|(?:\s*提取码\s*[:：]\s*\w+))?'
    matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
    if matches:
        # 去除重复链接
        unique_matches = list(set([match.strip() for match in matches]))
        return unique_matches
    return []


# 转存分享链接（优化版）
from collections import defaultdict, deque
def transfer_shared_link_optimize(client: P123Client, target_url: str, UPLOAD_TARGET_PID: int | str) -> bool:
    parsed_url = urlsplit(target_url)
    if '/s/' in parsed_url.path:
        after_s = parsed_url.path.split('/s/')[-1]
        temp_key = after_s.split('/')[0]
        pwd_sep_index = re.search(r'提取码[:：]', temp_key)
        share_key = temp_key[:pwd_sep_index.start()].strip() if pwd_sep_index else temp_key
    else:
        share_key = None
    if not share_key:
        logger.error(f"无效的分享链接: {target_url}")
        return False

    # 解析密码
    query_params = parse_qs(parsed_url.query)
    share_pwd = query_params.get('pwd', [None])[0]
    if not share_pwd:
        pwd_match = re.search(r'提取码\s*[:：]\s*(\w+)', parsed_url.path, re.IGNORECASE)
        if not pwd_match:
            pwd_match = re.search(r'提取码\s*[:：]\s*(\w+)', target_url, re.IGNORECASE)
        share_pwd = pwd_match.group(1) if pwd_match else ""

    all_items = []

    def recursive_fetch(parent_file_id: int = 0) -> None:
        """递归获取分享中的文件和目录"""
        try:
            page = 1
            while True:
                # --- 修复：回退到兼容性更好的 share_fs_list ---
                resp = client.share_fs_list({
                    "ShareKey": share_key,
                    "SharePwd": share_pwd,
                    "parentFileId": parent_file_id,
                    "limit": 100,
                    "Page": page
                })
                check_response(resp)
                data = resp["data"]
                
                if data and "InfoList" in data:
                    for item in data["InfoList"]:
                        all_items.append({
                            "file_id": item["FileId"],
                            "name": item["FileName"],
                            "etag": item.get("Etag", ""),
                            "parent_dir_id": parent_file_id,
                            "size": item.get("Size", 0),
                            "Type": item["Type"]
                        })
                if not data or len(data.get("InfoList", [])) < 100:
                    break
                page += 1
        except Exception as e:
            logger.error(f"获取列表失败（父ID: {parent_file_id}）: {str(e)}")
            raise
    try:
        recursive_fetch()
        file_count = sum(1 for item in all_items if item["Type"] != 1)
        dir_count = sum(1 for item in all_items if item["Type"] == 1)
        logger.info(f"共发现{file_count}个文件和{dir_count}个目录，准备转存")
    except Exception as e:
        logger.error(f"获取资源结构失败: {str(e)}")
        return False
    
    fileList = []
    for item in all_items:
        # 如果是文件且后缀在黑名单中，则跳过
        if item["Type"] != 1 and check_ext_filter(item["name"]):
            logger.info(f"🚫 根据配置跳过文件: {item['name']}")
            continue
            
        fileList.append({
            "fileID": item["file_id"],
            "size": item["size"],
            "etag": item["etag"],
            "type": item["Type"],
            "parentFileID": UPLOAD_TARGET_PID,
            "fileName": item["name"],
            "driveID": 0
        })

    if not fileList:
        logger.warning("过滤后没有文件需要转存")
        return False

    logger.info(f"准备转存文件列表到目录: {UPLOAD_TARGET_PID}")

    try:
        # 保持原生 requests 调用，这是最稳妥的批量转存方式
        url = "https://www.123pan.com/b/api/restful/goapi/v1/file/copy/save"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {client.token}"
        }
        payload = {
            "fileList": fileList,
            "shareKey": share_key,
            "sharePwd": share_pwd,
            "currentLevel": 0
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            response_json = response.json()
            if response_json.get("message") == "ok":
                logger.info(f"{target_url} 转存成功")
                return True
            else:
                logger.error(f"转存失败: {response_json.get('message')}")
                return False
        else:
            logger.error(f"请求失败: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"转存错误: {str(e)}")
        return False

def transfer_shared_link(client: P123Client, target_url: str, UPLOAD_TARGET_PID: int | str) -> bool:
    parsed_url = urlsplit(target_url)
    if '/s/' in parsed_url.path:
        after_s = parsed_url.path.split('/s/')[-1]
        temp_key = after_s.split('/')[0]
        pwd_sep_index = re.search(r'提取码[:：]', temp_key)
        share_key = temp_key[:pwd_sep_index.start()].strip() if pwd_sep_index else temp_key
    else:
        share_key = None
    if not share_key:
        logger.error(f"无效的分享链接: {target_url}")
        return False

    query_params = parse_qs(parsed_url.query)
    share_pwd = query_params.get('pwd', [None])[0]
    if not share_pwd:
        pwd_match = re.search(r'提取码\s*[:：]\s*(\w+)', parsed_url.path, re.IGNORECASE)
        if not pwd_match:
            pwd_match = re.search(r'提取码\s*[:：]\s*(\w+)', target_url, re.IGNORECASE)
        share_pwd = pwd_match.group(1) if pwd_match else ""

    all_dirs = []
    all_files = []

    def recursive_fetch(parent_file_id: int = 0) -> None:
        try:
            page = 1
            while True:
                # --- 修复：回退到 share_fs_list ---
                resp = client.share_fs_list({
                    "ShareKey": share_key,
                    "SharePwd": share_pwd,
                    "parentFileId": parent_file_id,
                    "limit": 100,
                    "Page": page
                })
                check_response(resp)
                data = resp["data"]
                
                if data and "InfoList" in data:
                    for item in data["InfoList"]:
                        if item["Type"] == 1:
                            all_dirs.append({
                                "dir_id": item["FileId"],
                                "name": item["FileName"],
                                "parent_dir_id": parent_file_id
                            })
                            recursive_fetch(item["FileId"])
                        else:
                            all_files.append({
                                "file_id": item["FileId"],
                                "name": item["FileName"],
                                "etag": item["Etag"],
                                "parent_dir_id": parent_file_id,
                                "size": item["Size"]
                            })
                
                if not data or len(data.get("InfoList", [])) < 100:
                    break
                page += 1
        except Exception as e:
            logger.error(f"获取列表失败（父ID: {parent_file_id}）: {str(e)}")
            raise

    try:
        recursive_fetch()
        logger.info(f"共发现{len(all_dirs)}个目录和{len(all_files)}个文件")
    except Exception as e:
        logger.error(f"获取资源结构失败: {str(e)}")
        return False

    # 1. 目录构建逻辑
    dir_children = defaultdict(list)
    all_dir_ids = {d["dir_id"] for d in all_dirs}
    share_top_dirs = []
    for dir_info in all_dirs:
        parent_id = dir_info["parent_dir_id"]
        if parent_id not in all_dir_ids:
            share_top_dirs.append(dir_info)
        else:
            dir_children[parent_id].append(dir_info)
            
    dir_queue = deque(share_top_dirs)
    dir_id_mapping = {}
    for dir_info in share_top_dirs:
        dir_id_mapping[dir_info["dir_id"]] = None

    while dir_queue:
        dir_info = dir_queue.popleft()
        original_dir_id = dir_info["dir_id"]
        dir_name = dir_info["name"]
        original_parent_id = dir_info["parent_dir_id"]

        if original_dir_id in [d["dir_id"] for d in share_top_dirs]:
            new_parent_id = UPLOAD_TARGET_PID
        else:
            new_parent_id = dir_id_mapping.get(original_parent_id)

        if not new_parent_id:
            continue

        try:
            # 目录创建通常不变：fs_mkdir(name, parent_id)
            create_resp = client.fs_mkdir(
                name=dir_name,
                parent_id=new_parent_id,
                duplicate=1
            )
            check_response(create_resp)
            new_dir_id = create_resp["data"]["Info"]["FileId"]
            dir_id_mapping[original_dir_id] = new_dir_id
            
            child_dirs = dir_children.get(original_dir_id, [])
            dir_queue.extend(child_dirs)
        except Exception as e:
            logger.error(f"创建目录 {dir_name} 失败: {str(e)}")
            return False

    # 2. 文件转存逻辑
    MAX_BATCH_SIZE = 100
    file_batches = defaultdict(list)
    
    for file_info in all_files:
        file_id = file_info["file_id"]
        original_parent_id = file_info["parent_dir_id"]
        target_parent_id = dir_id_mapping.get(original_parent_id, UPLOAD_TARGET_PID)
        
        file_data = {
            "file_id": file_id,
            "file_name": file_info["name"],
            "etag": file_info["etag"],
            "parent_file_id": original_parent_id,
            "size": file_info["size"]
        }
        file_batches[target_parent_id].append(file_data)
    
    all_batches = []
    for target_parent_id, files_in_dir in file_batches.items():
        for i in range(0, len(files_in_dir), MAX_BATCH_SIZE):
            batch_files = files_in_dir[i:i + MAX_BATCH_SIZE]
            all_batches.append((target_parent_id, batch_files))
    
    for batch_index, (target_parent_id, batch_files) in enumerate(all_batches, 1):
        try:
            # --- 修复：回退到 share_fs_copy ---
            copy_resp = client.share_fs_copy({
                "share_key": share_key,
                "share_pwd": share_pwd,
                "file_list": batch_files,
                "current_level": 1,
                "event": "transfer"
            }, parent_id=target_parent_id)
            
            check_response(copy_resp)
            logger.info(f"批次 {batch_index} 转存成功")
            
        except Exception as e:
            logger.error(f"批次 {batch_index} 转存失败: {str(e)}")
            return False
            
    return True



class UserStateManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_file)
        # 创建表，如果不存在
        conn.execute('''CREATE TABLE IF NOT EXISTS user_states
                     (user_id INTEGER PRIMARY KEY, state TEXT, data TEXT)''')
        
        # [新增] 检查列数，如果列数不对（比如旧版留下的4列），则重建表
        try:
            cursor = conn.execute("PRAGMA table_info(user_states)")
            columns = cursor.fetchall()
            if len(columns) != 3:
                logger.warning(f"检测到 user_states 表结构不匹配（当前{len(columns)}列），正在重建...")
                conn.execute("DROP TABLE user_states")
                conn.execute('''CREATE TABLE user_states
                             (user_id INTEGER PRIMARY KEY, state TEXT, data TEXT)''')
        except Exception as e:
            logger.error(f"检查数据库结构失败: {e}")
            
        conn.commit()
        conn.close()

    def set_state(self, user_id, state, data=None):
        conn = sqlite3.connect(self.db_file)
        # [修改] 显式指定列名 (user_id, state, data)，防止因数据库列数不匹配导致的 "4 columns but 3 values" 错误
        conn.execute("INSERT OR REPLACE INTO user_states (user_id, state, data) VALUES (?, ?, ?)",
                     (user_id, state, data))
        conn.commit()
        conn.close()

    def get_state(self, user_id):
        conn = sqlite3.connect(self.db_file)
        result = conn.execute("SELECT state, data FROM user_states WHERE user_id = ?",
                              (user_id,)).fetchone()
        conn.close()
        return result if result else (None, None)

    def clear_state(self, user_id):
        conn = sqlite3.connect(self.db_file)
        conn.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()


# 初始化用户状态管理器
user_state_manager = UserStateManager(USER_STATE_DB)


# 搜索123网盘文件夹（修改结果数量为15）
async def search_123_files(client: P123Client, keyword: str) -> list:
    """搜索123网盘中的文件夹（返回最多15个结果）"""
    all_items = []
    last_file_id = 0
    try:
        for i in range(5):  # 最多3页
            response = requests.get(
                f"https://open-api.123pan.com/api/v2/file/list?parentFileId=0&searchData={encodeURIComponent(keyword)}&searchMode=1&limit=100&lastFileId={last_file_id}",
                headers={
                    'Authorization': f'Bearer {client.token}',
                    'Platform': 'open_platform'
                },
                timeout=TIMEOUT
            )
            data = response.json()
            if data.get('code') == 401 or 'expired' in str(data.get('message', '')).lower():
                raise Exception("token expired")
            if data.get('code') != 0:
                raise Exception(f"搜索失败: {data.get('message', '未知错误')}")
            items = data.get('data', {}).get('fileList', [])
            # 仅筛选文件夹（type=1）
            folder_items = [item for item in items if item.get('type') == 1]
            all_items.extend(folder_items)
            last_file_id = data.get('data', {}).get('lastFileId', -1)
            if last_file_id == -1:
                break

        # 限制最多返回15个结果
        results = []
        # 批量处理15个结果，获取完整路径
        items_to_process = all_items[:20]  # 限制为15个结果
        logger.info(f"准备批量处理{len(items_to_process)}个文件夹结果")
        
        # 使用批量构建路径函数
        # 注意：即使只有15个文件夹项目，由于需要获取各级父目录信息，所以实际查询的ID数量会多于15个
        # 这种设计可以显著减少API调用次数，提高路径构建效率

        paths_map = await batch_build_full_paths(client, items_to_process)
        
        # 创建映射，以便快速查找item信息
        item_map = {str(item.get('fileId', '')): item for item in items_to_process if str(item.get('fileId', ''))}
        
        # 遍历paths_map的键值对，使results的顺序与paths_map的顺序保持一致
        for file_id, full_path in paths_map.items():
            item = item_map.get(file_id)
            if not item:
                continue
            
            results.append({
                "id": file_id,
                "name": item.get('filename'),
                "type": "文件夹",
                "path": full_path,  # 完整路径
                "create_time": item.get('createTime')
            })
        
        # 如果还有未在paths_map中的项目，也添加到results中
        for item in items_to_process:
            file_id = str(item.get('fileId', ''))
            if not file_id or file_id in paths_map:
                continue
            
            full_path = item.get('filename', '')
            results.append({
                "id": file_id,
                "name": item.get('filename'),
                "type": "文件夹",
                "path": full_path,  # 完整路径
                "create_time": item.get('createTime')
            })
        return results
    except Exception as e:
        logger.error(f"搜索文件夹失败: {str(e)}")
        raise


def get_folder_detail(client: P123Client, file_id: str) -> dict:
    """获取文件夹详情"""
    if not file_id:
        logger.error("文件夹ID为空")
        return {"filename": ""}
    try:
        response = requests.get(
            f"https://open-api.123pan.com/api/v1/file/detail?fileID={file_id}",
            headers={
                'Authorization': f'Bearer {client.token}',
                'Platform': 'open_platform'
            },
            timeout=TIMEOUT
        )
        data = response.json()
        if data.get('code') != 0:
            logger.error(f"获取文件夹{file_id}详情失败: {data.get('message')}")
            return {"filename": ""}
        return data.get('data', {})
    except Exception as e:
        logger.error(f"获取文件夹{file_id}详情异常: {str(e)}")
        return {"filename": ""}


def get_files_details(client: P123Client, file_ids: list) -> dict:
    """批量获取文件/文件夹详情"""
    if not file_ids:
        logger.error("文件ID列表为空")
        return {}
    try:
        logger.info(f"请求以下父目录ID详情：{file_ids}")
        response = requests.post(
            "https://open-api.123pan.com/api/v1/file/infos",
            headers={
                'Authorization': f'Bearer {client.token}',
                'Platform': 'open_platform',
                'Content-Type': 'application/json'
            },
            json={"fileIds": file_ids},
            timeout=TIMEOUT
        )
        data = response.json()
        #logger.info(f"以下父目录详情：{data}")
        if data.get('code') != 0:
            logger.error(f"批量获取文件详情失败: {data.get('message', '未知错误')}")
            return {}
        details_map = {}
        # 注意：API返回的字段名是fileList，不是list
        for item in data.get('data', {}).get('fileList', []):
            file_id = str(item.get('fileId'))
            details_map[file_id] = item
        return details_map
    except Exception as e:
        logger.error(f"批量获取文件详情异常: {str(e)}")
        return {}


async def build_full_path(client: P123Client, item: dict) -> str:
    """构建文件夹完整路径（用于显示） - 单个处理版本（保持向后兼容）"""
    # 由于已经实现了批量构建路径的功能，这里可以保留为向后兼容或简单调用
    paths_map = await batch_build_full_paths(client, [item])
    file_id = str(item.get('fileId', ''))
    return paths_map.get(file_id, item.get('filename', ''))


async def batch_build_full_paths(client: P123Client, items: list) -> dict:
    """批量构建多个文件夹的完整路径（修复全局缓存问题，确保父ID详情不丢失）"""
    path_map = {}
    if not items:
        return path_map
    
    query_level = 4  # 保持固定4层
    temp_path_map = {}
    queried_ids = set()  # 已查询过的ID（避免重复请求）
    current_query_ids = set()  # 当前轮需查询的ID
    global_details_cache = {}  # 新增：全局缓存，保存所有已查询的父目录详情（跨轮复用）
    
    # 初始化：收集每个文件的初始信息
    logger.info(f"开始处理{len(items)}个文件夹项目，query_level={query_level}")
    for item in items:
        file_id = str(item.get('fileId', ''))
        if not file_id:
            continue
        
        temp_path_map[file_id] = {
            'path_parts': [item.get('filename', '')],
            'current_parent_id': item.get('parentFileId'),
            'remaining_levels': query_level
        }
        
        parent_id = item.get('parentFileId')
        if parent_id and parent_id != 0:
            current_query_ids.add(str(parent_id))
    
    logger.info(f"第一轮查询（第1层父目录）：{len(current_query_ids)}个ID，处理{len(temp_path_map)}个文件")
    
    # 迭代查询父目录（4轮）
    for level in range(query_level):
        if not current_query_ids:
            logger.info(f"第{level+1}轮无父ID可查，提前结束")
            break
        
        logger.info(f"第{level+1}轮查询（剩余层级：{query_level - level}）：{len(current_query_ids)}个ID")
        
        # 1. 新增：查询当前轮ID，合并到全局缓存
        current_details = get_files_details(client, list(current_query_ids))
        global_details_cache.update(current_details)  # 关键：将当前轮详情存入全局缓存
        
        next_query_ids = set()
        
        # 2. 处理每个文件的父目录链：从全局缓存获取详情，而非当前轮缓存
        for file_id, info in temp_path_map.items():
            if info['remaining_levels'] <= 0:
                continue
            
            current_parent_id = info['current_parent_id']
            if not current_parent_id or current_parent_id == 0:
                continue
            
            current_parent_id_str = str(current_parent_id)
            # 关键：从全局缓存获取详情，而非当前轮缓存
            parent_detail = global_details_cache.get(current_parent_id_str)
            
            if not parent_detail:
                logger.warning(f"第{level+1}轮：全局缓存中未找到ID[{current_parent_id_str}]的详情，停止该文件的上层查询")
                info['remaining_levels'] = 0
                continue
            
            # 提取父目录名称，更新路径
            parent_name = parent_detail.get('filename', '')
            if parent_name:
                # 新增：避免重复添加同一目录（防止异常情况下的重复）
                if not info['path_parts'] or info['path_parts'][0] != parent_name:
                    info['path_parts'].insert(0, parent_name)
                logger.debug(f"文件[{file_id}]第{level+1}层父目录：{parent_name}，当前路径：{'/'.join(info['path_parts'])}")
            
            # 获取下一层父ID，加入下轮查询（需未查询过）
            next_parent_id = parent_detail.get('parentFileId')
            if next_parent_id and next_parent_id != 0:
                next_parent_id_str = str(next_parent_id)
                if (next_parent_id_str not in queried_ids and 
                    next_parent_id_str not in current_query_ids and 
                    next_parent_id_str not in next_query_ids):
                    next_query_ids.add(next_parent_id_str)
                info['current_parent_id'] = next_parent_id
            else:
                info['remaining_levels'] = 0
            
            # 剩余层级-1
            info['remaining_levels'] -= 1
        
        # 更新已查询ID和下轮查询ID
        queried_ids.update(current_query_ids)
        current_query_ids = next_query_ids
    
    # 4轮查询完成后，从全局缓存中继续构建路径（不发起新请求）
    logger.info("4轮查询已完成，开始从全局缓存中继续构建路径（不发起新请求）")
    has_more_to_process = True
    while has_more_to_process:
        has_more_to_process = False
        for file_id, info in temp_path_map.items():
            current_parent_id = info['current_parent_id']
            if not current_parent_id or current_parent_id == 0:
                continue
            
            current_parent_id_str = str(current_parent_id)
            # 只从全局缓存中获取详情，不发起新请求
            parent_detail = global_details_cache.get(current_parent_id_str)
            
            if parent_detail:
                # 提取父目录名称，更新路径
                parent_name = parent_detail.get('filename', '')
                if parent_name:
                    if not info['path_parts'] or info['path_parts'][0] != parent_name:
                        info['path_parts'].insert(0, parent_name)
                    logger.debug(f"从缓存中补充路径：文件[{file_id}]新增父目录：{parent_name}，当前路径：{'/'.join(info['path_parts'])}")
                
                # 更新下一层父ID
                next_parent_id = parent_detail.get('parentFileId')
                if next_parent_id and next_parent_id != 0:
                    info['current_parent_id'] = next_parent_id
                    has_more_to_process = True  # 还有更多父ID可以从缓存中查找
                else:
                    info['current_parent_id'] = 0
            else:
                info['current_parent_id'] = 0  # 缓存中没有，停止查找
    
    # 构建最终路径 - 按路径字符串排序，使相同公共前缀的文件夹优先放在一起
    # 首先获取所有项，然后按路径字符串排序
    sorted_items = sorted(temp_path_map.items(), key=lambda x: '/'.join(x[1]['path_parts']))

    for file_id, info in sorted_items:
        full_path = '/'.join(info['path_parts'])
        path_map[file_id] = full_path
        logger.debug(f"文件[{file_id}]最终路径：{full_path}")
    logger.info(f"批量路径构建完成，生成{len(path_map)}个文件路径（query_level=4，缓存补充完成）")
    return path_map


def encodeURIComponent(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe='~()*!.\'')


def create_share_link(client: P123Client, file_id: str, expiry_days: int = 0, password: str = None) -> dict:
    """创建分享链接"""
    if not file_id or not str(file_id).strip():
        raise ValueError("文件夹ID为空或无效")

    valid_expire_days = {0, 1, 7, 30}
    if expiry_days not in valid_expire_days:
        logger.warning(f"过期天数{expiry_days}无效，自动使用7天")
        expiry_days = 7

    try:
        folder_detail = get_folder_detail(client, file_id)
        folder_name = folder_detail.get('filename', f"分享文件夹_{file_id}")
        if not folder_name:
            logger.warning(f"文件夹ID{file_id}不存在，可能已被删除")

        response = requests.post(
            "https://open-api.123pan.com/api/v1/share/create",
            headers={
                'Authorization': f'Bearer {client.token}',
                'Platform': 'open_platform',
                'Content-Type': 'application/json'
            },
            json={
                "shareName": folder_name,
                "shareExpire": expiry_days,
                "fileIDList": file_id,
                "sharePwd": DIY_LINK_PWD
            },
            timeout=TIMEOUT
        )
        data = response.json()
        if data.get('code') != 0:
            raise Exception(f"创建分享失败: {data.get('message', '未知错误')}（ID: {file_id}）")
        share_info = data.get('data', {})
        if expiry_days == 0:
            expiry_str = "永久有效"
        else:
            expiry_time = int(time.time()) + expiry_days * 86400
            expiry_str = datetime.fromtimestamp(expiry_time).strftime('%Y-%m-%d %H:%M:%S')
        return {
            "url": f"https://www.123pan.com/s/{share_info.get('shareKey')}{'?pwd=' + DIY_LINK_PWD if DIY_LINK_PWD else ''}",
            "password": share_info.get('sharePwd'),
            "expiry": expiry_str
        }
    except Exception as e:
        logger.error(f"创建分享链接失败: {str(e)}")
        raise


def get_first_video_file(client: P123Client, file_id: str) -> str:
    """获取文件夹或子文件夹中第一个视频文件的名称"""
    video_extensions = {'.mkv', '.ts', '.mp4', '.avi', '.rmvb', '.wmv', '.m2ts', '.mpg', '.flv', '.rm', '.mov', '.iso'}

    def recursive_search(folder_id: str) -> str:
        try:
            # 调用123网盘API列出文件夹内容
            resp = client.fs_list(folder_id)
            check_response(resp)
            items = resp["data"]["InfoList"]

            # 优先检查当前文件夹的文件
            for item in items:
                if item["Type"] == 0:  # 类型为文件
                    filename = item["FileName"]
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in video_extensions:
                        return filename

            # 递归检查子文件夹
            for item in items:
                if item["Type"] == 1:  # 类型为文件夹
                    sub_result = recursive_search(item["FileId"])
                    if sub_result:
                        return sub_result
            return None
        except Exception as e:
            logger.error(f"搜索视频文件失败: {str(e)}")
            return None

    return recursive_search(file_id)

@bot.message_handler(commands=['info'])
def handle_info(message):
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "您没有权限使用此机器人。")
        return
    client = init_123_client()
    response = client.user_info()  # 验证token有效性
    def mask_uid(uid):
        """账户ID脱敏：1846764956 → 184****956"""
        uid_str = str(uid)
        return f"{uid_str[:3]}****{uid_str[-3:]}" if len(uid_str)>=6 else uid_str

    def mask_mobile(mobile):
        """手机号脱敏：18221643386 → 182****3386"""
        mobile_str = str(mobile)
        return f"{mobile_str[:3]}****{mobile_str[-4:]}" if len(mobile_str)==11 else mobile_str

    def format_size(size):
        """字节转TB/GB（自动适配单位）"""
        if size <= 0:
            return "0.00 GB"
        tb = size / (1024 **4)
        return f"{tb:.2f} TB" if tb >= 1 else f"{size / (1024** 3):.2f} GB"

    def space_progress(used, total, bar_len=10):
        """生成进度条：▓=已用，░=剩余"""
        if total == 0:
            return "□□□□□□□□□□ (0%)"
        ratio = used / total
        filled = int(ratio * bar_len)
        bar = "▓" * filled + "░" * (bar_len - filled)
        percent = f"{ratio*100:.1f}%"
        return f"{bar} ({percent})"

    # 假设响应数据为 `response`
    data = response["data"]

    # 1. 标题与账户信息
    base_title = "🚀 123云盘信息"

    account_info = f"""👤 账户信息
    ├─ 昵称：{data['Nickname']} {'🎖️VIP' if data['Vip'] else ''}
    ├─ 账户ID：{mask_uid(data['UID'])}
    ├─ 手机号：{mask_mobile(data['Passport'])}
    └─ 微信绑定：{"✅已绑" if data['BindWechat'] else "❌未绑"}"""

    # 2. 存储空间（带进度条）
    used = data['SpaceUsed']
    total = data['SpacePermanent']
    storage_progress = space_progress(used, total)

    storage_info = f"""💾 存储空间 {storage_progress}
    ├─ 已用：{format_size(used)}
    ├─ 永久：{format_size(total)}
    └─ 文件总数：{data['FileCount']:,} 个"""

    # 3. VIP详情（拆分多个权益）
    vip_details = []
    # 添加基础VIP信息
    #vip_details.append(f"├─ 等级：{data['VipLevel']} | 类型：{data['VipExplain']}")
    #vip_details.append(f"├─ 到期时间：{data['VipExpire']}")
    #vip_details.append(f"└─ 权益列表：")

    # 逐个添加VIP权益（单独成项）
    for i, vip in enumerate(data['VipInfo'], 1):
        # 最后一个权益用特殊符号
        symbol = "    └─" if i == len(data['VipInfo']) else "    ├─"
        vip_details.append(f"{symbol} {vip['vip_label']}：{vip['start_time']} → {vip['end_time']}")

    vip_info = "💎 VIP会员\n" + "\n".join(vip_details)

    # 4. 流量与功能状态
    traffic_info = f"""🚀 流量与功能
    ├─ 直连流量：{format_size(data['DirectTraffic'])}
    ├─ 分享流量：{format_size(data['ShareTraffic'])}
    └─ 直链功能：{"✅开启" if data['StraightLink'] else "❌关闭"}"""

    # 5. 备份信息
    backup_info = f"""📦 备份配置
    ├─ 移动端：{data['BackupFileInfo']['MobileTerminalBackupFileName']}
    └─ 桌面端：{data['BackupFileInfo']['DesktopTerminalBackupFileName']}"""

    # 拼接最终消息
    tg_message = "\n\n".join([
        base_title,
        account_info,
        storage_info,
        vip_info,
        traffic_info,
        backup_info
    ])
    # 最后一次性打印完整消息
    reply_thread_pool.submit(send_reply, message, tg_message)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        bot.answer_callback_query(call.id, "无权操作", show_alert=True)
        return

    if call.data == "show_usage":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, USE_METHOD)
    elif call.data == "show_disclaimer":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, DISCLAIMER_TEXT)
    elif call.data == "show_userbot_help":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, USERBOT_HELP)   

# Telegram机器人消息处理
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "您没有权限使用此机器人。")
        return

    # 构造按钮键盘
    markup = InlineKeyboardMarkup()
    # 第一行：使用说明 | 免责声明
    markup.row(InlineKeyboardButton("📖 使用说明", callback_data="show_usage"),
               InlineKeyboardButton("⚠️ 免责声明", callback_data="show_disclaimer"))
    # 第二行：人形命令 | 项目地址
    markup.row(InlineKeyboardButton("🤖 人形命令", callback_data="show_userbot_help"),
               InlineKeyboardButton("🌟 项目地址", url="https://github.com/dydydd/123bot"))
    
    # 发送简洁的启动消息
    bot.send_message(
        message.chat.id, 
        f"叮咚，我已成功启动，欢迎使用123bot！\n\n ═════当前版本❀{version}═════\n\n", 
        parse_mode='HTML', 
        reply_markup=markup
    )

def save_env_filter(new_filter_value):
    """持久化保存过滤词到db/user.env文件"""
    env_file_path = os.path.join('db', 'user.env')
    
    # 确保文件存在
    if not os.path.exists(env_file_path):
        logger.warning(f"{env_file_path} 文件不存在")
        return False
    
    try:
        # 读取文件内容
        with open(env_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 查找并替换ENV_FILTER行
        updated_lines = []
        found = False
        for line in lines:
            if line.startswith('ENV_FILTER='):
                updated_lines.append(f'ENV_FILTER={new_filter_value}\n')
                found = True
            else:
                updated_lines.append(line)
        
        # 如果没找到ENV_FILTER行，则添加
        if not found:
            # 找到频道监控配置部分，在合适的位置添加
            insert_index = -1
            for i, line in enumerate(lines):
                if '# 检查新消息的时间间隔（分钟）' in line:
                    insert_index = i + 2
                    break
            if insert_index != -1:
                updated_lines.insert(insert_index, f'ENV_FILTER={new_filter_value}\n')
            else:
                # 如果找不到合适位置，就添加到文件末尾
                updated_lines.append(f'\nENV_FILTER={new_filter_value}\n')
        
        # 写回文件
        with open(env_file_path, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)
        
        return True
    except Exception as e:
        logger.error(f"保存环境变量失败：{str(e)}")
        return False

@bot.message_handler(commands=['add'])
def add_filter(message):
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "您没有权限使用此机器人。")
        return
    global FILTER, filter_pattern
    try:
        # 展示当前过滤词和用法
        current_filters_text = FILTER if FILTER else "无（未设置任何过滤词）"
        usage_text = "ℹ️ 用法：\n- 添加过滤词：/add 关键词\n（例：/add WALK   /add WALK|权力的游戏）\n- 删除过滤词：/remove 关键词\n（例：/remove 权力的游戏   /remove WALK|权力的游戏）"
        
        # 检查是否有参数
        if len(message.text.split()) < 2:
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n❌ 请输入要添加的过滤词（例：/add WALK）\n\n{usage_text}")
            logger.error(f"用户 {message.from_user.id} 执行/add失败：无输入参数")
            return
        
        # 获取用户输入的过滤词并清理
        new_filters_text = message.text.split(maxsplit=1)[1].strip()
        
        # 检查是否为空字符串
        if not new_filters_text:
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n❌ 请输入要添加的过滤词（例：/add WALK 或 /add WALK|权力的游戏）\n\n{usage_text}")
            logger.error(f"用户 {message.from_user.id} 执行/add失败：参数为空")
            return
        
        # 拆分用户输入的多个过滤词
        new_filters_list = [f.strip() for f in new_filters_text.split("|") if f.strip()]
        
        # 拆分现有过滤词
        current_filters = FILTER.split("|") if FILTER else []
        
        # 记录添加结果
        added_filters = []
        existing_filters = []
        
        # 检查每个过滤词是否已存在并添加
        for new_filter in new_filters_list:
            if new_filter not in current_filters:
                added_filters.append(new_filter)
                current_filters.append(new_filter)
            else:
                existing_filters.append(new_filter)
        
        # 如果没有添加任何新过滤词
        if not added_filters:
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n⚠️ 所有过滤词「{', '.join(existing_filters)}」已存在，无需重复添加\n\n{usage_text}")
            return
        
        # 构建新的过滤词字符串
        FILTER = "|".join(current_filters)
        
        # 持久化保存到文件
        if not save_env_filter(FILTER):
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n⚠️ 过滤词添加成功，但保存到文件失败，请手动在配置页面更新\n\n{usage_text}")
        
        # 重建正则对象
        filter_pattern = re.compile(FILTER, re.IGNORECASE)
        
        # 构建反馈消息
        feedback_msg = f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n"
        
        if added_filters:
            feedback_msg += f"✅ 已添加过滤词：「{', '.join(added_filters)}」\n"
        
        if existing_filters:
            feedback_msg += f"⚠️ 已存在的过滤词：「{', '.join(existing_filters)}」\n"
        
        feedback_msg += f"📌 更新后过滤词：{FILTER}\n\n{usage_text}"
        
        # 发送成功反馈
        reply_thread_pool.submit(send_reply, message, feedback_msg)
        logger.info(f"用户 {message.from_user.id} 执行/add，添加过滤词：{', '.join(added_filters)}，已存在：{', '.join(existing_filters)}，更新后：{FILTER}")
        
    except Exception as e:
        reply_thread_pool.submit(send_reply, message, f"操作失败：{str(e)}")
        logger.info(f"用户 {message.from_user.id} 执行/add出错：{str(e)}")

@bot.message_handler(commands=['remove'])
def remove_filter(message):
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "您没有权限使用此机器人。")
        return

    global FILTER, filter_pattern
    try:
        # 展示当前过滤词和用法
        current_filters_text = FILTER if FILTER else "无（未设置任何过滤词）"
        usage_text = "ℹ️ 用法：\n- 添加过滤词：/add 关键词（例：/add WALK）\n- 删除过滤词：/remove 关键词（例：/remove 权力的游戏）"
        
        # 检查当前是否有过滤词
        if not FILTER:
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n⚠️ 当前无任何过滤词，无需删除\n\n{usage_text}")
            logger.error(f"用户 {message.from_user.id} 执行/remove失败：当前无过滤词")
            return
        
        # 检查是否有参数
        if len(message.text.split()) < 2:
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n❌ 请输入要删除的过滤词（例：/remove 权力的游戏）\n\n{usage_text}")
            logger.error(f"用户 {message.from_user.id} 执行/remove失败：无输入参数")
            return
        
        # 获取用户输入的过滤词并清理
        del_filters_text = message.text.split(maxsplit=1)[1].strip()
        
        # 检查是否为空字符串
        if not del_filters_text:
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n❌ 请输入要删除的过滤词（例：/remove 权力的游戏 或 /remove WALK|权力的游戏）\n\n{usage_text}")
            logger.error(f"用户 {message.from_user.id} 执行/remove失败：参数为空")
            return
        
        # 拆分用户输入的多个过滤词
        del_filters = [f.strip() for f in del_filters_text.split("|") if f.strip()]
        
        # 拆分现有过滤词
        current_filters = FILTER.split("|") if FILTER else []
        
        # 记录删除结果
        deleted_filters = []
        not_found_filters = []
        
        # 检查每个过滤词是否存在并删除
        for del_filter in del_filters:
            if del_filter in current_filters:
                deleted_filters.append(del_filter)
            else:
                not_found_filters.append(del_filter)
        
        # 删除存在的过滤词
        new_filters = [f for f in current_filters if f not in deleted_filters]
        FILTER = "|".join(new_filters) if new_filters else ""
        
        # 持久化保存到文件
        if not save_env_filter(FILTER):
            reply_thread_pool.submit(send_reply, message, f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n⚠️ 过滤词删除成功，但保存到文件失败，请手动在配置页面更新\n\n{usage_text}")

        # 重建正则对象
        filter_pattern = re.compile(FILTER, re.IGNORECASE)
        
        # 构建反馈消息
        updated_filters_text = FILTER if FILTER else "无"
        feedback_msg = f"📌 当前过滤词：{current_filters_text} （多个用|分隔，命中的内容会被转存，为空则会转存所有资源）\n"
        
        if deleted_filters:
            feedback_msg += f"✅ 已删除过滤词：「{', '.join(deleted_filters)}」\n"
        
        if not_found_filters:
            feedback_msg += f"⚠️ 未找到的过滤词：「{', '.join(not_found_filters)}」\n"
        
        feedback_msg += f"📌 更新后过滤词：{updated_filters_text}\n\n{usage_text}"
        
        # 发送成功反馈
        reply_thread_pool.submit(send_reply, message, feedback_msg)
        logger.info(f"用户 {message.from_user.id} 执行/remove，删除过滤词：{', '.join(deleted_filters)}，未找到：{', '.join(not_found_filters)}，更新后：{FILTER}")
        
    except Exception as e:
        reply_thread_pool.submit(send_reply, message, f"操作失败：{str(e)}")
        logger.error(f"用户 {message.from_user.id} 执行/remove出错：{str(e)}")

@bot.message_handler(commands=['share', 's123'])
def handle_share_command(message):
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "您没有权限使用此命令。")
        return
    try:
        command_used = message.text.split()[0].replace('/', '')
        command_parts = message.text.split(' ', 1)
        
        if len(command_parts) < 2 or not command_parts[1].strip():
            reply_thread_pool.submit(send_reply, message, f"请提供搜索关键词，例如：/{command_used} 权力的游戏")
            return
        
        keyword = command_parts[1].strip()
        
        # 根据命令确定模式
        mode = "json" if "s123" in command_used else "link"
        mode_text = "JSON生成" if mode == "json" else "分享链接"
        
        reply_thread_pool.submit(send_reply, message, f"正在搜索包含 '{keyword}' 的文件夹 ({mode_text}模式)...")
        client = init_123_client()
        import threading
        # 传入 mode
        threading.Thread(target=perform_search, args=(client, keyword, user_id, message.chat.id, mode)).start()
    except Exception as e:
        reply_thread_pool.submit(send_reply, message, f"操作失败: {str(e)}")
        logger.error(f"处理命令失败: {str(e)}")

def build_folder_message(results):
    """
    核心规则：
    1. 编号顺序：1-20严格对应输入顺序，不打乱、不重排
    2. 大组划分：按“原始编号连续+前两层目录相同”划大组（非连续/前缀不同则单独成组）
    3. 组内合并：每个大组内计算所有路径的公共前缀（含前两层外的深层前缀），合并为父目录
    4. 单独组处理：组内仅1条路径时，自动作为单独组，不强制合并公共前缀
    """
    # 步骤1：预处理路径，提取关键信息（保留原始编号）
    path_info_list = []
    for orig_seq, item in enumerate(results, start=1):  # 原始编号1-20
        raw_path = item.get("path", "").strip("/")
        dir_list = [p.strip() for p in raw_path.split("/") if p.strip()]  # 拆分目录列表
        dir_len = len(dir_list)
        
        # 提取前两层目录作为分组key（不足两层则取实际层数，如1层）
        if dir_len >= 2:
            group_key = tuple(dir_list[:2])  # 前两层目录作为key（如("Resource","大包资源")）
        else:
            group_key = tuple(dir_list)  # 不足两层，用全部目录作为key（如("Video",)）
        
        path_info_list.append({
            "orig_seq": orig_seq,
            "raw_path": raw_path,
            "dir_list": dir_list,
            "dir_len": dir_len,
            "group_key": group_key,
            "is_root": dir_len == 1  # 根目录判断：仅1层目录
        })
    if not path_info_list:
        return "未找到匹配文件夹"

    # 工具函数1：计算一组路径的公共前缀长度（核心修正！）
    def get_group_common_prefix(group_paths):
        if len(group_paths) == 1:
            # 单独组：公共前缀取到“倒数第二层”，确保子路径显示最后1层
            single_path = group_paths[0]
            return max(0, single_path["dir_len"] - 1)
        # 多路径组：关键修正——公共前缀长度 ≤ 最短路径的dir_len - 1
        min_dir_len = min(p["dir_len"] for p in group_paths)
        max_allowed_len = min_dir_len - 1  # 禁止公共前缀包含最短路径的最后一层
        base_dir = group_paths[0]["dir_list"]
        common_len = max_allowed_len  # 初始化为最大允许长度
        # 比较所有路径，找到最长公共前缀（不超过max_allowed_len）
        for p in group_paths[1:]:
            curr_dir = p["dir_list"]
            curr_common = 0
            while curr_common < common_len and curr_dir[curr_common] == base_dir[curr_common]:
                curr_common += 1
            if curr_common < common_len:
                common_len = curr_common
            if common_len == 0:
                break
        return common_len

    # 工具函数2：生成父目录字符串和子路径字符串
    def get_parent_subpath(path, common_len):
        dir_list = path["dir_list"]
        # 父目录：公共前缀部分
        parent_dir = dir_list[:common_len] if common_len > 0 else []
        parent_str = " / ".join(parent_dir) if parent_dir else ("根目录" if path["is_root"] else "")
        # 子路径：公共前缀之后的部分（若为空，显示最后1层目录）
        sub_dir = dir_list[common_len:] if common_len < path["dir_len"] else [dir_list[-1]]
        sub_path_str = " / ".join(sub_dir)
        return parent_str, sub_path_str

    # 步骤2：按“编号连续+group_key相同”划大组（核心分组逻辑）
    groups = []
    if path_info_list:
        current_group = [path_info_list[0]]  # 初始化当前组（第一个路径）
        for path in path_info_list[1:]:
            prev_path = current_group[-1]
            # 判断：当前路径与前一个路径“编号连续（必然满足，按顺序遍历）且group_key相同”
            if path["group_key"] == prev_path["group_key"]:
                current_group.append(path)
            else:
                # 不同group_key，保存当前组，新建组
                groups.append(current_group)
                current_group = [path]
        groups.append(current_group)  # 加入最后一个组

    # 步骤3：处理每个大组，合并组内公共前缀
    processed_groups = []
    for group in groups:
        common_len = get_group_common_prefix(group)  # 组内公共前缀长度
        group_parent = ""  # 组的统一父目录（取第一条路径的父目录，组内所有路径父目录相同）
        group_paths = []
        
        for path in group:
            parent_str, sub_path_str = get_parent_subpath(path, common_len)
            # 统一组的父目录（组内所有路径父目录一致，取第一条的即可）
            if not group_parent:
                group_parent = parent_str
            # 收集组内路径（含原始编号和子路径）
            group_paths.append({
                "orig_seq": path["orig_seq"],
                "sub_path": sub_path_str
            })
        
        processed_groups.append({
            "parent_str": group_parent,
            "paths": group_paths  # 组内路径按原始编号顺序
        })

    # 步骤4：按原始编号1-20拼接最终消息（确保顺序不变）
    msg = "找到以下匹配的文件夹，请输入序号选择：\n\n"
    # 用字典暂存所有路径（key=原始编号，value=（父目录，子路径））
    seq_path_dict = {}
    for group in processed_groups:
        parent = group["parent_str"]
        for path in group["paths"]:
            seq_path_dict[path["orig_seq"]] = (parent, path["sub_path"])

    # 按编号1-20依次遍历，显示结果
    last_parent = None  # 避免重复显示父目录
    for orig_seq in range(1, len(seq_path_dict) + 1):
        parent, sub_path = seq_path_dict[orig_seq]
        
        # 父目录变化时，显示新父目录
        if parent != last_parent:
            msg += f"📁 {parent}\n"
            last_parent = parent
        
        # 显示编号和子路径
        msg += f"      {orig_seq}：{sub_path}\n"

        # 组间空行（判断下一个编号的父目录是否变化）
        next_seq = orig_seq + 1
        if next_seq in seq_path_dict:
            next_parent = seq_path_dict[next_seq][0]
            if next_parent != parent:
                msg += "\n"

    msg += "\n请输入序号（例：1）选择，多选用空格分隔（例：1 2 3）"
    return msg




def perform_search(client, keyword, user_id, chat_id, mode="link"):
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(search_123_files(client, keyword))
        if not results:
            reply_thread_pool.submit(send_message_with_id, chat_id, "没有找到匹配的文件夹")
            return
        
        # 将结果和模式一起存入状态
        state_data = {
            "results": results,
            "mode": mode
        }
        user_state_manager.set_state(user_id, "SELECTING_FILE", json.dumps(state_data))
        
        folder_message = build_folder_message(results)
        reply_thread_pool.submit(send_message_with_id, chat_id, folder_message)
    except Exception as e:
        reply_thread_pool.submit(send_message_with_id, chat_id, f"搜索文件夹失败: {str(e)}")
        logger.error(f"搜索文件夹失败: {str(e)}")

from add_mag import submit_magnet_video_download
def add_magnet_links(client: P123Client, text, upload_dir=None, message=None):
    """识别文本中的多个磁力链接并添加到离线下载"""
    import re
    magnet_pattern = r'magnet:\?xt=urn:btih:(?:[A-Fa-f0-9]{40}(?![A-Fa-f0-9])|[A-Za-z0-9]{32}(?![A-Za-z0-9]))(?:&.*?)?'
    magnet_links = re.findall(magnet_pattern, text)
    magnet_links = list(set(magnet_links))
    if not magnet_links:
        return {'status': 'error', 'message': '未找到磁力链接', 'added_count': 0}
    
    logger.debug(f"找到磁力链接:{magnet_links}")
    if message:
        reply_thread_pool.submit(send_reply, message, f"找到{len(magnet_links)}条磁力链\n正在添加...")
    
    added_count = 0
    responses = []
    try:
        for link in magnet_links:
            # 新版库通常使用 offline_download_add_url
            # 参数可能是 url, save_path=None, ...
            # 如果新版库移除了 offline_add，请使用下面的标准方法
            try:
                # 尝试使用新版方法
                response = client.offline_download_add_url(
                    url=link,
                    parent_id=upload_dir
                )
            except AttributeError:
                # 回退到 helper 函数
                response = submit_magnet_video_download(link, client.token, upload_dir)
                
            time.sleep(0.5)
            responses.append({'link': link, 'response': response})
            added_count += 1
        return {'status': 'success', 'data': responses, 'added_count': added_count}
    except Exception as e:
        return {'status': 'error', 'message': f'添加磁力链接失败: {str(e)}', 'added_count': added_count}

import base64
import binascii
import re

def robust_normalize_md5(input_str):
    """
    自动识别MD5格式并转换为十六进制格式，异常时返回原始输入
    
    参数:
        input_str: 待处理的输入（可以是任何类型）
    
    返回:
        转换后的十六进制MD5（小写），或原始输入（处理失败时）
    """
    # 先检查是否为字符串类型，非字符串直接返回原始值
    if not isinstance(input_str, str):
        return input_str
    
    # 处理空字符串
    if not input_str:
        return input_str
    
    # 去除首尾空格
    processed_str = input_str.strip()
    
    # 检查是否为十六进制MD5（32位，仅含0-9、a-f、A-F）
    hex_pattern = re.compile(r'^[0-9a-fA-F]{32}$')
    if hex_pattern.match(processed_str):
        return processed_str.lower()
    
    # 尝试Base64解码处理
    try:
        # 尝试Base64解码（处理标准Base64和URL安全的Base64）
        binary_data = base64.b64decode(processed_str, validate=True)
        
        # 验证MD5固定长度（16字节）
        if len(binary_data) == 16:
            # 转换为十六进制字符串（小写）
            return binascii.hexlify(binary_data).decode('utf-8').lower()
    
    # 捕捉Base64解码相关异常
    except binascii.Error:
        pass
    # 捕捉其他可能的异常
    except Exception:
        pass
    
    # 所有处理失败，返回原始输入
    return input_str

def parse_share_link(message, share_link, up_load_pid=UPLOAD_JSON_TARGET_PID, send_messages=True):
    """
    解析秒传链接并转存 (适配新版 p123client + 日志增强版)
    """
    # ================= 链接解析部分 (保持原逻辑) =================
    if '#' in share_link and '$' in share_link:
        pass
    else:
        return False
        
    logger.info("正在解析秒传链接...")
    
    common_base_path = ""
    is_common_path_format = False
    is_v2_etag_format = False
    
    # 定义前缀常量
    LEGACY_FOLDER_LINK_PREFIX_V1 = "123FSLinkV1$"
    LEGACY_FOLDER_LINK_PREFIX_V2 = "123FSLinkV2$"
    COMMON_PATH_LINK_PREFIX_V1 = "123FLCPV1$"
    COMMON_PATH_LINK_PREFIX_V2 = "123FLCPV2$"
    COMMON_PATH_DELIMITER = "%"
    
    # 判断链接版本并剥离前缀
    if share_link.startswith(COMMON_PATH_LINK_PREFIX_V2):
        is_common_path_format = True
        is_v2_etag_format = True
        share_link = share_link[len(COMMON_PATH_LINK_PREFIX_V2):]
    elif share_link.startswith(COMMON_PATH_LINK_PREFIX_V1):
        is_common_path_format = True
        share_link = share_link[len(COMMON_PATH_LINK_PREFIX_V1):]
    elif share_link.startswith(LEGACY_FOLDER_LINK_PREFIX_V2):
        is_v2_etag_format = True
        share_link = share_link[len(LEGACY_FOLDER_LINK_PREFIX_V2):]
    elif share_link.startswith(LEGACY_FOLDER_LINK_PREFIX_V1):
        share_link = share_link[len(LEGACY_FOLDER_LINK_PREFIX_V1):]
        
    if is_common_path_format:
        delimiter_pos = share_link.find(COMMON_PATH_DELIMITER)
        if delimiter_pos > -1:
            common_base_path = share_link[:delimiter_pos]
            share_link = share_link[delimiter_pos + 1:]
            
    # 解析文件列表
    files = []
    for s_link in share_link.split('$'):
        if not s_link: continue
        parts = s_link.split('#')
        if len(parts) < 3: continue
        
        etag = parts[0]
        size = parts[1]
        file_path = '#'.join(parts[2:])
        
        if is_common_path_format and common_base_path:
            file_path = common_base_path + file_path

        # 注意：这里 file_path 可能是完整路径 "folder/file.jpg"
        if check_ext_filter(file_path):
             # 可以在这里记录日志，但为了避免刷屏，可以选择不记录或debug记录
             continue 
        # =========================
            
        files.append({
            "etag": etag,
            "size": int(size),
            "file_name": file_path,
            "is_v2_etag": is_v2_etag_format
        })
    
    logger.info(f"解析完成: 共 {len(files)} 个文件 (已过滤后缀)")
    
    if not files:
        return False

    status = True
    # 发送初始通知
    if send_messages:
        reply_thread_pool.submit(send_reply_delete, message, f"🚀 开始转存 {len(files)} 个文件...")
    
    try:
        # 开始计时
        start_time = time.time()
        
        # 初始化客户端
        client = init_123_client()
        
        # 统计变量
        results = []
        message_batch = []  # 消息批次缓存
        batch_size = 0      # 当前批次计数
        total_size = 0      # 成功转存体积
        skip_count = 0      # 跳过计数
        last_etag = None    # 上一个文件的ETag (用于去重)
        
        # 文件夹ID缓存 { "父ID/文件夹名": 新ID }
        folder_cache = {}
        target_dir_id = up_load_pid
        
        total_files = len(files)

        for i, file_info in enumerate(files):
            file_path = file_info.get('file_name', '')
            etag = file_info.get('etag', '')
            size = int(file_info.get('size', 0))
            is_v2_etag = file_info.get('is_v2_etag', False)
            
            # 数据完整性校验
            if not all([file_path, etag, size]):
                error_msg = "文件信息不完整"
                results.append({"success": False, "file_name": file_path, "error": error_msg})
                logger.error(f"❌ {file_path}: {error_msg}")
                continue
            
            try:
                # ---------------- 1. 目录结构创建 ----------------
                path_parts = file_path.split('/')
                file_name = path_parts.pop() # 取出文件名，剩下的就是目录
                current_parent_id = target_dir_id
                
                # 逐级检查/创建目录
                temp_path_str = ""
                for part in path_parts:
                    if not part: continue
                    temp_path_str = f"{temp_path_str}/{part}" if temp_path_str else part
                    cache_key = f"{current_parent_id}/{part}"
                    
                    if cache_key in folder_cache:
                        current_parent_id = folder_cache[cache_key]
                        continue
                    
                    # 创建目录 (带重试)
                    mk_retry = 2
                    folder_id = None
                    while mk_retry > 0:
                        try:
                            # client.fs_mkdir 是标准API
                            resp = client.fs_mkdir(name=part, parent_id=current_parent_id)
                            check_response(resp)
                            folder_id = resp["data"]["Info"]["FileId"]
                            break
                        except Exception as e:
                            mk_retry -= 1
                            if mk_retry == 0:
                                logger.warning(f"创建文件夹失败 '{part}': {e}")
                            time.sleep(0.5)
                    
                    if folder_id:
                        folder_cache[cache_key] = folder_id
                        current_parent_id = folder_id
                    else:
                        # 如果创建失败，尝试沿用上级ID，防止程序完全崩溃
                        pass

                # ---------------- 2. ETag 处理 ----------------
                # 如果是 V2 格式 (Base62)，转为 Hex MD5
                if is_v2_etag:
                    etag = optimized_etag_to_hex(etag, True)
                
                # 标准化 MD5 (确保小写且合法)
                final_md5 = robust_normalize_md5(etag)

                # ---------------- 3. 秒传核心逻辑 ----------------
                retry_count = 3
                rapid_resp = None
                is_skipped = False
                
                while retry_count > 0:
                    # 3.1 连续重复文件检测 (Simple Deduplication)
                    if last_etag == final_md5:
                        skip_count += 1
                        is_skipped = True
                        # 构造一个伪造的成功响应
                        rapid_resp = {"code": 0, "data": {"reuse": True, "skip": True}}
                        logger.info(f"🔄 跳过重复文件: {file_name}")
                        break
                    
                    try:
                        # 3.2 调用标准 API: upload_file_fast
                        rapid_resp = client.upload_file_fast(
                            file_name=file_name,
                            parent_id=current_parent_id,
                            file_md5=final_md5,
                            file_size=size,
                            duplicate=1
                        )
                        
                        # 3.3 判断结果
                        is_reused = rapid_resp.get("data", {}).get("Reuse") or rapid_resp.get("data", {}).get("reuse")
                        if is_reused:
                            break # 成功，跳出重试
                        else:

                            break 
                            
                    except Exception as e:
                        retry_count -= 1
                        logger.warning(f"秒传请求异常 {file_name}: {e} (剩余重试: {retry_count})")
                        time.sleep(2)
                        if retry_count == 0:
                            rapid_resp = {"code": -1, "message": str(e)}

                # ---------------- 4. 结果处理与日志记录 ----------------
                dir_path = os.path.dirname(file_path)
                
                # 成功判定：code=0 且 reuse=True (兼容大小写)
                is_success_response = rapid_resp and rapid_resp.get("code") == 0 and \
                                      (rapid_resp.get("data", {}).get("Reuse") or rapid_resp.get("data", {}).get("reuse"))

                if is_success_response:
                    
                    if is_skipped:
                        status_icon = '🔄'
                        log_msg = f"{file_name} (重复跳过)"
                    else:
                        status_icon = '✅'
                        log_msg = file_name
                        total_size += size
                        last_etag = final_md5 # 更新 last_etag
                        results.append({"success": True, "file_name": file_path, "size": size})

                    logger.info(f"{status_icon} 转存成功: {dir_path}/{log_msg}")
                    
                    # 添加到批次消息
                    message_batch.append({
                        'status': status_icon,
                        'dir': dir_path,
                        'file': log_msg
                    })
                    
                else:
                    # 失败处理
                    status_icon = '❌'
                    # 判断是否因为文件不在云端导致失败 (兼容大小写)
                    is_not_reused = rapid_resp and rapid_resp.get("code") == 0 and \
                                    not (rapid_resp.get("data", {}).get("Reuse") or rapid_resp.get("data", {}).get("reuse"))

                    if is_not_reused:
                        err_reason = "文件未在云端，无法秒传"
                    else:
                        err_reason = rapid_resp.get("message", "未知错误") if rapid_resp else "请求无响应"
                    
                    logger.warning(f"{status_icon} 转存失败: {dir_path}/{file_name} ({err_reason})")
                    
                    results.append({"success": False, "file_name": file_path, "error": err_reason})
                    
                    message_batch.append({
                        'status': status_icon,
                        'dir': dir_path,
                        'file': f"{file_name} ({err_reason})"
                    })

                batch_size += 1

                # ---------------- 5. 批次通知 (每10条) ----------------
                if batch_size % 10 == 0:
                    tree_messages = defaultdict(lambda: {'✅': [], '❌': [], '🔄': []})
                    for entry in message_batch:
                        tree_messages[entry['dir']][entry['status']].append(entry['file'])
                    
                    batch_msg_lines = []
                    for d_path, status_files in tree_messages.items():
                        for stat, f_list in status_files.items():
                            if f_list:
                                batch_msg_lines.append(f"--- {stat} {d_path}")
                                for idx, fname in enumerate(f_list):
                                    prefix = '      └──' if idx == len(f_list)-1 else '      ├──'
                                    batch_msg_lines.append(f"{prefix} {fname}")
                    
                    full_batch_msg = "\n".join(batch_msg_lines)
                    progress_text = f"📊 进度: {batch_size}/{total_files} ({int(batch_size/total_files*100)}%)\n\n{full_batch_msg}"
                    
                    if send_messages:
                        reply_thread_pool.submit(send_reply_delete, message, progress_text)
                    
                    # 清空批次缓存
                    message_batch = []
                
                # 速率控制
                time.sleep(1.0 / get_int_env("ENV_FILE_PER_SECOND", 5))
                
            except Exception as e:
                # 捕获单个文件处理中的严重错误
                logger.error(f"处理文件异常 {file_path}: {e}")
                results.append({"success": False, "file_name": file_path, "error": str(e)})
                
                dir_path, fname = os.path.split(file_path)
                message_batch.append({
                    'status': '❌', 
                    'dir': dir_path, 
                    'file': f"{fname} (系统异常)"
                })
                batch_size += 1

        # ---------------- 6. 发送剩余消息 ----------------
        if message_batch and send_messages:
            tree_messages = defaultdict(lambda: {'✅': [], '❌': [], '🔄': []})
            for entry in message_batch:
                tree_messages[entry['dir']][entry['status']].append(entry['file'])
            
            batch_msg_lines = []
            for d_path, status_files in tree_messages.items():
                for stat, f_list in status_files.items():
                    if f_list:
                        batch_msg_lines.append(f"--- {stat} {d_path}")
                        for idx, fname in enumerate(f_list):
                            prefix = '      └──' if idx == len(f_list)-1 else '      ├──'
                            batch_msg_lines.append(f"{prefix} {fname}")
            
            full_batch_msg = "\n".join(batch_msg_lines)
            reply_thread_pool.submit(send_reply_delete, message, f"📊 进度: {batch_size}/{total_files} (100%)\n\n{full_batch_msg}")

        # ---------------- 7. 最终统计报告 ----------------
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        
        success_count = sum(1 for r in results if r['success'])
        fail_count = len(results) - success_count
        
        # 格式化体积
        total_size_gb = total_size / (1024 ** 3)
        avg_size = total_size / success_count if success_count > 0 else 0
        avg_size_gb = avg_size / (1024 ** 3)
        
        # 构造汇总消息
        summary = (
            f"✅ 秒传任务完成！\n"
            f"📁 文件总数: {total_files}\n"
            f"✅ 成功转存: {success_count}\n"
            f"🔄 重复跳过: {skip_count}\n"
            f"❌ 转存失败: {fail_count}\n"
            f"📦 总计体积: {total_size_gb:.2f} GB\n"
            f"📊 平均大小: {avg_size_gb:.2f} GB\n"
            f"⏱️ 耗时统计: {elapsed_time} 秒"
        )
        
        # 构造失败详情
        error_details = ""
        if fail_count > 0:
            failed_list = [f"• {r['file_name']} ({r.get('error','未知')})" for r in results if not r['success']]
            # 最多显示15条错误，避免消息过长
            display_fails = failed_list[:15]
            error_details = "\n\n❌ 失败详情 (前15条):\n" + "\n".join(display_fails)
            if len(failed_list) > 15:
                error_details += f"\n... 以及其他 {len(failed_list)-15} 个错误"

        final_msg = summary + error_details
        
        logger.info(f"任务结束: {summary.replace(chr(10), ' | ')}") # chr(10) is \n
        
        if send_messages:
            reply_thread_pool.submit(send_reply, message, final_msg)
        
        # 如果失败太多，返回False
        if fail_count == total_files:
            return False
            
    except Exception as e:
        logger.error(f"处理秒传链接全局异常: {str(e)}")
        if send_messages:
            reply_thread_pool.submit(send_reply, message, f"处理异常: {str(e)}")
        status = False
    
    return status

def extract_123_links_from_full_text(message_str):
    """
    提取符合条件的123系列秒传链接
    特征：以123FSLinkV1/2、123FLCPV1/2开头，以文本形式\n（字符串"\\n"）或🔍为结束标志
          若未匹配到结束标志，则自动匹配到文本末尾
    :param message_str: 完整的原始字符串
    :return: 匹配到的链接列表（去重并保留原始顺序）
    """
    # 构建正则：
    # 1. 匹配指定开头 (123FSLinkV1/2 或 123FLCPV1/2)
    # 2. .*? 非贪婪匹配任意字符（包括实际换行，因启用DOTALL）
    # 3. (?=\\n|🔍|$) 正向预查：匹配到文本"\\n"、"🔍"或文本末尾时停止（不包含结束标志本身）
    # 注意：正则中用\\n表示文本中的"\n"（需转义反斜杠）
    link_pattern = re.compile(
        r'(123FSLinkV[12]|123FLCPV[12]).*?(?=\\n|\'}|\',|$)',
        re.DOTALL  # 让.匹配实际换行符（若文本中存在）
    )

    # 提取所有匹配的链接
    matched_links = [match.group(0) for match in link_pattern.finditer(message_str)]
    
    # 去重并保留原始顺序
    return list(dict.fromkeys(matched_links))

def extract_kuake_target_url(text):
    # 匹配标准夸克链接（http/https开头，提取核心share_id）
    link_pattern = r'https?://pan\.quark\.cn/s/([\w-]+)(?:[#?].*)?'
    # 匹配链接自带的pwd参数
    pwd_in_link_pattern = r'[?&]pwd=(\w+)'
    # 匹配文本中的提取码（兼容多种格式）
    pwd_text_pattern = r'提取码[：:]?\s*(\w+)'

    # 关键优化1：用集合记录已处理的share_id，避免重复添加同一链接
    processed_share_ids = set()
    link_info_list = []
    
    for match in re.finditer(link_pattern, text, re.IGNORECASE):
        share_id = match.group(1)
        if not share_id or share_id in processed_share_ids:  # 重复share_id直接跳过
            continue
        
        original_link = match.group(0)
        built_in_pwd = re.search(pwd_in_link_pattern, original_link).group(1) if re.search(pwd_in_link_pattern, original_link) else None
        
        link_info_list.append({"share_id": share_id.strip(), "built_in_pwd": built_in_pwd})
        processed_share_ids.add(share_id)  # 标记为已处理

    # 提取文本提取码（去重保序）
    passwords = list(dict.fromkeys(re.findall(pwd_text_pattern, text, re.IGNORECASE)))

    # 生成标准化链接
    processed_links = []
    for idx, info in enumerate(link_info_list):
        base_url = f"https://pan.quark.cn/s/{info['share_id']}"
        # 关键优化2：确保pwd匹配逻辑不错位（优先自带pwd，无则按索引取文本pwd）
        final_pwd = info['built_in_pwd']
        if not final_pwd and idx < len(passwords):
            final_pwd = passwords[idx]
        
        final_url = f"{base_url}?pwd={final_pwd}" if final_pwd else base_url
        processed_links.append(final_url)

    # 最终去重（保序）
    return list(dict.fromkeys(processed_links))

# ================= [开始] 新增 sync189 逻辑 =================
def clean_filename(name):
    """
    清洗文件名，去除非法字符
    """
    if not name:
        return "Unknown_Folder"
    
    # 1. 去除首尾空格
    name = name.strip()
    
    # 2. 替换非法字符 (Windows/网盘通用限制: \ / : * ? " < > |)
    # 将它们替换为下划线 _
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    
    # 3. 去除控制字符 (如换行符、制表符等)
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)
    
    # 4. 再次去除可能的首尾点号或空格
    name = name.strip('. ')
    
    return name

def find_child_folder_id(client, parent_id, folder_name):
    """
    在指定父目录下查找特定名称的子文件夹ID
    用于解决文件夹已存在导致的创建失败问题
    """
    try:
        # 使用 v2 接口列出文件
        url = "https://open-api.123pan.com/api/v2/file/list"
        
        # 遍历几页，防止文件夹内容太多导致找不到（通常前100个就能找到）
        last_file_id = 0
        
        # 最多往后翻3页(300个文件)，通常足够了
        for _ in range(3): 
            params = {
                "parentFileId": parent_id,
                "limit": 100,
                "lastFileId": last_file_id,
                "trashed": 0,
                "orderBy": "fileId",
                "orderDirection": "desc"
            }
            headers = {
                "Authorization": f"Bearer {client.token}",
                "Platform": "open_platform"
            }
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            res_json = resp.json()
            
            if res_json.get("code") != 0:
                # 如果接口报错，停止查找
                break
                
            file_list = res_json.get("data", {}).get("fileList", [])
            if not file_list:
                break
                
            for item in file_list:
                # type=1 是文件夹，且名称完全匹配
                if item.get("type") == 1 and item.get("filename") == folder_name:
                    return item.get("fileId")
            
            # 获取下一页的游标
            last_file_id = res_json.get("data", {}).get("lastFileId", 0)
            if last_file_id == 0:
                break
                
    except Exception as e:
        logger.error(f"查找文件夹异常: {e}")
        
    return None

# --- 全局锁，用于保护文件夹创建 ---
folder_lock = threading.Lock()

def get_progress_bar(current, total, length=15):
    """生成进度条字符串 [████░░░░]"""
    if total == 0:
        return "[]"
    percent = current / total
    filled_length = int(length * percent)
    bar = "█" * filled_length + "░" * (length - filled_length)
    return f"[{bar}] {int(percent * 100)}%"

def sync_file_worker(client123, file_info, root_123_pid, folder_cache):
    """
    [子线程工作函数] 处理单个文件的目录检查与秒传
    """   
    # 增加前置检查
    if check_ext_filter(file_info['file_name']):
        # 返回一个特殊的跳过状态，或者直接当做成功但不处理
        # 这里建议返回 fail 或新增 skipped 状态，这里简单返回 skipped
        return {"status": "skipped", "name": file_info['file_name'], "msg": "后缀过滤"}     
    try:
        # === 1. 目录结构处理 (必须加锁) ===
        relative_path = file_info.get('parent_path', '/').strip('/')
        current_123_parent_id = root_123_pid

        if relative_path:
            # 涉及读取/写入 folder_cache 和 API 创建，必须互斥
            with folder_lock:
                path_parts = relative_path.split('/')
                current_path_str = ""
                
                for raw_part in path_parts:
                    if not raw_part: continue
                    part = clean_filename(raw_part) # 需确保 clean_filename 已定义
                    current_path_str += f"/{part}"
                    
                    # 查缓存
                    if current_path_str in folder_cache:
                        current_123_parent_id = folder_cache[current_path_str]
                    else:
                        # 查云端 / 创建
                        new_folder_id = None
                        found_id = find_child_folder_id(client123, current_123_parent_id, part)
                        if found_id:
                            new_folder_id = found_id
                        else:
                            try:
                                resp = client123.fs_mkdir(part, parent_id=current_123_parent_id)
                                if resp.get("code") == 0:
                                    new_folder_id = resp["data"]["Info"]["FileId"]
                            except Exception:
                                pass # 线程中不宜过多打印创建失败日志
                        
                        if new_folder_id:
                            folder_cache[current_path_str] = new_folder_id
                            current_123_parent_id = new_folder_id
                        else:
                            # 失败回退到根目录
                            current_123_parent_id = root_123_pid

        # === 2. 执行秒传 (耗时操作，并行执行) ===
        rapid_resp = client123.upload_file_fast(
            file_name=file_info['file_name'],
            parent_id=current_123_parent_id,
            file_md5=robust_normalize_md5(file_info['md5']),
            file_size=int(file_info['file_size']),
            duplicate=1
        )

        is_success = False
        if rapid_resp.get("code") == 0:
            data = rapid_resp.get("data", {})
            if data and (data.get("Reuse") or data.get("reuse")):
                is_success = True
        
        if is_success:
            return {"status": "success", "file_id": file_info['file_id'], "name": file_info['file_name']}
        else:
            return {"status": "fail", "name": file_info['file_name']}

    except Exception as e:
        return {"status": "error", "msg": str(e), "name": file_info['file_name']}

from bot189 import Cloud189
from concurrent.futures import ThreadPoolExecutor
# [修改后 V5] 多线程并发 + 智能进度条反馈
def process_189_to_123_sync(message):
    user_id = message.from_user.id
    target_189_pid = os.getenv("ENV_189_UPLOAD_PID", "")
    root_123_pid = UPLOAD_TARGET_PID 

    if not target_189_pid:
        reply_thread_pool.submit(send_reply, message, "❌ 未配置 ENV_189_UPLOAD_PID")
        return

    # --- 1. 初始化天翼云 ---
    client189 = Cloud189()
    if not client189.check_cookie_valid():
        env_189_id = os.getenv("ENV_189_CLIENT_ID", "")
        env_189_secret = os.getenv("ENV_189_CLIENT_SECRET", "")
        if env_189_id and env_189_secret:
            logger.info("天翼云Cookie失效，尝试自动登录...")
            if not client189.login(env_189_id, env_189_secret):
                reply_thread_pool.submit(send_reply, message, "❌ 天翼云登录失败")
                return
        else:
            reply_thread_pool.submit(send_reply, message, "❌ 天翼云Cookie失效")
            return

    # 发送初始消息并保存对象，后续用于编辑
    status_msg = bot.reply_to(message, "♻️ 正在扫描天翼云盘源目录...")

    # --- 2. 获取源文件 ---
    try:
        files_189 = client189.get_folder_files_for_transfer(target_189_pid)
    except Exception as e:
        bot.edit_message_text(f"❌ 扫描出错: {str(e)}", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        return

    if not files_189:
        bot.edit_message_text("📂 天翼云源目录为空", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        return

    total_files = len(files_189)
    bot.edit_message_text(f"🔍 扫描到 {total_files} 个文件，准备启动 5 线程并发秒传...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)

    # --- 3. 初始化 123 客户端 & 准备工作 ---
    client123 = init_123_client()
    
    success_count = 0
    fail_count = 0
    processed_count = 0
    delete_list = []
    folder_cache = {} 
    
    # 进度控制
    last_update_time = 0
    start_time = time.time()

    # --- 4. 多线程执行同步 ---
    # max_workers=5 推荐值，过高可能导致123接口限流
    with ThreadPoolExecutor(max_workers=5) as executor:
        # 提交所有任务
        futures = [
            executor.submit(sync_file_worker, client123, f, root_123_pid, folder_cache) 
            for f in files_189
        ]
        
        # 处理结果 (as_completed 会在任务完成时立即 yield)
        for future in concurrent.futures.as_completed(futures):
            processed_count += 1
            res = future.result()
            
            if res['status'] == 'success':
                success_count += 1
                delete_list.append(res['file_id'])
                logger.info(f"✅ 秒传成功: {res['name']}")
            else:
                fail_count += 1
                logger.warning(f"❌ 秒传失败: {res['name']} ({res.get('msg', 'unknown')})")

            # --- 智能进度反馈 (每2秒更新一次消息) ---
            current_time = time.time()
            if current_time - last_update_time > 2 or processed_count == total_files:
                last_update_time = current_time
                
                # 计算速度和剩余时间
                elapsed = current_time - start_time
                speed = processed_count / elapsed if elapsed > 0 else 0
                eta = (total_files - processed_count) / speed if speed > 0 else 0
                
                # 生成进度条
                progress_bar = get_progress_bar(processed_count, total_files)
                
                msg_text = (
                    f"🚀 **同步进行中...**\n\n"
                    f"{progress_bar}\n"
                    f"🔢 进度: {processed_count}/{total_files}\n"
                    f"✅ 成功: {success_count}  ❌ 失败: {fail_count}\n"
                    f"⚡ 速度: {speed:.1f} 文件/秒\n"
                    f"⏳ 剩余: {int(eta)} 秒"
                )
                
                try:
                    bot.edit_message_text(msg_text, chat_id=status_msg.chat.id, message_id=status_msg.message_id, parse_mode='Markdown')
                except Exception:
                    pass # 忽略编辑消息可能出现的网络错误

    # --- 5. 清理天翼云源文件 ---
    deleted_files_count = 0
    cleaned_folders_count = 0
    
    if delete_list:
        bot.edit_message_text(f"🗑️ 秒传完成，正在删除 {len(delete_list)} 个源文件...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        
        # 批量删除（依然单线程分批处理，删除操作通常很快且并发容易触发风控）
        batch_size = 50
        for i in range(0, len(delete_list), batch_size):
            batch_ids = delete_list[i:i + batch_size]
            task_infos = [{"fileId": fid, "fileName": "del", "isFolder": 0} for fid in batch_ids]
            try:
                res = client189.delete_files(task_infos)
                if res.get("success"):
                    deleted_files_count += len(batch_ids)
            except Exception as e:
                logger.error(f"删除文件异常: {e}")
            time.sleep(1)
        
        # 清理空文件夹
        bot.edit_message_text("🧹 正在清理天翼云残留的空文件夹...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        try:
            cleaned_folders_count = client189.delete_empty_folders(target_189_pid)
        except Exception as e:
            logger.error(f"清理空文件夹失败: {e}")

    # --- 6. 最终战报 ---
    total_time = int(time.time() - start_time)
    result_msg = (
        f"🏁 **189⚡123 同步任务结束**\n\n"
        f"⏱️ 耗时: {total_time} 秒\n"
        f"📂 总文件: {total_files}\n"
        f"✅ 秒传成功: {success_count}\n"
        f"❌ 秒传失败: {fail_count}\n"
        f"🗑️ 删除源文件: {deleted_files_count}\n"
        f"🧹 清理空目录: {cleaned_folders_count}"
    )
    
    # 删除之前的进度消息，发送最终战报
    try:
        bot.delete_message(chat_id=status_msg.chat.id, message_id=status_msg.message_id)
    except:
        pass
    reply_thread_pool.submit(send_reply, message, result_msg)

# [新增] 注册 /sync189 命令
@bot.message_handler(commands=['sync189'])
def handle_sync_189_command(message):
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "🚫 您没有权限执行此操作")
        return
    
    reply_thread_pool.submit(send_reply, message, "⏳ 收到同步指令，正在后台启动处理进程...")
    
    # 在新线程中运行，防止阻塞Bot主进程
    threading.Thread(target=process_189_to_123_sync, args=(message,)).start()

# ================= [结束] 新增 sync189 逻辑 =================

from quark_export_share import export_share_info
from share import TMDBHelper
tmdb = TMDBHelper()
# 创建锁对象确保文件依次转存
link_process_lock = threading.Lock()
@bot.message_handler(content_types=['text', 'photo'])
def handle_general_message(message):
    logger.info("进入handle_general_message")
    user_id = message.from_user.id
    if user_id != TG_ADMIN_USER_ID:
        reply_thread_pool.submit(send_reply, message, "您没有权限使用此机器人。")
        return
    
    # [新增] 关键修改：忽略以 '-' 开头的 Userbot 命令
    # 防止 Bot 试图解析 '-s123' 等命令失败后回复报错，且因 Userbot 删除了消息导致死循环
    if message.content_type == 'text' and message.text and message.text.startswith('-'):
        logger.info(f"检测到 Userbot 命令 '{message.text}'，Bot 主动跳过")
        return
    
    with link_process_lock:
        text = f"{message}"
        client = init_123_client()             
        # 执行匹配
        full_links = extract_123_links_from_full_text(text)
        if full_links:
            for link in full_links:
                parse_share_link(message, link)
            user_state_manager.clear_state(user_id)
            return
        # 调用函数并获取返回值
        result = add_magnet_links(client,text,get_int_env("ENV_123_MAGNET_UPLOAD_PID", 0),message)

        # 根据返回值状态执行不同的print
        if result['status'] == 'success':
            success_count = 0
            fail_count = 0
            fail_messages = []
            
            # 检查每个链接的添加结果
            for item in result['data']:
                link = item['link']
                response = item['response']
                if isinstance(response, dict) and response.get('code') == 0:
                    success_count += 1
                else:
                    fail_count += 1
                    # 截取链接的前40个字符作为标识
                    link_identifier = link
                    msg = f"\n{link_identifier}: {response.get('message', '未知错误')}" if isinstance(response, dict) else f"{link_identifier}: {str(response)}"
                    fail_messages.append(msg)
            
            # 打印结果
            logger.info(f"123磁力链接添加结果: 成功{success_count}个, 失败{fail_count}个")
            if fail_count > 0:
                logger.error(f"失败详情:{', '.join(fail_messages)}")
                reply_thread_pool.submit(send_reply, message, f"123磁力链接添加部分失败: 成功{success_count}个, 失败{fail_count}个\n失败详情: {', '.join(fail_messages)}")
            else:
                reply_thread_pool.submit(send_reply, message, f"123磁力链接添加成功: 共添加了{success_count}个链接")
            user_state_manager.clear_state(user_id)
            return
        else:
            if result['message'] == '未找到磁力链接':
                #logger.info("未找到任何磁力链接")
                None
            else:
                logger.error(f"123磁力链接添加失败: {result['message']}")
                reply_thread_pool.submit(send_reply_delete, message, f"123磁力链接添加失败: {result['message']}")
                user_state_manager.clear_state(user_id)
                return
        if "提取码" in text and "www.123" in text:
            reply_thread_pool.submit(send_reply, message, f"仅支持形如 https://www.123pan.com/s/abcde-fghi?pwd=ABCD 的提取码格式")
            return
        target_urls = extract_target_url(text)
        if target_urls:
            reply_thread_pool.submit(send_reply_delete, message, f"发现{len(target_urls)}个123分享链接，开始转存...")
            success_count = 0
            fail_count = 0
            for url in target_urls:
                try:
                    result = transfer_shared_link_optimize(client, url, UPLOAD_LINK_TARGET_PID)
                    if result:
                        success_count += 1
                        logger.info(f"转存成功: {url}")
                    else:
                        fail_count += 1
                        logger.error(f"转存失败: {url}")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"转存异常: {url}, 错误: {str(e)}")
                    
            #time.sleep(3)
            reply_thread_pool.submit(send_reply, message, f"转存完成：成功{success_count}个，失败{fail_count}个")
            user_state_manager.clear_state(user_id)
            return
        
        target_urls = extract_kuake_target_url(text)
        if target_urls:
            if not os.getenv("ENV_KUAKE_COOKIE", ""):
                logger.error(f"请填写夸克COOKIE")
                reply_thread_pool.submit(send_reply, message, f"请填写夸克COOKIE")
                return
            reply_thread_pool.submit(send_reply, message, f"发现{len(target_urls)}个夸克分享链接，开始尝试秒传到123...")
            success_count = 0   
            fail_count = 0
            for url in target_urls:
                try:
                    json_data = export_share_info(url,os.getenv("ENV_KUAKE_COOKIE", ""))
                    if json_data:
                        save_json_file_quark(message,json_data)
                        #parse_share_link(message, kuake_link, get_int_env("ENV_123_KUAKE_UPLOAD_PID", 0))                
                    else:
                        logger.error(f"夸克分享转存123出错")
                        reply_thread_pool.submit(send_reply, message, f"夸克分享转存123出错")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"转存异常: {url}, 错误: {str(e)}")
            #time.sleep(3)
            #reply_thread_pool.submit(send_reply, message, f"转存完成：成功{success_count}个，失败{fail_count}个")
            user_state_manager.clear_state(user_id)
            return

        # ... 天翼云盘部分 ...       
        from bot189 import save_189_link    
        from bot189 import extract_target_url as extract_target_url_189
        from bot189 import save_189_link, get_share_file_snapshot
        
        target_urls = extract_target_url_189(text)
        if target_urls:
            reply_thread_pool.submit(send_reply_delete, message, f"发现{len(target_urls)}个天翼云盘分享链接，正在处理...")
            
            success_count = 0
            fail_count = 0
            
            client123 = init_123_client()
            
            # 1. 123云盘目标基础ID (秒传位置)
            pid_for_123 = os.getenv("ENV_189GO123_UPLOAD_PID", "")
            if not pid_for_123:
                pid_for_123 = os.getenv("ENV_123_UPLOAD_PID", "0")
            
            # 2. 天翼云目标ID (兜底转存)
            pid_for_189 = os.getenv("ENV_189_LINK_UPLOAD_PID", "")
            if not pid_for_189:
                pid_for_189 = os.getenv("ENV_189_UPLOAD_PID", "-11")

            logger.info(f"189配置 | 123基础ID: {pid_for_123} | 189兜底ID: {pid_for_189}")

            for url in target_urls:
                try:
                    logger.info(f"正在解析天翼云链接元数据: {url}")
                    # 获取文件快照 + 分享标题(作为根文件夹名)
                    files_in_share, root_share_name = get_share_file_snapshot(client189, url)
                    
                    all_rapid_success = False
                    
                    if files_in_share:
                        total_f = len(files_in_share)
                        success_f = 0
                        logger.info(f"解析成功，共 {total_f} 个文件，准备秒传...")
                        
                        # [关键] 文件夹ID全局缓存 (避免同一层级重复请求API)
                        # Key: "父ID_文件夹名", Value: "文件夹ID"
                        # 放在循环外，确保同一个分享链接内缓存共享
                        folder_cache = {} 
                        
                        for i, f_info in enumerate(files_in_share):
                            try:
                                # === [核心逻辑] 构建完整目录链 ===
                                raw_path = f_info.get('path', '').strip('/')
                                path_parts = raw_path.split('/')
                                
                                # 2. 提取文件名: "007.mp4"
                                file_name = path_parts.pop() 
                                
                                # 3. 构建目录列表: ["我的资源", "动作片", "007系列"]
                                # 将 "分享标题" 作为第一层，剩下的 path_parts 作为后续层级
                                dir_chain = []
                                if root_share_name:
                                    dir_chain.append(root_share_name)
                                dir_chain.extend([p for p in path_parts if p]) # 追加剩余路径
                                
                                # 4. 逐级递归创建/查找目录
                                current_pid = pid_for_123 # 从配置的根目录开始
                                
                                for folder_name in dir_chain:
                                    # 生成缓存Key (确保父ID和文件夹名唯一确定一个子文件夹)
                                    cache_key = f"{current_pid}_{folder_name}"
                                    
                                    # A. 查本地缓存 (速度最快，支持嵌套的关键)
                                    if cache_key in folder_cache:
                                        current_pid = folder_cache[cache_key]
                                        continue
                                    
                                    # B. 查云端 / 创建
                                    found_id = find_child_folder_id(client123, current_pid, folder_name)
                                    if found_id:
                                        # 存在 -> 记录缓存，进入下一级
                                        folder_cache[cache_key] = found_id
                                        current_pid = found_id
                                    else:
                                        # 不存在 -> 创建
                                        try:
                                            resp = client123.fs_mkdir(folder_name, parent_id=current_pid)
                                            if resp.get("code") == 0:
                                                new_id = resp["data"]["Info"]["FileId"]
                                                folder_cache[cache_key] = new_id
                                                current_pid = new_id
                                                logger.info(f"📁 创建目录: {folder_name} (ID: {new_id})")
                                            else:
                                                logger.warning(f"⚠️ 创建目录失败: {folder_name} - {resp.get('message')}")
                                        except Exception:
                                            pass

                                # === 5. 执行秒传 (到最后一级目录) ===
                                resp = client123.upload_file_fast(
                                    file_name=file_name,
                                    parent_id=current_pid, 
                                    file_md5=f_info['md5'],
                                    file_size=f_info['size'],
                                    duplicate=1
                                )
                                
                                if resp.get("code") == 0 and \
                                   (resp.get("data", {}).get("Reuse") or resp.get("data", {}).get("reuse")):
                                    success_f += 1
                                    
                            except Exception as e:
                                logger.error(f"❌ 单文件处理异常 {f_info.get('name')}: {e}")
                                pass 
                        
                        logger.info(f"123直连秒传结果: {success_f}/{total_f}")
                        
                        if success_f == total_f and total_f > 0:
                            all_rapid_success = True
                            success_count += 1
                            reply_thread_pool.submit(send_reply, message, f"✅ 123云盘极速秒传成功！\n📁 目录: {root_share_name}\n链接: {url}\n✨ 完美保留多层级目录结构")
                            continue 
                    
                    # 2. 秒传失败，走兜底转存 (保存到 189)
                    if not all_rapid_success:
                        logger.info("123秒传未完全覆盖，执行转存到天翼云盘...")
                        if files_in_share:
                            reply_thread_pool.submit(send_reply_delete, message, f"⚠️ 123云盘无此资源，正在转存到天翼云盘 (占用空间)...")
                        
                        result = save_189_link(client189, url, pid_for_189)
                        
                        if result:
                            success_count += 1
                            logger.info(f"天翼云转存成功: {url}")
                            reply_thread_pool.submit(send_reply, message, f"✅ 已转存到天翼云盘 (123秒传未完全覆盖)\n链接: {url}\n请稍后使用 /sync189 进行同步。")
                        else:
                            fail_count += 1
                            logger.error(f"天翼云转存失败: {url}")
                            reply_thread_pool.submit(send_reply, message, f"❌ 转存失败: {url}")

                except Exception as e:
                    fail_count += 1
                    logger.error(f"处理异常: {url}, 错误: {str(e)}")
            
            user_state_manager.clear_state(user_id)
            return

        # ... 115部分 ...
        from bot115 import extract_target_url as  extract_target_url_115
        from bot115 import transfer_shared_link as  transfer_shared_link_115
        from bot115 import init_115_client

        target_urls = extract_target_url_115(text)
        if target_urls:
            reply_thread_pool.submit(send_reply_delete, message, f"发现{len(target_urls)}个115分享链接，开始转存...")
            client = init_115_client()
            
            success_count = 0
            fail_count = 0
            skipped_count = 0  # 初始化计数器
            
            for url in target_urls:
                try:
                    if not url: continue
                    
                    # 确定 PID
                    target_pid = os.getenv("ENV_115_LINK_UPLOAD_PID", "0")
                    if url.startswith("ed2k://") or url.startswith("magnet:?"):
                        target_pid = os.getenv("ENV_115_OFFLINE_PID", target_pid)

                    # 执行转存
                    result = transfer_shared_link_115(client, url, target_pid)
                    
                    # 1. 判断是否成功 (利用 __bool__)
                    if result:
                        success_count += 1
                        logger.info(f"✅ 115网盘转存成功: {url}")
                        
                        # 2. 判断是否跳过 (利用新属性 skipped)
                        # getattr 是为了防止 bot115 未更新导致报错的防御性写法
                        if getattr(result, 'skipped', False):
                            skipped_count += 1
                    else:
                        fail_count += 1
                        logger.error(f"115网盘转存失败: {url}")
                        
                except Exception as e:
                    fail_count += 1
                    logger.error(f"115网盘转存异常: {url}, 错误: {str(e)}")
            
            # 构建直观的回复
            reply_msg = f"✅ 115网盘转存完成：成功{success_count}个"
            
            # 如果有跳过的任务，进行特别标注
            if skipped_count > 0:
                reply_msg += f" (含{skipped_count}个任务已存在)"
            
            reply_msg += f"，失败{fail_count}个"
            
            reply_thread_pool.submit(send_reply, message, reply_msg)
            user_state_manager.clear_state(user_id)
            return


    state, data = user_state_manager.get_state(user_id)
    if state == "SELECTING_FILE":
        try:
            raw_text = message.text.strip()
            text = raw_text.replace('　', ' ').strip()
            full_width = '０１２３４５６７８９'
            half_width = '0123456789'
            trans_table = str.maketrans(full_width, half_width)
            text = text.translate(trans_table)
            try:
                # 支持空格分隔的多个数字，如 "1 2 3 5"
                selections = [int(num) - 1 for num in text.split()]
                if not selections:
                    raise ValueError("请至少输入一个有效的序号")
                # 检查是否有重复的序号
                if len(selections) != len(set(selections)):
                    raise ValueError("序号不能重复")
            except ValueError as e:
                if "invalid literal" in str(e):
                    raise ValueError("请输入有效的数字序号（例如：1 2 3 4），不要包含字母或符号")
                else:
                    raise e
                
            # [修改] 增强的状态数据解析，支持 mode
            try:
                loaded_data = json.loads(data)
                # 判断是旧列表格式还是新字典格式
                if isinstance(loaded_data, dict) and "results" in loaded_data:
                    results = loaded_data["results"]
                    mode = loaded_data.get("mode", "link")
                elif isinstance(loaded_data, list):
                    results = loaded_data
                    mode = "link" # 默认为链接模式
                else:
                    results = []
                    mode = "link"
            except Exception:
                reply_thread_pool.submit(send_reply, message, "数据解析错误，请重新搜索")
                return

            if not results:
                reply_thread_pool.submit(send_reply, message, "搜索结果已失效，请重新搜索")
                user_state_manager.clear_state(user_id)
                return
            
            # 验证所有选择是否在有效范围内
            for idx in selections:
                if not (0 <= idx < len(results)):
                    raise ValueError(f"序号 {idx+1} 超出范围，请重新输入")
            
            # 初始化客户端（只需初始化一次）
            client = init_123_client()
            
            # 遍历所有选择的文件夹
            for selection in selections:
                selected_item = results[selection]
                file_id = selected_item['id']
                folder_name = selected_item['name']
                logger.info(f"选中文件夹ID: {file_id}, 名称: {folder_name}, 模式: {mode}")
                
                # 只为第一个文件夹发送处理消息
                if selection == selections[0]:
                    op_text = "生成JSON文件" if mode == "json" else "创建分享链接"
                    reply_thread_pool.submit(send_reply, message, f"正在为 {len(selections)} 个文件夹{op_text}...")

                # ==========================
                # 分支 1: 分享链接模式 (link)
                # ==========================
                if mode == "link":
                    if get_int_env("ENV_MAKE_NEW_LINK", 1):
                        existing_share = get_existing_shares(client, folder_name)
                    else:
                        existing_share = None
                        
                    if existing_share:
                        # 尝试获取TMDB元数据
                        file_name=get_first_video_file(client, file_id)
                        metadata = tmdb.get_metadata_optimize(folder_name, file_name)
                        share_data = {
                            "share_url": f"{existing_share['url']}{'?pwd=' + existing_share['password'] if existing_share['password'] else ''}",
                            "folder_name": folder_name,
                            "file_id": file_id  # 选中的文件夹ID，用于后续查询文件
                        }

                        if not metadata:
                            logger.warning(f"未获取到TMDB元数据: {folder_name}/{file_name}")
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, f"未获取到TMDB元数据，不予分享，请规范文件夹名: {folder_name}/{file_name}")
                            # 注意：如果是多选，这里 continue 跳过当前，不清除状态
                            continue 

                        # 仅当metadata存在且title在folder_name中时才执行
                        if metadata:
                            # 使用封装函数构建消息
                            share_message, share_message2, poster_url, files = build_share_message(metadata, client, file_id, folder_name, file_name, existing_share)

                            # 发送图片和消息
                            try:
                                bot.send_photo(message.chat.id, poster_url, caption=share_message, parse_mode='HTML')
                                if TOKENSHARE:
                                    botshare.send_photo(TARGET_CHAT_ID_SHARE, poster_url, caption=share_message, parse_mode='HTML')
                            except Exception as e:
                                logger.error(f"发送图片失败: {str(e)}")
                                reply_thread_pool.submit(send_message_with_id, message.chat.id, share_message)
                        else:
                            # 无元数据的备用显示
                            files = get_directory_files(client, file_id, folder_name)
                            share_message = f"✅ 已存在分享链接：\n{folder_name}\n"
                            share_message += f"链接：{existing_share['url']}{'?pwd=' + existing_share['password'] if existing_share['password'] else ''}\n"
                            if existing_share['password']:
                                share_message += f"提取码：{existing_share['password']}\n"
                            share_message += f"过期时间：{existing_share['expiry']}"
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, share_message)

                        # [移除] 这里移除了 AUTO_MAKE_JSON 的逻辑，因为现在由 json 模式接管

                        # 发帖询问逻辑
                        if os.getenv("ENV_123PANFX_COOKIE","") and len(selections)==1:
                            user_state_manager.set_state(user_id, "ASK_POST", json.dumps(share_data))
                            ask_msg = "是否需要将该内容发布到论坛？\n1. 放弃发帖\n2. 发送到电影板块\n3. 发送到电视剧板块\n4. 发送到动漫板块"
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, ask_msg)
                            return # 发帖需要等待下一步，直接返回，不清除状态

                    else:
                        # 创建新分享链接
                        file_name = get_first_video_file(client,file_id)
                        metadata = tmdb.get_metadata_optimize(folder_name, file_name)
                        porn_result = None

                        if not metadata:
                            logger.warning(f"未获取到TMDB元数据: {folder_name}/{file_name}")
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, f"未获取到TMDB元数据，不予分享，请规范文件夹名: {folder_name}/{file_name}")
                            continue

                        # 检查内容是否涉及色情
                        if os.getenv("AI_API_KEY", ""):
                            porn_result = check_porn_content(folder_name+"/"+file_name+"："+metadata.get('plot'))
                        else:
                            porn_result = check_porn_content(
                                            content=folder_name+"/"+file_name+"："+metadata.get('plot'),
                                            api_url="https://api.edgefn.net",
                                            api_key="sk-Mk6CjIVzoCcg2VnK8c5a85Ef49Ca43F1Ba9b9a13E98f30A9",
                                            model_name="DeepSeek-R1-0528-Qwen3-8B",
                                            max_tokens=15000
                                        )
                        
                        # 根据检测结果决定后续操作
                        if porn_result and porn_result['is_pornographic']:
                            logger.warning(f"检测到色情内容，已拒绝分享: {folder_name}")
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, f"影视介绍中检测到涉及色情内容，拒绝分享，判断依据：{porn_result['reason']}")
                            continue
                        
                        # 非色情内容，继续创建分享链接
                        share_info = create_share_link(client, file_id)
                        share_data = {
                            "share_url": share_info["url"],
                            "folder_name": folder_name,
                            "file_id": file_id  # 选中的文件夹ID，用于后续查询文件
                        }

                        # 仅当metadata存在且title在folder_name中时才执行
                        if metadata:
                            # 使用封装函数构建消息
                            share_message, share_message2, poster_url, files = build_share_message(metadata, client, file_id, folder_name, file_name, share_info)

                            # 发送图片和消息
                            try:
                                bot.send_photo(message.chat.id, poster_url, caption=share_message, parse_mode='HTML')
                                if TOKENSHARE:
                                    botshare.send_photo(TARGET_CHAT_ID_SHARE, poster_url, caption=share_message, parse_mode='HTML')
                            except Exception as e:
                                logger.error(f"发送图片失败: {str(e)}")
                                reply_thread_pool.submit(send_message_with_id, message.chat.id, share_message)
                        else:
                            files = get_directory_files(client, file_id, folder_name)
                            # 使用原来的消息格式
                            share_message = f"✅ 分享链接已创建：\n{folder_name}\n"
                            share_message += f"链接：{share_info['url']}\n"
                            if share_info['password']:
                                share_message += f"提取码：{share_info['password']}\n"
                            share_message += f"过期时间：{share_info['expiry']}"
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, share_message)
                        
                        # [移除] 同样移除了 AUTO_MAKE_JSON 逻辑

                        if os.getenv("ENV_123PANFX_COOKIE","") and len(selections)==1:
                            user_state_manager.set_state(user_id, "ASK_POST", json.dumps(share_data))
                            ask_msg = "是否需要将该内容发布到论坛？\n1. 放弃发帖\n2. 发送到电影板块\n3. 发送到电视剧板块\n4. 发送到动漫板块"
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, ask_msg)
                            return

                # ==========================
                # 分支 2: JSON 文件模式 (json)
                # ==========================
                elif mode == "json":
                    try:
                        # 获取文件夹内文件列表
                        files = get_directory_files(client, file_id, folder_name)
                        if not files:
                            logger.warning(f"文件夹为空: {folder_name}")
                            reply_thread_pool.submit(send_message_with_id, message.chat.id, f"文件夹为空: {folder_name}")
                            continue

                        # 计算总文件数和总体积
                        total_files_count = len(files)
                        total_size = sum(file_info["size"] for file_info in files)
                        
                        # [修改] 创建符合规范的JSON结构
                        json_data = {
                            "usesBase62EtagsInExport": False,
                            "etagEncrypted": False,
                            "commonPath": f"{folder_name}/",
                            "totalFilesCount": total_files_count,
                            "totalSize": total_size,
                            "formattedTotalSize": get_formatted_size(total_size), # 使用新辅助函数
                            "files": [
                                {
                                    "path": file_info["path"],
                                    "etag": file_info["etag"],
                                    "size": file_info["size"]
                                }
                                for file_info in files
                            ]
                        }
                        
                        # 保存JSON文件
                        json_file_path = f"{folder_name}.json"
                        with open(json_file_path, 'w', encoding='utf-8') as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                        
                        # 计算显示体积
                        size_str = get_formatted_size(total_size)
                        
                        with open(json_file_path, 'rb') as f:
                            # 计算平均文件大小
                            avg_size = total_size / total_files_count if total_files_count > 0 else 0
                            avg_size_str = get_formatted_size(avg_size)
                            
                            # 发送文件
                            bot.send_document(
                                message.chat.id, 
                                f, 
                                caption=f"📁 {folder_name}\n📝文件数: {total_files_count}个\n📦总体积: {size_str}\n📊平均文件大小: {avg_size_str}"
                            )
                        
                        # 删除临时文件
                        os.remove(json_file_path)
                    
                    except Exception as e:
                        logger.error(f"生成或发送JSON文件失败: {str(e)}")
                        reply_thread_pool.submit(send_message_with_id, message.chat.id, f"生成文件列表失败，请重试")

            # 处理完成后，清除状态 (ASK_POST 状态已在上面 return，不会走到这里)
            user_state_manager.clear_state(user_id)

        except ValueError as e:
            reply_thread_pool.submit(send_reply, message, str(e))
        except Exception as e:
            reply_thread_pool.submit(send_reply, message, f"创建分享链接失败: 请检查文件夹是否为空，{str(e)}")
            logger.error(f"创建分享链接失败: {str(e)}")
    
    elif state == "ASK_POST":
        try:
            selection = message.text.strip()
            if selection not in ["1", "2", "3", "4"]:
                raise ValueError("请输入1、2、3或4选择操作")
            #global json
            # 解析保存的分享数据
            share_data = json.loads(data)
            share_url = share_data["share_url"]
            folder_name = share_data["folder_name"]
            file_id = share_data["file_id"]

            if selection == "1":
                # 放弃发帖
                reply_thread_pool.submit(send_reply, message, "已取消发帖")
                user_state_manager.clear_state(user_id)
            else:
                # 确定媒体类型（2=电影，3=电视剧）
                # 根据选择确定媒体类型：2->电影，3->动画，其他->电视剧
                if selection == "2":
                    media_type = "movie"  # 选择2：电影
                elif selection == "3":
                    media_type = "tv"  # 选择3：电视剧
                elif selection == "4":
                    media_type = "anime"  # 选择4：动漫
                else:
                    media_type = None  # 选择1：放弃（无需处理）

                # 获取第一个视频文件名称
                reply_thread_pool.submit(send_reply, message, "正在查找视频文件以确定影视的分辨率及音频等信息...")
                client = init_123_client()
                file_name = get_first_video_file(client, file_id)
                if not file_name:
                    reply_thread_pool.submit(send_reply, message, "未找到视频文件，无法发帖")
                    user_state_manager.clear_state(user_id)
                    return

                # 调用share.py中的post_to_forum发布
                from share import post_to_forum
                reply_thread_pool.submit(send_reply, message, "正在发布到论坛...")
                success, forum_url = post_to_forum(
                    share_url=share_url,
                    folder_name=folder_name,
                    file_name=file_name,
                    media_type=media_type
                )

                # 反馈结果
                if success:
                    reply_thread_pool.submit(send_reply, message, f"发帖成功！\n{folder_name}\n社区链接：{forum_url}\n123资源社区因您的分享而更美好❤️")
                else:
                    reply_thread_pool.submit(send_reply, message, f"发帖失败，{forum_url}, 请重试")
                user_state_manager.clear_state(user_id)

        except ValueError as e:
            reply_thread_pool.submit(send_reply, message, str(e))
        except Exception as e:
            reply_thread_pool.submit(send_reply, message, f"操作失败: {str(e)}")
            logger.error(f"处理发帖选择错误: {e}")
    else:
        reply_thread_pool.submit(send_reply, message, "未识别的命令")


#  启动人形监听线程 (升级：-s123回复支持TMDB富文本+海报缩略图)
# [修改] 启动人形监听线程 (升级：支持后缀过滤 + TMDB富文本 + 海报缩略图)
def start_userbot_listener():
    """
    启动 Pyrogram Userbot 监听人形命令 (修复版 V4：增加后缀过滤)
    """
    import traceback
    import time
    import asyncio
    import requests
    import re
    import os
    import json
    from share import get_quality 
    
    USERBOT_STATE_ID = -TG_ADMIN_USER_ID 

    # ==================== 内部类：TMDB分析工具 ====================
    class TVAnalyzer:
        def __init__(self):
            self.api_key = os.getenv("ENV_TMDB_API_KEY", "") or "93513c7928441ee2a23b6ed943aa1023"
            self.base_url = "https://api.themoviedb.org/3"
            self.language = "zh-CN"

        def fetch_tmdb_info_sync(self, keyword, is_tv=True):
            try:
                media_type = "tv" if is_tv else "movie"
                search_url = f"{self.base_url}/search/{media_type}?api_key={self.api_key}&query={keyword}&language={self.language}"
                resp = requests.get(search_url, timeout=10)
                if resp.status_code != 200: return None
                data = resp.json()
                if not data.get('results'): return None
                
                best_match = data['results'][0]
                tmdb_id = best_match['id']
                
                append_to = "credits,external_ids"
                if is_tv: append_to += ",seasons"
                
                detail_url = f"{self.base_url}/{media_type}/{tmdb_id}?api_key={self.api_key}&language={self.language}&append_to_response={append_to}"
                detail_resp = requests.get(detail_url, timeout=10)
                if detail_resp.status_code != 200: return None
                details = detail_resp.json()
                
                credits = details.get('credits', {})
                cast = [c.get('name', '') for c in credits.get('cast', [])[:5]]
                crew = [c.get('name') for c in credits.get('crew', []) if c.get('job') == 'Director']
                genres = [g.get('name') for g in details.get('genres', [])]
                countries = [c.get('name') for c in details.get('production_countries', [])]
                
                if is_tv and not crew:
                    crew = [c.get('name') for c in details.get('created_by', [])]

                date_str = details.get('release_date') or details.get('first_air_date') or '0000'
                year = date_str[:4] if len(date_str) >= 4 else '0000'

                result = {
                    'id': tmdb_id,
                    'title': details.get('title') or details.get('name'),
                    'overview': details.get('overview', '暂无简介'),
                    'year': year,
                    'vote_average': round(details.get('vote_average', 0.0), 1),
                    'poster_path': f"https://image.tmdb.org/t/p/original{details.get('poster_path')}" if details.get('poster_path') else None,
                    'backdrop_path': f"https://image.tmdb.org/t/p/original{details.get('backdrop_path')}" if details.get('backdrop_path') else None,
                    'media_type': '📺 电视剧' if is_tv else '🎬 电影',
                    'cast': ', '.join(cast),
                    'director': ', '.join(crew),
                    'genres': ', '.join(genres),
                    'countries': ', '.join(countries),
                    'seasons_count': details.get('number_of_seasons', 0),
                    'episodes_count': details.get('number_of_episodes', 0),
                    'seasons': details.get('seasons', [])
                }
                return result
            except Exception as e:
                logger.error(f"TMDB Fetch Error: {e}")
                return None

        def analyze_files(self, local_files, tmdb_info):
            if not tmdb_info or "📺" not in tmdb_info.get('media_type', ''): return ""
            local_seasons = {}
            for file_name in local_files:
                name_lower = file_name.lower()
                s_match = re.search(r's(\d+)', name_lower)
                e_match = re.search(r'e(\d+)', name_lower)
                if s_match and e_match:
                    s, e = int(s_match.group(1)), int(e_match.group(1))
                    local_seasons.setdefault(s, set()).add(e)
                else:
                    cn_s = re.search(r'第(\d+)季', name_lower)
                    cn_e = re.search(r'第(\d+)集', name_lower)
                    if cn_s and cn_e:
                        s, e = int(cn_s.group(1)), int(cn_e.group(1))
                        local_seasons.setdefault(s, set()).add(e)

            report = []
            tmdb_seasons = {s['season_number']: s['episode_count'] for s in tmdb_info.get('seasons', []) if s['season_number'] > 0}
            missing_seasons = sorted(set(tmdb_seasons.keys()) - set(local_seasons.keys()))
            if missing_seasons:
                report.append(f"❌ 缺失季度: S{', S'.join(map(str, missing_seasons))}")

            for s_num, total_eps in tmdb_seasons.items():
                if s_num in local_seasons:
                    local_eps = local_seasons[s_num]
                    if len(local_eps) < total_eps:
                        expected_eps = set(range(1, total_eps + 1))
                        missing_eps = sorted(expected_eps - local_eps)
                        if missing_eps:
                            formatted_missing = []
                            if len(missing_eps) > 0:
                                start = prev = missing_eps[0]
                                for ep in missing_eps[1:]:
                                    if ep == prev + 1: prev = ep
                                    else:
                                        formatted_missing.append(f"{start}-{prev}" if start != prev else f"{start}")
                                        start = prev = ep
                                formatted_missing.append(f"{start}-{prev}" if start != prev else f"{start}")
                            missing_str = ', '.join(formatted_missing)
                            if len(missing_str) > 20: missing_str = missing_str[:20] + "..."
                            report.append(f"⚠️ S{s_num:02d} 缺{len(missing_eps)}集 (E{missing_str})")

            if not report: return "✅ 剧集完整"
            return "\n".join(report)

    tv_analyzer = TVAnalyzer()
    # ==================== 内部类结束 ====================

    logger.info("⏳ [人形模块] 等待 15 秒后启动，避开 Bot 启动高峰...")
    time.sleep(15)
        
    try:
        try:
            from pyrogram import Client, filters, enums
        except ImportError:
            logger.error("❌ [人形模块] 缺少依赖，请 pip install pyrogram tgcrypto")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        session_file = "db/default_session.session"
        if not os.path.exists(session_file): return

        api_id = int(os.getenv("ENV_API_ID") or 0)
        api_hash = os.getenv("ENV_API_HASH")
        if not api_id or not api_hash: return

        app = Client("default_session", api_id=api_id, api_hash=api_hash, workdir="db") 

        # ---------------- s123 命令 ----------------
        @app.on_message(filters.me & filters.command("s123", prefixes="-"))
        async def userbot_s123_handler(client, message):
            try:
                if len(message.command) < 2:
                    await message.edit_text("❌ 请提供关键词,例如: -s123 电影名称")
                    return
                keyword = message.text.split(maxsplit=1)[1]
                await message.edit_text(f"🔍 正在搜索: {keyword} ...")
                p123 = init_123_client()
                results = await loop.run_in_executor(None, lambda: asyncio.run(search_123_files(p123, keyword)))
                if not results:
                    await message.edit_text(f"❌ 未找到关于 '{keyword}' 的文件夹")
                    return
                folder_msg = build_folder_message(results)
                
                # 记录消息ID，确保后续能删除
                state_data = {
                    "results": results, 
                    "mode": "json",
                    "msg_id": message.id,      # 搜索结果消息ID
                    "chat_id": message.chat.id # 聊天ID
                }
                user_state_manager.set_state(USERBOT_STATE_ID, "SELECTING_FILE", json.dumps(state_data))
                
                await message.edit_text(f"✅ 搜索完成\n{folder_msg}")
            except Exception as e:
                logger.error(f"Userbot -s123 error: {e}")
                await message.edit_text(f"❌ 搜索出错: {e}")

        # ---------------- 序号选择 (修复：消息回溯删除 + 文件过滤) ----------------
        @app.on_message(filters.me & filters.regex(r"^\d+(\s+\d+)*$"))
        async def userbot_selection_handler(client, message):
            raw_text = message.text or message.caption or ""
            if not raw_text: return

            text = message.text.strip()
            
            state, data = user_state_manager.get_state(USERBOT_STATE_ID)
            if state != "SELECTING_FILE":
                message.continue_propagation()
                return 

            # 1. 立即删除用户回复的数字
            try: await message.delete()
            except: pass
            
            # 2. 寻找要删除的列表消息
            list_msg = None
            if message.reply_to_message:
                list_msg = message.reply_to_message
            else:
                try:
                    loaded_data = json.loads(data)
                    saved_msg_id = loaded_data.get("msg_id")
                    saved_chat_id = loaded_data.get("chat_id")
                    
                    if saved_chat_id == message.chat.id and saved_msg_id:
                        list_msg = await client.get_messages(message.chat.id, saved_msg_id)
                except Exception as e:
                    logger.warning(f"回溯消息失败: {e}")

            try:
                selections = [int(num) - 1 for num in text.split()]
                try:
                    loaded_data = json.loads(data)
                    results = loaded_data["results"] if isinstance(loaded_data, dict) and "results" in loaded_data else loaded_data
                except: return

                if not results: return

                for idx in selections:
                    if not (0 <= idx < len(results)):
                        if list_msg: await list_msg.edit_text(f"❌ 序号 {idx+1} 超出范围，请重新搜索")
                        return

                # 3. 删除列表消息，发送新的进度消息
                if list_msg:
                    try: await list_msg.delete()
                    except: pass
                
                status_msg = await client.send_message(message.chat.id, f"⚙️ 正在获取元数据 (任务 {len(selections)} 个)...")
                
                p123 = init_123_client()

                for selection in selections:
                    selected_item = results[selection]
                    file_id = selected_item['id']
                    folder_name = selected_item['name']

                    try:
                        # 获取全部文件列表
                        files = await loop.run_in_executor(None, get_directory_files, p123, file_id, folder_name)
                        if not files: continue

                        # === [新增] 这里执行后缀过滤 ===
                        filtered_files = []
                        skipped_num = 0
                        for f in files:
                            # 调用全局定义的 check_ext_filter
                            if check_ext_filter(f.get("path", "")):
                                skipped_num += 1
                                continue
                            filtered_files.append(f)
                        
                        files = filtered_files
                        
                        if skipped_num > 0:
                            logger.info(f"Userbot生成JSON: 已过滤 {skipped_num} 个文件")
                            
                        if not files:
                            await client.send_message(message.chat.id, f"❌ 文件夹 {folder_name} 内所有文件均被过滤规则屏蔽")
                            continue
                        # ==============================

                        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.ts', '.rmvb', '.iso', '.wmv', '.m2ts', '.mpg', '.flv', '.rm'}
                        video_files = [f for f in files if os.path.splitext(f["path"])[1].lower() in video_exts]
                        
                        total_size = sum(f["size"] for f in files)
                        if total_size < 1024**3: size_str = f"{total_size / (1024**2):.2f} MB"
                        else: size_str = f"{total_size / (1024**3):.2f} GB"
                        
                        avg_size = total_size / len(video_files) if video_files else 0
                        if avg_size < 1024**3: avg_str = f"{avg_size / (1024**2):.2f} MB"
                        else: avg_str = f"{avg_size / (1024**3):.2f} GB"

                        file_info_text = f"🎬 视频数量: {len(video_files)} | 总大小: {size_str} | 平均大小：{avg_str}"
                        quality = get_quality(video_files[0]["path"]) if video_files else "未知"

                        clean_keyword = re.split(r'[ .\[\(]', folder_name.split('/')[0])[0]
                        is_tv = bool(video_files and any(re.search(r's\d+|e\d+|第\d+集', f['path'].lower()) for f in video_files[:5]))
                        tmdb_info = await loop.run_in_executor(None, tv_analyzer.fetch_tmdb_info_sync, clean_keyword, is_tv)

                        poster_path = None
                        caption = ""

                        if tmdb_info:
                            if tmdb_info.get('poster_path'):
                                try:
                                    poster_resp = await loop.run_in_executor(None, requests.get, tmdb_info['poster_path'])
                                    if poster_resp.status_code == 200:
                                        poster_path = f"thumb_{file_id}.jpg"
                                        with open(poster_path, 'wb') as f: f.write(poster_resp.content)
                                except: pass

                            content_type = tmdb_info.get('media_type', '🎬 电影')
                            metadata = {'plot': tmdb_info.get('overview', '')}
                            
                            caption = (
                                f"{content_type}｜{tmdb_info.get('title')} ({tmdb_info.get('year')})\n\n"
                                f"⭐️ 评分: {tmdb_info.get('vote_average')} ...\n"
                                f"🌍 地区: {tmdb_info.get('countries')}\n"
                                f"📽  类型: {tmdb_info.get('genres')}\n"
                                f"🎬 导演: {tmdb_info.get('director')}...\n"
                                f"👥 主演: {tmdb_info.get('cast')}...\n"
                                f"\n📖 简介: <blockquote expandable=\"\">{metadata.get('plot')[:100]}...</blockquote>\n\n"
                                f"{file_info_text}\n"
                                f"🏷 质量: {quality}\n\n"
                                f"🙋 来自🤖自动生成的JSON"
                            )
                        else:
                            caption = f"📂 <b>{folder_name}</b>\n\n{file_info_text}\n🏷 视频质量: {quality}\n🙋 来自🤖自动生成的JSON"

                        json_data = {
                            "usesBase62EtagsInExport": False,
                            "etagEncrypted": False,
                            "commonPath": f"{folder_name}/",
                            "totalFilesCount": len(files),
                            "totalSize": total_size,
                            "formattedTotalSize": size_str, 
                            "files": [{"path": f["path"], "etag": f["etag"], "size": f["size"]} for f in files]
                        }

                        json_file_path = f"{folder_name}.json"
                        
                        with link_process_lock:
                            with open(json_file_path, 'w', encoding='utf-8') as f:
                                json.dump(json_data, f, ensure_ascii=False, indent=2)
                        
                        await client.send_document(
                            chat_id=message.chat.id,
                            document=json_file_path,
                            caption=caption,
                            thumb=poster_path,
                            parse_mode=enums.ParseMode.HTML
                        )
                        
                        if os.path.exists(json_file_path): os.remove(json_file_path)
                        if poster_path and os.path.exists(poster_path): os.remove(poster_path)

                    except Exception as e:
                        logger.error(f"处理失败: {e}")
                        await client.send_message(message.chat.id, f"❌ 处理失败 {folder_name}: {e}")

                # 4. 任务完成后删除进度消息
                try: await status_msg.delete()
                except: pass
                
                user_state_manager.clear_state(USERBOT_STATE_ID)

            except Exception as e:
                logger.error(f"Userbot 选择处理出错: {e}")

        # ---------------- mc 命令 (修复：媒体组深层扫描 + 纯文本JSON + 后缀过滤) ----------------
        @app.on_message(filters.me & filters.command("mc", prefixes="-"))
        async def userbot_mc_handler(client, message):
            target_msg = message.reply_to_message or message
            try:
                if message.chat.id: await client.get_chat(message.chat.id)
            except: pass

            status_msg = await message.edit_text("♻️ 正在解析...")
            
            def ub_log_callback(text):
                logger.info(f"[Userbot Log] {text}")
                if "📊" in text or "开始" in text:
                    async def safe_edit():
                        try:
                            import time
                            ts = time.strftime("%H:%M:%S")
                            display_text = text.split('\n')[0] 
                            await status_msg.edit_text(f"♻️ 执行中 ({ts})...\n{display_text}")
                        except Exception: pass
                    asyncio.run_coroutine_threadsafe(safe_edit(), loop)

            try:
                transfer_result = None
                json_data = None
                doc = None

                def is_json_doc(msg_obj):
                    if not msg_obj or not msg_obj.document: return False
                    fname = (msg_obj.document.file_name or "").lower()
                    mime = (msg_obj.document.mime_type or "").lower()
                    if fname.endswith(".json") or "json" in mime: return True
                    return False

                if is_json_doc(target_msg):
                    doc = target_msg.document
                
                if not doc and target_msg.media_group_id:
                    try:
                        media_group = await client.get_media_group(target_msg.chat.id, target_msg.id)
                        if media_group:
                            for m in media_group:
                                if is_json_doc(m):
                                    doc = m.document
                                    break
                    except Exception as e:
                        logger.warning(f"获取媒体组失败: {e}")

                if doc:
                    await status_msg.edit_text(f"📥 正在下载: {doc.file_name}...")
                    file_path = await client.download_media(doc)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    os.remove(file_path)
                
                elif target_msg.text or target_msg.caption:
                    text_content = target_msg.text or target_msg.caption
                    stripped = text_content.strip()
                    if (stripped.startswith('{') and stripped.endswith('}')) or \
                       (stripped.startswith('[') and stripped.endswith(']')):
                        try:
                            json_data = json.loads(stripped)
                            await status_msg.edit_text("📥 识别到文本JSON，正在解析...")
                        except: pass

                if json_data:
                    await status_msg.edit_text("⚙️ 正在转存 (请稍候)...")
                    with link_process_lock:
                        # 核心函数 core_process_json_data 内部已经集成了过滤逻辑
                        transfer_result = await loop.run_in_executor(None, core_process_json_data, json_data, ub_log_callback)
                    
                    if transfer_result:
                        await status_msg.edit_text("🎨 正在生成战报...")
                        
                        folder_name = transfer_result.get('target_dir_name', '未知目录')
                        success_count = transfer_result.get('success_count', 0)
                        fail_count = transfer_result.get('fail_count', 0)
                        file_list = transfer_result.get('file_list', [])
                        total_size_str = transfer_result.get('total_size_str', '0B')
                        filtered_count = transfer_result.get('filtered_count', 0) # 获取过滤数
                        
                        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.ts', '.rmvb', '.iso', '.wmv', '.m2ts', '.mpg', '.flv', '.rm'}
                        video_files = [f for f in file_list if os.path.splitext(f)[1].lower() in video_exts]
                        is_tv = bool(video_files and any(re.search(r's\d+|e\d+|第\d+集', f.lower()) for f in video_files[:5]))
                        quality = get_quality(video_files[0]) if video_files else "未知"
                        
                        clean_keyword = re.split(r'[ .\[\(]', folder_name.split('/')[0])[0]
                        tmdb_info = await loop.run_in_executor(None, tv_analyzer.fetch_tmdb_info_sync, clean_keyword, is_tv)
                        
                        poster_path = None
                        caption = ""
                        
                        filter_msg = f"🚫 过滤: {filtered_count}\n" if filtered_count > 0 else ""

                        if tmdb_info:
                            if tmdb_info.get('poster_path'):
                                try:
                                    poster_resp = await loop.run_in_executor(None, requests.get, tmdb_info['poster_path'])
                                    if poster_resp.status_code == 200:
                                        poster_path = f"thumb_mc.jpg"
                                        with open(poster_path, 'wb') as f: f.write(poster_resp.content)
                                except: pass
                            
                            analysis_report = tv_analyzer.analyze_files(file_list, tmdb_info)
                            metadata = {'plot': tmdb_info.get('overview', '')}
                            
                            caption = (
                                f"{tmdb_info.get('media_type')}｜{tmdb_info.get('title')} ({tmdb_info.get('year')})\n\n"
                                f"⭐️ 评分: {tmdb_info.get('vote_average')}\n"
                                f"🌍 地区: {tmdb_info.get('countries')}\n"
                                f"📽 类型: {tmdb_info.get('genres')}\n"
                                f"🎬 导演: {tmdb_info.get('director')}...\n"
                                f"👥 主演: {tmdb_info.get('cast')}...\n"
                                f"\n📖 简介: <blockquote expandable=\"\">{metadata.get('plot')[:100]}...</blockquote>\n\n"
                                f"📂 目录: {folder_name}\n"
                                f"📊 状态: 成功 {success_count} / 失败 {fail_count}\n"
                                f"{filter_msg}"
                                f"📦 体积: {total_size_str} \n"
                                f"🖼️ 质量: {quality}\n"
                                f"🦋 完整性: {analysis_report}\n\n"
                                f"🙋 来自🤖转存完成"
                            )
                        else:
                            caption = (
                                f"📂 <b>{folder_name}</b>\n\n"
                                f"⚠️ 未找到 TMDB 信息 (关键词: {clean_keyword})\n"
                                f"📊 状态: 成功 {success_count} / 失败 {fail_count}\n"
                                f"{filter_msg}"
                                f"📦 体积: {total_size_str} \n"
                                f"🖼️ 质量: {quality}\n"
                                f"🙋 来自🤖转存完成"
                            )
                        
                        try: await status_msg.delete()
                        except: pass
                        
                        if poster_path:
                            await client.send_photo(message.chat.id, photo=poster_path, caption=caption, parse_mode=enums.ParseMode.HTML)
                            os.remove(poster_path)
                        else:
                            await client.send_message(message.chat.id, caption, parse_mode=enums.ParseMode.HTML)
                    else:
                        await status_msg.edit_text("✅ JSON 转存结束 (无返回数据)")
                    return

                # C. 处理链接 (普通文本)
                if not json_data and (target_msg.text or target_msg.caption):
                    text_content = target_msg.text or target_msg.caption
                    links = extract_123_links_from_full_text(text_content)
                    if links:
                        await status_msg.edit_text(f"🔗 发现 {len(links)} 个链接，处理中...")
                        results = []
                        def process_links_sync():
                            res_list = []
                            with link_process_lock:
                                for link in links:
                                    try:
                                        # parse_share_link 内部也已经集成了过滤逻辑
                                        parse_share_link(None, link, send_messages=False)
                                        res_list.append(f"✅ 已提交: {link[:15]}...")
                                    except Exception as e:
                                        res_list.append(f"❌ 失败: {str(e)[:20]}")
                            return res_list
                        
                        res = await loop.run_in_executor(None, process_links_sync)
                        await status_msg.edit_text(f"✅ 链接处理完毕:\n" + "\n".join(res))
                        return

                await status_msg.edit_text("❌ 未找到有效的 JSON (文件/文本)。")

            except Exception as e:
                logger.error(f"Userbot -mc error: {e}")
                await status_msg.edit_text(f"❌ 错误: {e}")

        async def runner():
            try:
                logger.info("🔄 [人形模块] 连接中...")
                await app.start()
                me = await app.get_me()
                logger.info(f"✅ [人形模块] 🎉🎉就绪🎉🎉！用户💃🏻: {me.first_name}")

                await asyncio.Event().wait()

            except Exception as e:
                logger.error(f"❌ [人形模块] 运行出错: {e}")
            finally:
                if app.is_connected: await app.stop()

        loop.run_until_complete(runner())

    except Exception as e:
        logger.error(f"❌ [人形模块] 崩溃: {traceback.format_exc()}")

# 新增函数：查询已存在的未失效分享链接
def get_existing_shares(client: P123Client, folder_name: str) -> dict:
    """查询已存在的未失效分享链接"""
    shares = []
    last_share_id = 0
    try:
        while True:
            # 调用分享列表API
            response = requests.get(
                f"https://open-api.123pan.com/api/v1/share/list?limit=100&lastShareId={last_share_id}",
                headers={
                    'Authorization': f'Bearer {client.token}',
                    'Platform': 'open_platform'
                },
                timeout=TIMEOUT
            )
            data = response.json()

            if data.get('code') != 0:
                logger.error(f"获取分享列表失败: {data.get('message')}")
                break

            # 提取当前页分享数据
            share_list = data.get('data', {}).get('shareList', [])
            shares.extend(share_list)

            # 处理分页
            last_share_id = data.get('data', {}).get('lastShareId', -1)
            if last_share_id == -1:
                break  # 已到最后一页

        # 筛选出名称匹配且未失效的分享
        for share in shares:
            if (share.get('shareName') == folder_name and
                    share.get('expired') == 0 and  # expired=0表示未失效
                    share.get('expiration', '') > '2050-06-30 00:00:00'):  # 过期时间大于2050-06-30 00:00:00
                return {
                    "url": f"https://www.123pan.com/s/{share.get('shareKey')}",
                    "password": share.get('sharePwd'),
                    "expiry": "永久有效"
                }

        # 未找到匹配的有效分享
        return None

    except Exception as e:
        logger.error(f"查询已存在分享失败: {str(e)}")
        return None


def core_process_json_data(json_data, log_callback):
    """
    执行 JSON 转存的核心逻辑 (修复除以零错误版)
    """
    try:
        # 1. 解析 JSON 数据
        if isinstance(json_data, list):
            # 格式2: 数组格式 [[etag, size, filename], ...]
            logger.info("检测到数组格式的妙传文件")
            common_path = ''
            files = []
            uses_v2_etag = False
            total_size_json = 0
            
            for item in json_data:
                if isinstance(item, list) and len(item) >= 3:
                    etag, size, filename = item[0], item[1], item[2]
                    files.append({
                        'path': filename,
                        'etag': etag,
                        'size': size
                    })
                    total_size_json += int(size)
        else:
            # 格式1: 对象格式 {commonPath, files, ...}
            logger.info("检测到对象格式的妙传文件")
            common_path = json_data.get('commonPath', '').strip()
            if common_path.endswith('/'):
                common_path = common_path[:-1]
            files = json_data.get('files', [])
            uses_v2_etag = json_data.get('usesBase62EtagsInExport', False)
            total_size_json = json_data.get('totalSize', 0)

        # 2. 过滤文件逻辑
        filtered_files = []
        skipped_count_by_ext = 0
        
        for file_info in files:
            f_path = file_info.get('path', '')
            if check_ext_filter(f_path):
                skipped_count_by_ext += 1
                continue
            filtered_files.append(file_info)
        
        files = filtered_files
        
        if skipped_count_by_ext > 0:
            log_callback(f"🚫 根据配置过滤了 {skipped_count_by_ext} 个不需要的文件")

        if not files:
            log_callback("JSON文件中没有找到有效文件（或全部被过滤）。")
            return None

        # 3. 准备工作
        total_files_count = len(files) # 锁定总数，防止变化
        log_callback(f"开始转存JSON文件中的 {total_files_count} 个文件...")
        start_time = time.time()
        
        client = init_123_client()
        results = []
        message_batch = []
        batch_size = 0
        total_size = 0
        skip_count = 0
        last_etag = None
        success_filenames = [] 
        folder_cache = {}
        target_dir_name = common_path if common_path else 'JSON转存'
        target_dir_id = UPLOAD_JSON_TARGET_PID

        # 4. 遍历转存
        for i, file_info in enumerate(files):
            file_path = file_info.get('path', '')
            if common_path:
                file_path = f"{common_path}/{file_path}"
            etag = file_info.get('etag', '')
            size = int(file_info.get('size', 0))

            if not all([file_path, etag, size]):
                results.append({"success": False, "file_name": file_path, "error": "信息不全"})
                continue

            try:
                # 4.1 创建目录
                path_parts = file_path.split('/')
                file_name = path_parts.pop()
                parent_id = target_dir_id
                current_path = ""
                
                for part in path_parts:
                    if not part: continue
                    current_path = f"{current_path}/{part}" if current_path else part
                    cache_key = f"{parent_id}/{current_path}"

                    if cache_key in folder_cache:
                        parent_id = folder_cache[cache_key]
                        continue

                    retry_count = 3
                    folder = None
                    while retry_count > 0:
                        try:
                            folder = client.fs_mkdir(part, parent_id=parent_id, duplicate=1)     
                            time.sleep(0.2)                  
                            check_response(folder)
                            break
                        except Exception:
                            retry_count -= 1
                            time.sleep(3)

                    if folder:
                        folder_id = folder["data"]["Info"]["FileId"]
                        folder_cache[cache_key] = folder_id
                        parent_id = folder_id
                
                # 4.2 处理ETag
                if uses_v2_etag:
                    etag = optimized_etag_to_hex(etag, True)

                # 4.3 执行秒传
                retry_count = 3
                rapid_resp = None
                while retry_count > 0:
                    if last_etag == etag:
                        skip_count += 1
                        rapid_resp = {"data": {"Reuse": True, "Skip": True}, "code": 0}
                        break
                    try:
                        rapid_resp = client.upload_file_fast(
                            file_name=file_name,
                            parent_id=parent_id,
                            file_md5=robust_normalize_md5(etag),
                            file_size=size,
                            duplicate=1
                        )
                        check_response(rapid_resp)
                        break
                    except Exception:
                        retry_count -= 1
                        time.sleep(3)

                # 4.4 记录结果
                dir_p = os.path.dirname(file_path)
                
                if rapid_resp is None:
                    err = "请求重试耗尽"
                    results.append({"success": False, "file_name": file_path, "error": err})
                    message_batch.append({'status': '❌', 'dir': dir_p, 'file': f"{file_name} ({err})"})
                    
                elif rapid_resp.get("code") == 0 and rapid_resp.get("data", {}).get("Reuse", False):
                    if rapid_resp.get("data", {}).get("Skip"):
                        message_batch.append({'status': '🔄', 'dir': dir_p, 'file': f"{file_name} (重复)"})
                        success_filenames.append(file_name) 
                    else:
                        last_etag = etag
                        results.append({"success": True, "file_name": file_path, "size": size})
                        total_size += size
                        message_batch.append({'status': '✅', 'dir': dir_p, 'file': file_name})
                        success_filenames.append(file_name) 
                else:
                    err = "无法秒传"
                    results.append({"success": False, "file_name": file_path, "error": err})
                    message_batch.append({'status': '❌', 'dir': dir_p, 'file': f"{file_name} ({err})"})
                
                batch_size += 1

                # 4.5 [关键修复] 安全的日志计算
                if batch_size % 10 == 0:
                    tree_messages = defaultdict(lambda: {'✅': [], '❌': [], '🔄': []})
                    for entry in message_batch:
                        tree_messages[entry['dir']][entry['status']].append(entry['file'])
                    
                    batch_msg = []
                    for d, s_files in tree_messages.items():
                        for s, fs in s_files.items():
                            if fs:
                                batch_msg.append(f"--- {s} {d}")
                                for idx, f in enumerate(fs):
                                    prefix = '      └──' if idx == len(fs)-1 else '      ├──'
                                    batch_msg.append(f"{prefix} {f}")
                    batch_msg_str = "\n".join(batch_msg)
                    
                    # 修复点1：防止 total_files_count 为 0
                    if total_files_count > 0:
                        percent = int(batch_size / total_files_count * 100)
                    else:
                        percent = 0
                        
                    log_callback(f"📊 {batch_size}/{total_files_count} ({percent}%) 个文件已处理\n\n{batch_msg_str}")
                    message_batch = []
                
                # 4.6 [关键修复] 安全的速率休眠
                # 防止 ENV_FILE_PER_SECOND 为 0 导致 crash
                rate_limit = get_int_env("ENV_FILE_PER_SECOND", 5)
                if rate_limit > 0:
                    time.sleep(1.0 / rate_limit)

            except Exception as e:
                # 捕获单个文件处理中的所有异常，防止打断整个任务
                err_str = str(e)
                logger.error(f"处理文件出错 {file_name}: {err_str}")
                results.append({"success": False, "file_name": file_path, "error": err_str})
                message_batch.append({'status': '❌', 'dir': os.path.dirname(file_path), 'file': f"{file_name} ({err_str})"})
                batch_size += 1

        # 5. 处理剩余消息
        if message_batch:
            tree_messages = defaultdict(lambda: {'✅': [], '❌': [], '🔄': []})
            for entry in message_batch:
                tree_messages[entry['dir']][entry['status']].append(entry['file'])
            batch_msg = []
            for d, s_files in tree_messages.items():
                for s, fs in s_files.items():
                    if fs:
                        batch_msg.append(f"--- {s} {d}")
                        for idx, f in enumerate(fs):
                            prefix = '      └──' if idx == len(fs)-1 else '      ├──'
                            batch_msg.append(f"{prefix} {f}")
            batch_msg_str = "\n".join(batch_msg)
            log_callback(f"📊 {batch_size}/{total_files_count} (100%) 个文件已处理\n\n{batch_msg_str}")

        # 6. 统计结果
        end_time = time.time()
        elapsed_time = end_time - start_time
        hours, remainder = divmod(int(elapsed_time), 3600)
        minutes, seconds = divmod(remainder, 60)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count
        size_str = get_formatted_size(total_size)

        result_msg = (
            f"✅ JSON文件转存完成！\n"
            f"✅成功: {success_count}个\n"
            f"❌失败: {fail_count}个\n"
            f"🔄跳过重复: {skip_count}个\n"
            f"🚫后缀过滤: {skipped_count_by_ext}个\n"
            f"📊体积: {size_str}\n"
            f"⏱️耗时: {time_str}"
        )
        log_callback(result_msg)

        if fail_count > 0:
            failed_files = [f"• {r['file_name']}（{r.get('error')}）" for r in results if not r.get("success")]
            # 分批发送错误日志
            for idx in range(0, len(failed_files), 10):
                batch = failed_files[idx:idx+10]
                batch_msg = "❌ 失败详情:\n" + "\n".join(batch)
                log_callback(batch_msg)
                time.sleep(0.5)
        
        return {
            "success_count": success_count,
            "fail_count": fail_count,
            "skip_count": skip_count,
            "filtered_count": skipped_count_by_ext,
            "total_size_str": size_str,
            "time_str": time_str,
            "target_dir_name": target_dir_name, 
            "file_list": success_filenames     
        }

    except Exception as e:
        logger.error(f"核心JSON处理异常: {str(e)}")
        log_callback(f"❌ 核心处理失败: {str(e)}")
        return None

@bot.message_handler(content_types=['document'], func=lambda message: message.document.mime_type == 'application/json' or message.document.file_name.endswith('.json'))
def process_json_file(message):
    with link_process_lock:  # 获取锁，确保多个请求依次处理
        user_id = message.from_user.id
        if user_id != TG_ADMIN_USER_ID:
            reply_thread_pool.submit(send_reply, message, "您没有权限使用此功能。")
            return
        
        logger.info("进入 Bot 文件转存 JSON 流程")
        
        try:
            # 1. 获取并下载文件
            file_retry_count = 0
            file_path = None
            while file_retry_count < 10:
                try:
                    file_id = message.document.file_id
                    file_info = bot.get_file(file_id)
                    file_path = file_info.file_path
                    break
                except Exception as e:
                    logger.error(f"从TG获取文件失败: {e}")
                    file_retry_count += 1
                    time.sleep(3)
            
            if not file_path:
                reply_thread_pool.submit(send_reply, message, "下载文件失败，请重试。")
                return

            json_url = f'https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}'
            response = requests.get(json_url)
            response.encoding = 'utf-8' # 显式设置编码
            json_data = response.json()

            # 2. 定义回调函数，适配 core_process_json_data 的日志接口
            def bot_log_adapter(text):
                # 如果是进度条消息，尝试使用 delete 模式发送（如果逻辑支持）
                if "📊" in text:
                    reply_thread_pool.submit(send_reply_delete, message, text)
                else:
                    reply_thread_pool.submit(send_reply, message, text)

            # 3. 调用核心处理函数
            core_process_json_data(json_data, bot_log_adapter)
            
        except Exception as e:
            logger.error(f"处理JSON文件全局异常: {str(e)}")
            reply_thread_pool.submit(send_reply, message, f"❌ 处理异常: {str(e)}")

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
link_process_lock = threading.Lock()
quark_folder_lock = threading.Lock()
def process_single_quark_file(client, file_info, common_path, target_dir_id, folder_cache, uses_v2_etag):
    """单个夸克文件处理函数 (用于多线程并发)"""
    file_path = file_info.get('path', '')
    
    if check_ext_filter(file_path):
        return {
            "success": True,   
            "file_name": file_path, 
            "size": 0, 
            "skip": False, 
            "msg": "后缀过滤"  
        }  
    
    # 构建完整文件路径
    if common_path:
        file_path = f"{common_path}/{file_path}"
    etag = file_info.get('etag', '')
    size = int(file_info.get('size', 0))

    if not all([file_path, etag, size]):
        return {"success": False, "file_name": file_path or "未知文件", "error": "文件信息不完整", "path": file_path}

    try:
        # --- 1. 目录结构处理 (线程安全区) ---
        path_parts = file_path.split('/')
        file_name = path_parts.pop()
        parent_id = target_dir_id
        
        current_path = ""
        # 遍历路径创建目录
        for part in path_parts:
            if not part: continue
            current_path = f"{current_path}/{part}" if current_path else part
            cache_key = f"{parent_id}/{current_path}"

            # 加锁检查/创建目录，防止多线程竞争导致重复创建
            with quark_folder_lock:
                if cache_key in folder_cache:
                    parent_id = folder_cache[cache_key]
                else:
                    # 创建新文件夹（带重试）
                    mk_retry = 2
                    folder_id = None
                    while mk_retry > 0:
                        try:
                            # 尝试创建
                            folder = client.fs_mkdir(part, parent_id=parent_id, duplicate=1)
                            # 简单的检查，不做耗时的 check_response
                            if folder.get("code") == 0:
                                folder_id = folder["data"]["Info"]["FileId"]
                                break
                            else:
                                mk_retry -= 1
                                time.sleep(0.5)
                        except Exception:
                            mk_retry -= 1
                            time.sleep(0.5)
                    
                    if folder_id:
                        folder_cache[cache_key] = folder_id
                        parent_id = folder_id
                    else:
                        # 创建失败则沿用上级ID，防止整条路径失败
                        pass

        # --- 2. 处理ETag ---
        if uses_v2_etag:
            etag = optimized_etag_to_hex(etag, True)
        
        final_md5 = robust_normalize_md5(etag)

        # --- 3. 执行秒传 (耗时操作，并发执行) ---
        retry_count = 3
        rapid_resp = None
        
        while retry_count > 0:
            try:
                rapid_resp = client.upload_file_fast(
                    file_name=file_name,
                    parent_id=parent_id,
                    file_md5=final_md5,
                    file_size=size,
                    duplicate=1
                )
                
                # 成功判断 (Reuse=True)
                if rapid_resp.get("code") == 0 and \
                   (rapid_resp.get("data", {}).get("Reuse") or rapid_resp.get("data", {}).get("reuse")):
                    return {
                        "success": True, 
                        "file_name": file_path, 
                        "size": size, 
                        "skip": rapid_resp.get("data", {}).get("Skip", False),
                        "file_id": rapid_resp.get("data", {}).get("FileId", "")
                    }
                
                # 明确的失败 (Reuse=False)
                if rapid_resp.get("code") == 0:
                     return {
                        "success": False, 
                        "file_name": file_path, 
                        "error": "云端无此文件，秒传失败"
                    }
                
                # 其他API错误，重试
                retry_count -= 1
                time.sleep(2)
                
            except Exception as e:
                retry_count -= 1
                time.sleep(2)
                if retry_count == 0:
                    return {"success": False, "file_name": file_path, "error": str(e)}

        return {"success": False, "file_name": file_path, "error": rapid_resp.get("message", "请求超时") if rapid_resp else "未知错误"}

    except Exception as e:
        return {"success": False, "file_name": file_path, "error": f"处理异常: {str(e)}"}


def save_json_file_quark(message, json_data):
    logger.info("进入123转存夸克 (智能重试版 V5 - 直接发送JSON)")
    try:
        # 1. 基础数据提取
        origin_common_path = json_data.get('commonPath', '').strip()
        if origin_common_path and not origin_common_path.endswith('/'):
            origin_common_path += '/'
            
        files = json_data.get('files', [])
        uses_v2_etag = json_data.get('usesBase62EtagsInExport', False)
        total_files_count = len(files)

        if not files:
            reply_thread_pool.submit(send_reply, message, "夸克分享中没有找到文件信息。")
            return

        # 发送初始消息
        status_msg_text = f"🚀 开始转存夸克文件 (共 {total_files_count} 个)...\n⚡️ 正在启动多线程加速..."
        reply_thread_pool.submit(send_reply_delete, message, status_msg_text)
        
        start_time = time.time()
        client = init_123_client()

        # 2. 初始化统计变量
        results = []
        total_size = 0
        skip_count = 0     # 重复跳过
        filter_count = 0   # 后缀过滤
        success_count = 0  # 实际成功
        fail_count = 0     # 失败
        
        # [新增] 视频统计变量
        video_count = 0
        video_total_size = 0
        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.ts', '.rmvb', '.iso', '.wmv', '.m2ts', '.mpg', '.flv', '.rm'}

        # 用于收集失败文件的列表
        failed_files_data = []
        
        # 文件夹缓存
        folder_cache = {}
        target_dir_id = get_int_env("ENV_123_KUAKE_UPLOAD_PID", 0)
        
        # 3. 启动多线程
        max_workers = 5  
        
        processed_count = 0
        last_report_time = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务
            future_to_file = {
                executor.submit(
                    process_single_quark_file, 
                    client, 
                    file_info, 
                    origin_common_path, 
                    target_dir_id, 
                    folder_cache, 
                    uses_v2_etag
                ): file_info for file_info in files
            }
            
            for future in as_completed(future_to_file):
                processed_count += 1
                file_info = future_to_file[future]
                res = future.result()
                
                # 统计逻辑
                if res['success']:
                    # 检查是否为后缀过滤
                    if res.get('msg') == "后缀过滤":
                        filter_count += 1
                    
                    # 检查是否为重复跳过
                    elif res.get('skip'):
                        skip_count += 1
                        success_count += 1 # 逻辑上算成功
                        # 统计视频信息（重复的也算在视频统计里，看需求，通常算了总数也要算这个）
                        fname = res.get('file_name', '')
                        fsize = res.get('size', 0)
                        if os.path.splitext(fname)[1].lower() in video_exts:
                            video_count += 1
                            video_total_size += fsize
                        
                    # 正常转存成功
                    else:
                        success_count += 1
                        total_size += res['size']
                        # 统计视频信息
                        fname = res.get('file_name', '')
                        fsize = res.get('size', 0)
                        if os.path.splitext(fname)[1].lower() in video_exts:
                            video_count += 1
                            video_total_size += fsize
                        logger.info(f"✅ [夸克] 秒传成功: {res['file_name']}")
                else:
                    fail_count += 1
                    logger.warning(f"❌ [夸克] 秒传失败: {res['file_name']} ({res.get('error')})")
                    failed_files_data.append(file_info)
                
                results.append(res)
                
                # 进度报告
                current_time = time.time()
                if current_time - last_report_time > 3 or processed_count == total_files_count:
                    last_report_time = current_time
                    percent = int(processed_count / total_files_count * 100)
                    progress_msg = (
                        f"📊 转存进度: {processed_count}/{total_files_count} ({percent}%)\n"
                        f"✅ 成功: {success_count} (跳过 {skip_count})\n"
                        f"🚫 过滤: {filter_count}\n"
                        f"❌ 失败: {fail_count}"
                    )
                    reply_thread_pool.submit(send_reply_delete, message, progress_msg)

        # 4. 最终统计
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        hours, remainder = divmod(int(elapsed_time), 3600)
        minutes, seconds = divmod(remainder, 60)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        total_size_gb = total_size / (1024 ** 3)
        size_str = f"{total_size_gb:.2f}GB"
        
        # 计算视频平均大小
        video_avg_size_str = "0B"
        video_total_size_str = get_formatted_size(video_total_size)
        if video_count > 0:
            video_avg_size_str = get_formatted_size(video_total_size / video_count)

        result_msg = (
            f"✅ 夸克转存任务完成！\n"
            f"📂 总文件: {total_files_count}个\n"
            f"✅ 成功: {success_count}个\n"
            f"❌ 失败: {fail_count}个\n"
            f"🔄 跳过重复: {skip_count}个\n"
            f"🚫 后缀过滤: {filter_count}个\n"
            f"----------------------\n"
            f"🎬 视频统计: {video_count}个\n"
            f"📹 视频总大: {video_total_size_str}\n"
            f"📏 平均大小: {video_avg_size_str}\n"
            f"----------------------\n"
            f"📦 实际转存: {size_str}\n"
            f"⏱️ 耗时: {time_str}"
        )
        reply_thread_pool.submit(send_reply, message, result_msg)
        
        # 5. [优化] 生成并发送失败文件列表 (直接发送JSON)
        if fail_count > 0 and failed_files_data:
            try:
                # --- 计算新的 commonPath ---
                full_paths = []
                for f in failed_files_data:
                    rel_path = f.get('path', '').replace('\\', '/')
                    if origin_common_path:
                        full_p = f"{origin_common_path}{rel_path}"
                    else:
                        full_p = rel_path
                    full_paths.append(full_p)
                
                new_common_prefix = ""
                if full_paths:
                    try:
                        new_common_prefix = os.path.commonpath(full_paths)
                        new_common_prefix = new_common_prefix.replace('\\', '/')
                        if new_common_prefix:
                            new_common_prefix += '/'
                    except ValueError:
                        new_common_prefix = ""
                
                # --- 修正文件路径并强制字典顺序 ---
                processed_files = []
                total_retry_size = 0
                for f, full_p in zip(failed_files_data, full_paths):
                    if new_common_prefix and full_p.startswith(new_common_prefix):
                        final_path = full_p[len(new_common_prefix):]
                    else:
                        final_path = full_p 
                    
                    # 显式按顺序构造字典: path -> etag -> size
                    new_f = {
                        "path": final_path,
                        "etag": f.get('etag'),
                        "size": f.get('size')
                    }
                    processed_files.append(new_f)
                    total_retry_size += int(f.get('size', 0))

                # --- 构造有序字典 (头部在最前，files在最后) ---
                retry_json = {}
                retry_json["usesBase62EtagsInExport"] = uses_v2_etag
                retry_json["etagEncrypted"] = False
                retry_json["commonPath"] = new_common_prefix
                retry_json["totalFilesCount"] = len(processed_files)
                retry_json["totalSize"] = total_retry_size
                retry_json["files"] = processed_files 
                
                # --- 决定文件名 (后缀改为 .json) ---
                if new_common_prefix:
                    filename_base = new_common_prefix.strip('/')
                    filename_base = re.sub(r'[\\/:*?"<>|]', '_', filename_base)
                    retry_filename = f"{filename_base}.json"
                else:
                    timestamp = int(time.time())
                    retry_filename = f"failed_files_{timestamp}.json"
                
                with open(retry_filename, 'w', encoding='utf-8') as f:
                    json.dump(retry_json, f, ensure_ascii=False, indent=2)
                
                # --- 发送文件 ---
                caption = (
                    f"⚠️ `检测到 {fail_count} 个文件转存失败。`\n"
                    f"📄 `已生成失败重试文件：{retry_filename}`\n"
                    f"💡 `  👇👇👇食用方法👇👇👇`\n\n"
                    f"`待 123 云盘资源更新后，直接将此 **JSON 文件转发给机器人** 即可重试。`\n"
                )
                
                with open(retry_filename, 'rb') as f:
                    bot.send_document(
                        message.chat.id, 
                        f, 
                        caption=caption,
                        parse_mode='Markdown'
                    )
                
                os.remove(retry_filename)
                
            except Exception as e:
                logger.error(f"生成失败重试文件出错: {e}")
                reply_thread_pool.submit(send_reply, message, f"❌ 生成失败列表文件出错: {str(e)}")

    except Exception as e:
        logger.error(f"夸克转存全局异常: {str(e)}")
        reply_thread_pool.submit(send_reply, message, f"❌ 处理异常: {str(e)}")

# Base62字符表（123云盘V2 API使用）
BASE62_CHARS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

def optimized_etag_to_hex(etag, is_v2=False):
    """将Base62编码的ETag转换为十六进制格式（参考123pan_bot中的实现）"""
    if not is_v2:
        return etag
    
    try:
        # 检查是否是有效的MD5格式（32位十六进制）
        if len(etag) == 32 and all(c in '0123456789abcdefABCDEF' for c in etag):
            return etag.lower()
        
        # 转换Base62到十六进制
        num = 0
        for char in etag:
            if char not in BASE62_CHARS:
                logger.error(f"❌ ETag包含无效字符: {char}")
                return etag
            num = num * 62 + BASE62_CHARS.index(char)
        
        # 转换为十六进制并确保32位
        hex_str = hex(num)[2:].lower()
        if len(hex_str) > 32:
            # 取后32位
            hex_str = hex_str[-32:]
            logger.warning(f"ETag转换后长度超过32位，截断为: {hex_str}")
        elif len(hex_str) < 32:
            # 前面补零
            hex_str = hex_str.zfill(32)
            logger.warning(f"ETag转换后不足32位，补零后: {hex_str}")
        
        # 验证是否为有效的MD5
        if len(hex_str) != 32 or not all(c in '0123456789abcdef' for c in hex_str):
            logger.error(f"❌ 转换后ETag格式无效: {hex_str}")
            return etag
        
        return hex_str
    except Exception as e:
        logger.error(f"❌ ETag转换失败: {str(e)}")
        return etag

# 注册文档消息处理器（已移至start_bot_thread函数内部）
# bot.message_handler(content_types=['document'])(process_json_file)

# 定义bot线程变量
bot_thread = None

def start_bot_thread():
    global bot
    # 确保bot实例存在
    if not bot:
        bot = telebot.TeleBot(TG_BOT_TOKEN)
    while True:
        try:
            #bot.polling(none_stop=True, interval=1)
            bot.infinity_polling(logger_level=logging.ERROR)
        except Exception as e:
            logger.warning(f"代理网络不稳定，与TG尝试重连中...\n错误原因:{str(e)}")
            time.sleep(5)
    return threading.current_thread()



def check_task():
    global bot_thread
    # 检查bot线程状态（固定20秒检查一次）
    if not bot_thread or not bot_thread.is_alive():
        logger.warning(f"代理网络不稳定，与TG尝试重连中...")
        bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
        bot_thread.start()

if __name__ == "__mp_main__":
    from bot115 import tg_115monitor
    from bot189 import Cloud189
    client189 = Cloud189()
    ENV_189_CLIENT_ID = os.getenv("ENV_189_CLIENT_ID","")
    ENV_189_CLIENT_SECRET = os.getenv("ENV_189_CLIENT_SECRET","")

    if (ENV_189_CLIENT_ID and ENV_189_CLIENT_SECRET):
        logger.info("天翼云盘正在尝试登录 ...")
        client189.login(ENV_189_CLIENT_ID, ENV_189_CLIENT_SECRET)

# === [重写] 全能版天翼云监控 (集成秒传+目录结构+兜底+优雅战报) ===
def tg_189monitor(client189):
    # 引用必要组件
    from bot189 import init_database, get_latest_messages, save_message, TelegramNotifier
    from bot189 import TG_BOT_TOKEN, TG_ADMIN_USER_ID, get_share_file_snapshot, save_189_link
    
    init_database()
    notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
    logger.info("===== 开始检查 天翼网盘监控 (智能秒传版) =====")

    # 1. 获取新消息
    new_messages = get_latest_messages()
    if not new_messages:
        return

    # 2. 初始化 123 客户端
    client123 = init_123_client()

    # 3. 获取目录配置
    # 123目标目录 (秒传用)
    pid_for_123 = os.getenv("ENV_189GO123_UPLOAD_PID", "")
    if not pid_for_123:
        pid_for_123 = os.getenv("ENV_123_UPLOAD_PID", "0")

    # 189兜底目录 (转存用)
    pid_for_189 = os.getenv("ENV_189_LINK_UPLOAD_PID", "")
    if not pid_for_189:
        pid_for_189 = os.getenv("ENV_189_UPLOAD_PID", "-11")

    logger.info(f"189监控配置 | 123目标ID: {pid_for_123} | 189兜底ID: {pid_for_189}")

    # 4. 遍历处理新消息
    for msg in new_messages:
        message_id, date_str, message_url, target_url, message_text = msg
        logger.info(f"处理新消息: {target_url}")
        
        status = "处理中"
        result_msg = ""
        
        try:
            # === A. 获取快照 (只读不存) ===
            files_in_share, root_share_name = get_share_file_snapshot(client189, target_url)
            
            all_rapid_success = False
            
            # [新增] 提前定义统计变量，供后续复用
            video_count = 0
            total_size_str = "未知"
            avg_size_str = "未知"
            display_msg_url = message_url
            
            # [新增] 尝试预先计算统计信息 (如果快照获取成功)
            if files_in_share:
                try:
                    # 1. 过滤后缀 (如果全局定义了check_ext_filter则调用，否则跳过)
                    filtered_files = []
                    for f in files_in_share:
                        if 'check_ext_filter' in globals() and check_ext_filter(f.get('name', '')):
                            continue
                        filtered_files.append(f)
                    files_in_share = filtered_files

                    # 2. 统计数据
                    video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.ts', '.rmvb', '.iso', '.wmv', '.m2ts', '.mpg', '.flv', '.rm'}
                    video_files = [f for f in files_in_share if os.path.splitext(f.get('name', ''))[1].lower() in video_exts]
                    video_count = len(video_files)
                    total_size_bytes = sum(f.get('size', 0) for f in files_in_share)
                    
                    if video_count > 0:
                        avg_size_bytes = total_size_bytes / video_count
                    else:
                        avg_size_bytes = total_size_bytes / len(files_in_share) if files_in_share else 0
                    
                    total_size_str = get_formatted_size(total_size_bytes)
                    avg_size_str = get_formatted_size(avg_size_bytes)
                    
                    # 3. 链接修复
                    if display_msg_url and not display_msg_url.startswith('http'):
                        display_msg_url = f"https://t.me/{display_msg_url}"
                except Exception as e:
                    logger.warning(f"统计信息计算失败: {e}")

            if files_in_share:
                total_f = len(files_in_share)
                success_f = 0
                logger.info(f"解析成功，共 {total_f} 个文件，尝试秒传...")
                
                # 文件夹缓存 (避免重复API请求)
                folder_cache = {}
                
                # === B. 尝试秒传到 123 (带目录结构) ===
                for i, f_info in enumerate(files_in_share):
                    try:
                        # 1. 路径解析
                        raw_path = f_info.get('path', '').strip('/')
                        path_parts = raw_path.split('/')
                        file_name = path_parts.pop()
                        
                        # 2. 构建目录链 (根目录名 + 子目录)
                        dir_chain = []
                        if root_share_name:
                            dir_chain.append(root_share_name)
                        dir_chain.extend([p for p in path_parts if p])
                        
                        # 3. 递归定位目标文件夹ID
                        current_pid = pid_for_123
                        
                        for folder_name in dir_chain:
                            cache_key = f"{current_pid}_{folder_name}"
                            if cache_key in folder_cache:
                                current_pid = folder_cache[cache_key]
                                continue
                            
                            found_id = find_child_folder_id(client123, current_pid, folder_name)
                            if found_id:
                                folder_cache[cache_key] = found_id
                                current_pid = found_id
                            else:
                                try:
                                    resp = client123.fs_mkdir(folder_name, parent_id=current_pid)
                                    if resp.get("code") == 0:
                                        new_id = resp["data"]["Info"]["FileId"]
                                        folder_cache[cache_key] = new_id
                                        current_pid = new_id
                                except Exception:
                                    pass

                        # 4. 执行秒传
                        resp = client123.upload_file_fast(
                            file_name=file_name,
                            parent_id=current_pid,
                            file_md5=f_info['md5'],
                            file_size=f_info['size'],
                            duplicate=1
                        )
                        
                        if resp.get("code") == 0 and \
                           (resp.get("data", {}).get("Reuse") or resp.get("data", {}).get("reuse")):
                            success_f += 1
                            
                    except Exception as e:
                        pass
                
                logger.info(f"123直连秒传结果: {success_f}/{total_f}")
                
                # 全量成功，流程结束
                if success_f == total_f and total_f > 0:
                    all_rapid_success = True
                    status = "✅ 189⚡123云盘极速秒传成功"
                    # [优化] 极速秒传成功回复
                    result_msg = (
                        f"✅ 189⚡123云盘极速秒传成功！\n"
                        f"📁 名称: {root_share_name}\n"
                        f"📨 消息: {display_msg_url}\n"
                        f"🌍 链接: {target_url}\n"
                        f"🎬 视频: {video_count} 个\n"
                        f"📦 大小: {total_size_str} | 平均: {avg_size_str}\n"
                        f"✨ 零流量 · 秒级传输 · 不占空间"
                    )
                    notifier.send_message(result_msg)
                    save_message(message_id, date_str, message_url, target_url, status, result_msg)
                    continue # 跳过后续的兜底逻辑
            
            # === C. 兜底转存 (存到 189) ===
            # 如果秒传未覆盖所有文件，则执行老办法
            if not all_rapid_success:
                logger.info("123秒传未覆盖，执行兜底转存到天翼云盘...")
                
                # 使用专门的 189 兜底目录 ID
                result = save_189_link(client189, target_url, pid_for_189)
                
                if result:
                    status = "转存成功"
                    # [优化] 兜底转存成功回复
                    result_msg = (
                        f"✅ 已转存至天翼云盘 (123秒传未全覆盖)\n"
                        f"📁 名称: {root_share_name}\n"
                        f"📨 消息: {display_msg_url}\n"
                        f"🌍 链接: {target_url}\n"
                        f"🎬 统计: {video_count} 个视频 (需同步)\n"
                        f"📦 大小: {total_size_str} | 平均: {avg_size_str}\n"
                        f"💡 提示: 请稍后使用 /sync189 完成迁移"
                    )
                else:
                    status = "转存失败"
                    # [优化] 失败回复
                    result_msg = (
                        f"❌ 天翼云转存失败 (空间不足或其他错误)\n"
                        f"📁 名称: {root_share_name}\n"
                        f"📨 消息: {display_msg_url}\n"
                        f"🌍 链接: {target_url}\n"
                        f"📦 大小: {total_size_str}\n"
                        f"🔧 建议: 请检查天翼云空间或Cookie状态"
                    )
                
                notifier.send_message(result_msg)
                save_message(message_id, date_str, message_url, target_url, status, result_msg)

        except Exception as e:
            logger.error(f"处理监控消息异常: {e}")
            save_message(message_id, date_str, message_url, target_url, "报错", f"异常: {e}")


def main():     
    from server import app
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=12366, debug=False, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    while (os.getenv("ENV_WEB_PASSPORT", "") == "") or (os.getenv("ENV_123_CLIENT_ID", "") == ""):
        try:
            logger.warning("请检查docker-compose.yml中的 ENV_WEB_PASSPORT 以及配置web页面的 ENV_123_CLIENT_ID 是否填写完整，可前往 https://hub.docker.com/r/dydydd/123bot 查看部署方法")
            bot.send_message(TG_ADMIN_USER_ID,f"请检查docker-compose.yml中的 ENV_WEB_PASSPORT 以及配置web页面的 ENV_123_CLIENT_ID 是否填写完整，可前往 https://hub.docker.com/r/dydydd/123bot 查看部署方法")
        except Exception as e:
            logger.error(f"发送消息失败: {str(e)}")
        time.sleep(60)
    threading.Thread(target=ptto123, daemon=True).start()
    logger.info(f"123转存目标目录ID: {UPLOAD_TARGET_PID} | 检查间隔: {CHECK_INTERVAL}分钟")
    init_database()
    client = init_123_client()

    global bot_thread
    # 初始启动bot线程
    bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
    bot_thread.start()
    # [新增] 启动人形模块线程
    logger.info("正在启动人形模块线程...")
    threading.Thread(target=start_userbot_listener, daemon=True).start()
    
    schedule.every(20).seconds.do(check_task)

    if get_int_env("ENV_189_TGMONITOR_SWITCH", 0):
        
        try:            
            # 读取189清理配置
            env_189_clear_pid = os.getenv("ENV_189_CLEAR_PID", "")
            env_189_clear_period = get_int_env("ENV_189_CLEAR_PERIOD", 6)
            clear_folder_ids = [pid.strip() for pid in env_189_clear_pid.split(",") if pid.strip()]
            
            # 定义定时清理函数
            def clear_189_folders():
                logger.info(f"===== 开始执行天翼云盘文件夹清理任务（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）=====")
                try:
                    # 尝试删除文件夹内容（不检查登录状态，依赖方法内部处理）
                    for folder_id in clear_folder_ids:
                        logger.info(f"删除文件夹 {folder_id} 中的内容...")
                        try:
                            client189.delete_folder_contents(folder_id)
                            logger.info(f"成功删除文件夹 {folder_id} 中的内容")
                        except Exception as e:
                            logger.error(f"删除文件夹 {folder_id} 内容失败: {str(e)}")
                    
                    # 清空回收站
                    logger.info("清空回收站...")
                    try:
                        if client189.empty_recycle_bin():
                            logger.info("成功执行天翼网盘文件清理任务")
                            reply_thread_pool.submit(send_message, f"✅成功执行天翼网盘清空回收站任务（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
                        else:
                            logger.info("天翼网盘文件清理失败")
                            reply_thread_pool.submit(send_message, f"❌天翼网盘清空回收站失败（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
                    except Exception as e:
                        logger.error(f"清空回收站失败: {str(e)}")
                        reply_thread_pool.submit(send_message, f"❌天翼网盘清空回收站失败: {str(e)}（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
                except Exception as e:
                    logger.error(f"天翼云盘清理任务执行失败: {str(e)}")
                logger.info("===== 天翼云盘文件夹清理任务执行完毕 =====")
            
            # 设置定时任务，每env_189_clear_period小时执行一次
            if clear_folder_ids:
                logger.info(f"设置天翼云盘文件夹定时清理任务，每{env_189_clear_period}小时执行一次")
                schedule.every(env_189_clear_period).hours.do(clear_189_folders)
                # 立即执行一次清理任务
                clear_189_folders()
            else:
                logger.info("未配置ENV_189_CLEAR_PID，跳过天翼云盘文件夹定时清理任务")
        except Exception as e:
            logger.error(f"登录出现错误: {e}")

    try:
        while True:
            logger.info(f"===== 开始检查（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}），当前版本 {version}=====")
            if AUTHORIZATION:
                client = init_123_client()
                new_messages = get_latest_messages()
                schedule.run_pending()
                if new_messages:
                    for msg in new_messages:
                        message_id, date_str, message_url, target_url, message_text = msg
                        logger.info(f"处理新消息: {message_id} | {target_url}")
                        # 获取排除关键词环境变量（多个关键词用|分隔）
                        # 当排除关键词为空时，全都不排除
                        exclude_filter = os.environ.get('ENV_EXCLUDE_FILTER', '')
                        exclude_pattern = re.compile(exclude_filter) if exclude_filter else None

                        # 检查是否匹配过滤条件且不包含排除关键词
                        is_match = filter_pattern.search(target_url) or filter_pattern.search(message_text)
                        is_excluded = exclude_pattern and (exclude_pattern.search(target_url) or exclude_pattern.search(message_text))

                        if not is_match:
                            status = "未转存"
                            result_msg = f"未匹配过滤条件（{FILTER}），跳过转存"
                            logger.info(result_msg)
                            time.sleep(1)
                        elif is_excluded:
                            status = "未转存"
                            result_msg = f"包含排除关键词（{exclude_filter}），跳过转存"
                            logger.info(result_msg)
                            time.sleep(1)
                        else:
                            logger.info(f"消息匹配过滤条件（{FILTER}），开始转存...")
                            
                            # 二次过滤关键词配置（当某条消息触发转存后，如进一步满足下面的要求，则转移到特定的文件夹）
                            # 格式为：DV:1,DOLBY VISION:2,SSTA:3 即满足DV关键词转移到ID为1的文件夹，满足SSTA关键词转移到ID为3的文件夹
                            # 如果ENV_SECOND_FILTER为空，则全部转移至ENV_123_UPLOAD_PID
                            ENV_SECOND_FILTER = os.getenv("ENV_SECOND_FILTER", "")
                            transfer_id=UPLOAD_TARGET_PID
                            
                            # 根据关键词筛选并设置transfer_id
                            # ENV_SECOND_FILTER.strip() 用于去除字符串前后的空白字符（空格、制表符、换行符等）
                            # 这样可以确保即使环境变量值前后有空格也能正确处理，避免因空白字符导致的逻辑错误
                            # 如果去除空白后字符串不为空，则执行二次过滤逻辑
                            if ENV_SECOND_FILTER.strip():
                                try:
                                    # 解析二次过滤规则，格式为：关键词:文件夹ID,关键词:文件夹ID,...
                                    filter_rules = ENV_SECOND_FILTER.split(',')
                                    for rule in filter_rules:
                                        if ':' in rule:
                                            # 分割关键词和文件夹ID，但保留关键词中的空格（如"DOLBY VISION"中的空格会被保留）
                                            keyword, folder_id = rule.split(':', 1)
                                            # keyword.strip() 用于确保关键词不为空字符串
                                            # 注意：关键词内部的空格（如"DOLBY VISION"中的空格）不会被去除，会作为关键词的一部分进行匹配
                                            if (keyword.strip() and 
                                                (keyword in message_text or 
                                                 (target_url and keyword in target_url))):
                                                transfer_id = int(folder_id.strip())
                                                logger.info(f"消息匹配二次过滤关键词 '{keyword}'，将转存到文件夹ID: {folder_id}")
                                                reply_thread_pool.submit(send_message, f"消息匹配二次过滤关键词 '{keyword}'，将转存到文件夹ID: {folder_id}")
                                                break
                                except Exception as e:
                                    logger.error(f"解析二次过滤规则失败: {e}")
                                    reply_thread_pool.submit(send_message, f"解析二次过滤规则失败: {e}")
                            if target_url:                                
                                result = transfer_shared_link_optimize(client, target_url, transfer_id)
                                if result:
                                    status = "转存成功"
                                    result_msg = f"✅123云盘转存成功\n消息内容: {message_url}\n链接: {target_url}"
                                    reply_thread_pool.submit(send_message, result_msg)
                                else:                               
                                    status = "转存失败"
                                    result_msg = f"❌123云盘转存失败\n消息内容: {message_url}\n链接: {target_url}"
                                    reply_thread_pool.submit(send_message, result_msg)
                            else:
                                full_links = extract_123_links_from_full_text(message_text)
                                if full_links:
                                    for link in full_links:
                                        if parse_share_link(message_text, link, transfer_id, False):
                                            status = "转存成功"
                                            result_msg = f"✅123云盘秒传链接转存成功\n消息内容: {message_url}\n"
                                            reply_thread_pool.submit(send_message, result_msg)
                                        else:
                                            status = "转存失败"
                                            result_msg = f"❌123云盘秒传链接转存失败\n消息内容: {message_url}\n"  
                                            #notifier.send_message(result_msg)     
                                else:
                                    status = "转存失败"
                                    result_msg = f"❌123云盘秒传链接转存失败\n消息内容: {message_url}\n"  
                                    #notifier.send_message(result_msg)     
                            time.sleep(2)
                        save_message(message_id, date_str, message_url, target_url, status, result_msg)
                else:
                    logger.info("未发现新的123分享链接")

            if get_int_env("ENV_115_TGMONITOR_SWITCH", 0):
                            try:
                                # 确保导入了模块
                                from bot115 import tg_115monitor
                                tg_115monitor()
                            except Exception as e:
                                # [关键] 捕获异常，只打印日志，不让程序退出
                                logger.error(f"115监控任务出错 (已跳过，防止容器重启): {str(e)}")          
            
            if get_int_env("ENV_189_TGMONITOR_SWITCH", 0):
                try:
                    # 直接调用本文件定义的 tg_189monitor (上面那个全能版)
                    tg_189monitor(client189)
                except Exception as e:
                    logger.error(f"天翼云监控任务出错: {e}")
            
            logger.info(f"休息{CHECK_INTERVAL}分钟，当前版本 {version}...")
            
            try:
                next_time = datetime.now() + timedelta(minutes=CHECK_INTERVAL)
                logger.info(f"下次检查时间是：{next_time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                logger.error(f"计算下次检查时间出错: {e}")

            total_wait_seconds = CHECK_INTERVAL * 60
            elapsed_seconds = 0
            # 拆分等待时间，每1秒检查一次定时任务（20秒内会检查20次，满足20秒检查一次的需求）
            exit=0
            while elapsed_seconds < total_wait_seconds:
                # 检查是否需要退出（在休息前检查，确保只在记录日志后退出）
                try:
                    # 直接访问should_exit变量而不是通过globals()检查
                    with should_exit.get_lock():
                        if link_process_lock.acquire(blocking=False):
                            try:
                                if should_exit.value:
                                    logger.info("检测到退出标志，子进程将在休息前退出")
                                    exit=1
                                    break   
                            finally:
                                link_process_lock.release()
                except Exception as e:
                    logger.error(f"检查退出标志时发生错误: {str(e)}")
                time.sleep(1)  # 短间隔休眠，保证20秒内至少检查一次
                elapsed_seconds += 1
            if exit:
                break

    except KeyboardInterrupt:
        logger.info("程序已停止")
    except Exception as e:
        logger.error(f"程序异常终止: {str(e)}")
        #notifier.send_message(f"tgto123：程序异常终止: {str(e)}")

    
from ptto115 import ptto123process
def ptto123():
    while get_int_env("ENV_PTTO123_SWITCH", 0) or get_int_env("ENV_PTTO115_SWITCH", 0):
        try:
            ptto123process()
        except Exception as e:
            logger.error(f"ptto123线程异常终止: {str(e)}")
            bot.send_message(TG_ADMIN_USER_ID, f"ptto123线程异常终止: {str(e)}")
            time.sleep(300)

import threading
import multiprocessing
import signal

if __name__ == "__main__":
    # 设置全局默认模式为 spawn
    multiprocessing.set_start_method('spawn')
# 全局共享标志，用于通知子进程退出
should_exit = multiprocessing.Value('b', False)

# 子进程运行的函数
def run_main(exit_flag):
    # 将共享变量设置为全局变量，以便main函数可以访问
    global should_exit
    should_exit = exit_flag
    try:
        main()
    except Exception as e:
        logger.error(f"子进程运行异常: {str(e)}")

if __name__ == "__main__":
    # 检查db\user.env文件是否存在，如果不存在则从templete.env创建
    user_state_manager.clear_state(TG_ADMIN_USER_ID)
    user_env_path = os.path.join('db', 'user.env')
    if not os.path.exists(user_env_path):
        logger.info(f"user.env文件不存在，从templete.env创建...")
        # 确保db目录存在
        os.makedirs('db', exist_ok=True)
        # 复制templete.env到db目录并重命名为user.env
        if os.path.exists('templete.env'):
            shutil.copy2('templete.env', user_env_path)
            logger.info(f"成功创建user.env文件")
        else:
            logger.warning(f"警告: templete.env文件不存在，无法创建user.env")
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)

    while True:
        try:            
            # [修改] 构造按钮键盘并发送简洁消息
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📖 使用说明", callback_data="show_usage"),
                       InlineKeyboardButton("⚠️ 免责声明", callback_data="show_disclaimer"))
            markup.row(InlineKeyboardButton("🤖 人形命令", callback_data="show_userbot_help"),
                       InlineKeyboardButton("🌟 项目地址", url="https://t.me/xx123pan1"))
            
            # 发送简洁的启动消息
            bot.send_message(
                TG_ADMIN_USER_ID, 
                f"叮咚，我已成功启动，欢迎使用123bot！\n\n ═════当前版本❀{version}═════\n\n",
                parse_mode='HTML', 
                reply_markup=markup
            )
            break
            
        except Exception as e:
            logger.error(f"由于网络等原因无法与TG Bot建立通信，30秒后重试...: {str(e)}")
            time.sleep(30)

    # 主进程控制逻辑
    restart_time = time_datetime(3, 0, 0)  # 设置在每天下午6:50:00重启
    
    # 计算初始的下一次重启时间戳
    def calculate_next_restart_time():
        today = datetime.now().date()
        # 计算今天的重启时间时间戳
        today_restart_time = datetime.combine(today, restart_time).timestamp()
        # 当前时间戳
        now = datetime.now().timestamp()
        # 如果当前时间在今天的重启时间之前，则下一次重启时间为今天重启时间
        # 如果当前时间已过今天的重启时间，则下一次重启时间为明天重启时间
        if now < today_restart_time:
            next_restart = today_restart_time
        else:
            next_restart = datetime.combine(today + timedelta(days=1), restart_time).timestamp()
        return next_restart
    
    next_restart_time = calculate_next_restart_time()
    
    while True:
        try:
            # 创建并启动子进程，传递共享变量
            main_process = multiprocessing.Process(target=run_main, args=(should_exit,))
            main_process.daemon = False
            main_process.start()
            logger.info(f"子进程 {main_process.pid} 已启动")
            logger.info(f"下一次计划清理内存时间: {datetime.fromtimestamp(next_restart_time).strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 监控子进程和重启时间
            while main_process.is_alive():
                # 检查是否到达重启时间
                now = datetime.now().timestamp()
                
                if now >= next_restart_time:
                    # 设置退出标志，通知子进程
                    with should_exit.get_lock():
                        should_exit.value = True
                    
                    # 等待子进程退出，最多等待60秒
                    wait_time = 0
                    max_wait = 1800
                    while main_process.is_alive() and wait_time < max_wait:
                        time.sleep(1)
                        wait_time += 1
                    
                    # 如果子进程还在运行，跳过此次重启
                    if main_process.is_alive():
                        logger.warning(f"子进程 {main_process.pid} 未能在规定时间内自行退出,跳过此次重启")
                        with should_exit.get_lock():
                            should_exit.value = False
                        next_restart_time = calculate_next_restart_time()
                        logger.info(f"下一次计划清理内存时间: {datetime.fromtimestamp(next_restart_time).strftime('%Y-%m-%d %H:%M:%S')}")
                        continue

                    # 重置退出标志
                    with should_exit.get_lock():
                        should_exit.value = False                    
                    # 计算下一次重启时间
                    next_restart_time = calculate_next_restart_time()
                    logger.info(f"已完成清理内存，下一次计划清理内存时间: {datetime.fromtimestamp(next_restart_time).strftime('%Y-%m-%d %H:%M:%S')}")
                    break
                
                # 每10秒检查一次
                time.sleep(10)
            
            # 子进程退出后，等待一段时间再重启
            if not main_process.is_alive():
                logger.info(f"子进程 {main_process.pid} 已退出，等待5秒后重启")
                time.sleep(5)
            
        except KeyboardInterrupt:
            logger.info("接收到中断信号，正在终止子进程...")
            if 'main_process' in locals() and main_process.is_alive():
                try:
                    main_process.terminate()
                    main_process.join(timeout=10)
                except Exception as e:
                    logger.error(f"终止子进程时发生错误: {str(e)}")
            logger.info("程序已停止")
            break
