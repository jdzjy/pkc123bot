#!/usr/bin/env python3
"""
Telegram 人形登录模块 - Web API适配版 (修复Session保存问题 & 增加持久化监听)
"""

import os
import sys
import asyncio
import logging
import shutil
from typing import Optional, Dict, Any
from pathlib import Path

# 引入 idle 用于维持连接
from pyrogram import Client, idle
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired,
    PhoneNumberInvalid, PhoneNumberBanned, FloodWait, ApiIdInvalid,
    AuthKeyDuplicated, UserDeactivated, AuthKeyInvalid
)

# 配置文件路径
TEMPLATE_ENV_PATH = 'templete.env'
ENV_FILE_PATH = os.path.join('db', 'user.env')

# 确保db目录存在
os.makedirs('db', exist_ok=True)

# 配置日志
# [修改] 将 Pyrogram 的日志级别设置为 WARNING，屏蔽 Web 端检查状态时的刷屏日志
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("tg_login")

class TelegramLogin:
    """Telegram 人形登录类 - API版"""
    
    def __init__(self, session_name: str = "default_session"):
        self.config = self.load_config_from_file()
        self.api_id = self.config.get('ENV_API_ID')
        self.api_hash = self.config.get('ENV_API_HASH')
        self.session_name = session_name
        
        self.db_dir = Path("db")
        self.db_dir.mkdir(exist_ok=True)
        self.session_path = str(self.db_dir / session_name)
        
        # 临时会话名称（用于登录过程，防止损坏现有会话）
        self.temp_session_name = f"{session_name}_temp"
        
        # 用于Web登录的临时客户端实例
        self.temp_client: Optional[Client] = None
        self.phone_code_hash: Optional[str] = None
        self.phone_number: Optional[str] = None

    def load_config_from_file(self) -> Dict[str, str]:
        config = {}
        target_file = ENV_FILE_PATH if os.path.exists(ENV_FILE_PATH) else TEMPLATE_ENV_PATH
        if os.path.exists(target_file):
            with open(target_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip().strip('"').strip("'")
        
        if 'ENV_API_ID' in config:
            try:
                config['ENV_API_ID'] = int(config['ENV_API_ID'])
            except:
                pass
        return config

    def get_session_file_path(self) -> str:
        return f"{self.session_path}.session"

    async def is_session_valid(self) -> bool:
        """检查正式会话是否有效"""
        if not os.path.exists(self.get_session_file_path()):
            return False
        
        # 使用临时客户端检查，避免占用锁
        client = Client(
            name=self.session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            workdir="db",
            in_memory=True # 尝试使用内存模式避免频繁IO
        )
        try:
            await client.connect()
            me = await client.get_me()
            await client.disconnect()
            return me is not None
        except Exception as e:
            # 这里的错误通常是正常的（比如被锁），不打印以减少干扰
            try:
                await client.disconnect()
            except:
                pass
            return False

    async def get_user_info(self) -> Dict[str, Any]:
        """获取用户信息 (Web端调用)"""
        # 先检查文件是否存在，避免无意义连接
        if not os.path.exists(self.get_session_file_path()):
             return {"status": "not_logged_in"}

        client = Client(
            name=self.session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            workdir="db"
        )
        try:
            await client.connect()
            me = await client.get_me()
            await client.disconnect()
            return {
                "status": "logged_in",
                "user_id": me.id,
                "first_name": me.first_name,
                "username": me.username,
                "phone": me.phone_number
            }
        except Exception:
            # 这里的异常可能是因为后台线程正在使用session文件（锁），这是正常的
            # 如果文件存在但无法读取，Web端显示未登录或出错即可，不影响后台运行
            return {"status": "error_or_locked"}

    # --- 新增：后台持久化运行方法 ---
    
    def start_userbot_listener(self, register_handlers_func):
        """
        启动持久化的 Userbot 监听 (阻塞式运行)
        :param register_handlers_func: 一个回调函数，接收 client 对象，用于注册消息处理器
        """
        if not os.path.exists(self.get_session_file_path()):
            logger.warning("❌ [人形模块] 无法启动：未找到会话文件。请先在 Web 页面登录。")
            return

        if not self.api_id or not self.api_hash:
            logger.warning("❌ [人形模块] 无法启动：缺少 API_ID 或 API_HASH。")
            return

        logger.info("🚀 [人形模块] 正在初始化后台客户端...")
        
        app = Client(
            name=self.session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            workdir="db"
        )

        # 调用外部传入的函数注册 handlers (-s123, -mc 等)
        if register_handlers_func:
            register_handlers_func(app)

        try:
            app.start()
            me = app.get_me()
            logger.info(f"✅ [人形模块] 已连接！当前用户: {me.first_name} (@{me.username})")
            logger.info("✅ [人形模块] 正在后台等待命令 (-s123 / -mc)...")
            
            # 核心修改：使用 idle() 保持连接持久化，直到进程结束
            idle()
            
            app.stop()
        except Exception as e:
            logger.error(f"❌ [人形模块] 运行出错: {e}")

    # --- Web 登录流程方法 (保持不变) ---

    async def api_step_1_send_code(self, phone: str) -> Dict[str, Any]:
        """Web登录第一步：发送验证码"""
        if self.temp_client:
            try:
                if self.temp_client.is_connected:
                    await self.temp_client.disconnect()
            except:
                pass

        temp_file = self.db_dir / f"{self.temp_session_name}.session"
        if temp_file.exists():
            try:
                os.remove(temp_file)
            except:
                pass

        self.temp_client = Client(
            name=self.temp_session_name,
            api_id=self.api_id,
            api_hash=self.api_hash,
            workdir="db"
        )
        
        self.phone_number = phone
        
        try:
            await self.temp_client.connect()
            sent_code = await self.temp_client.send_code(phone)
            self.phone_code_hash = sent_code.phone_code_hash
            return {"success": True, "message": "验证码已发送"}
        except FloodWait as e:
            await self._cleanup_temp()
            return {"success": False, "message": f"请求太频繁，请等待 {e.value} 秒"}
        except Exception as e:
            await self._cleanup_temp()
            return {"success": False, "message": str(e)}
    
    async def api_step_2_verify_code(self, code: str) -> Dict[str, Any]:
        """Web登录第二步：验证验证码"""
        if not self.temp_client:
            return {"success": False, "message": "会话已完全失效，请重新发送验证码"}
        
        if not self.temp_client.is_connected:
            try:
                await self.temp_client.connect()
            except Exception as e:
                return {"success": False, "message": f"重连失败: {e}"}
            
        try:
            await self.temp_client.sign_in(
                self.phone_number,
                self.phone_code_hash,
                code
            )
            await self._save_session_file()
            return {"success": True, "status": "logged_in", "message": "登录成功"}
            
        except SessionPasswordNeeded:
            return {"success": True, "status": "2fa_required", "message": "需要两步验证密码"}
        except (PhoneCodeInvalid, PhoneCodeExpired):
            return {"success": False, "message": "验证码无效或已过期"}
        except Exception as e:
            logger.error(f"验证失败: {e}")
            return {"success": False, "message": f"验证失败: {str(e)}"}

    async def api_step_3_password(self, password: str) -> Dict[str, Any]:
        """Web登录第三步：两步验证"""
        if not self.temp_client or not self.temp_client.is_connected:
            return {"success": False, "message": "会话超时"}
            
        try:
            await self.temp_client.check_password(password)
            await self._save_session_file()
            return {"success": True, "status": "logged_in", "message": "登录成功"}
        except Exception as e:
            return {"success": False, "message": f"密码错误: {str(e)}"}

    async def _save_session_file(self):
        try:
            if self.temp_client.is_connected:
                await self.temp_client.disconnect()
            
            self.temp_client = None
            
            temp_path = self.db_dir / f"{self.temp_session_name}.session"
            final_path = self.db_dir / f"{self.session_name}.session"
            
            if not temp_path.exists():
                raise FileNotFoundError("临时会话文件未生成")

            if final_path.exists():
                os.remove(final_path)
            
            shutil.move(str(temp_path), str(final_path))
            logger.info(f"会话文件已保存: {final_path}")
            
        except Exception as e:
            logger.error(f"保存会话文件失败: {e}")
            raise e

    async def _cleanup_temp(self):
        if self.temp_client:
            try:
                await self.temp_client.disconnect()
            except:
                pass
            self.temp_client = None
            
        temp_file = self.db_dir / f"{self.temp_session_name}.session"
        if temp_file.exists():
            try:
                os.remove(temp_file)
            except:
                pass

    async def logout(self):
        await self._cleanup_temp()
        path = self.get_session_file_path()
        if os.path.exists(path):
            os.remove(path)
            return True
        return False