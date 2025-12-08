import json
import time
import requests
from urllib import parse
from concurrent.futures import ThreadPoolExecutor
import threading
from Crypto.Cipher import PKCS1_v1_5 as Cipher_pksc1_v1_5
from Crypto.PublicKey import RSA
import logging
import argparse
from tqdm import tqdm
import os
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlsplit, parse_qs
import re
import schedule
from dotenv import load_dotenv

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
        logger.warning(f"环境变量 {env_name} 值不是有效的整数，使用默认值 {default_value}")
        return default_value

CHANNEL_URL = os.getenv("ENV_189_TG_CHANNEL", "")
ENV_189_TG_CHANNEL = os.getenv("ENV_189_TG_CHANNEL", "")
ENV_189_CLIENT_ID = os.getenv("ENV_189_CLIENT_ID", "")
ENV_189_CLIENT_SECRET = os.getenv("ENV_189_CLIENT_SECRET", "")
ENV_189_UPLOAD_PID = os.getenv("ENV_189_UPLOAD_PID", "")
ENV_189_COOKIES = os.getenv("ENV_189_COOKIES", "")

TG_BOT_TOKEN = os.getenv("ENV_TG_BOT_TOKEN", "")
TG_ADMIN_USER_ID = get_int_env("ENV_TG_ADMIN_USER_ID", 0)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

DB_DIR = "db"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)
DATABASE_FILE = os.path.join(DB_DIR, "TG_monitor-189.db")
CHECK_INTERVAL = get_int_env("ENV_CHECK_INTERVAL", 5)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
]
RETRY_TIMES = 3
TIMEOUT = 15

# PC User-Agent (用于API交互)
PC_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def rsaEncrpt(password, public_key):
    rsakey = RSA.importKey(public_key)
    cipher = Cipher_pksc1_v1_5.new(rsakey)
    return cipher.encrypt(password.encode()).hex()

def clean_filename(name):
    illegal_chars = '"\\/:*?|><'
    for char in illegal_chars:
        name = name.replace(char, '')
    return name[:255]

class BatchSaveTask:
    def __init__(self, shareInfo, batchSize, targetFolderId, shareFolderId=None, maxWorkers=3):
        self.shareInfo = shareInfo
        self.batchSize = batchSize
        self.shareFolderId = shareFolderId
        self.targetFolderId = targetFolderId
        self.tqLock = threading.Lock()
        self.taskNum = 0
        self.walkDirNum = 0
        self.saveDirNum = 0
        self.failed = False
        self.error_msg = ""  # [新增] 用于存储具体的错误原因
        self.threadPool = ThreadPoolExecutor(max_workers=maxWorkers)
        self.tq = tqdm(desc='正在保存')

    def __updateTq(self, num=1):
        data = {
            "剩余任务数": self.taskNum,
            "已保存目录数:": self.saveDirNum,
            "已遍历目录数:": self.walkDirNum
        }
        if num:
            self.tq.set_postfix(data, refresh=False)
            self.tq.update(num)
        else:
            self.tq.set_postfix(data)

    def __incTaskNum(self, num):
        self.tqLock.acquire()
        self.taskNum += num
        self.__updateTq(0)
        self.tqLock.release()

    def getTaskNum(self):
        self.tqLock.acquire()
        num = self.taskNum
        self.tqLock.release()
        return num

    def __incWalkDirNum(self, num=1):
        self.tqLock.acquire()
        self.walkDirNum += num
        self.__updateTq(num)
        self.tqLock.release()

    def __incSaveDirNum(self, num=1):
        self.tqLock.acquire()
        self.saveDirNum += num
        self.__updateTq(num)
        self.tqLock.release()

    def run(self, checkInterval=1):
        with self.tq:
            self.__incTaskNum(1)
            self.threadPool.submit(self.__batchSave, self.targetFolderId, self.shareFolderId)
            while self.getTaskNum() > 0:
                time.sleep(checkInterval)
            self.threadPool.shutdown()
        # [修改] 返回元组 (是否成功, 错误信息)
        return not self.failed, self.error_msg

    def __testAndSaveDir(self, folderInfo, targetFolderId):
        try:
            folderName = folderInfo["name"]
            shareFolderId = folderInfo["id"]
            clean_folder_name = clean_filename(folderName)
            code = self.shareInfo.saveShareFiles([{
                "fileId": shareFolderId,
                "fileName": clean_folder_name,
                "isFolder": 1}],
                targetFolderId)
            if code:
                if code == "ShareDumpFileOverload":
                    try:
                        nextFolderId = self.shareInfo.client.createFolder(parentFolderId=targetFolderId,
                                                                          name=folderName)
                        if nextFolderId:
                            self.__incTaskNum(1)
                            self.threadPool.submit(self.__batchSave, nextFolderId, shareFolderId)
                            return
                        else:
                            self.error_msg = f"创建文件夹失败: {folderName}"
                            log.error(f"failed to create folder[{folderInfo}] at [{targetFolderId}]")
                            self.failed = True
                    except Exception as e1:
                        self.error_msg = f"创建文件夹异常: {e1}"
                        log.error(f"failed to create folder[{folderInfo}] at [{targetFolderId}]: {e1}")
                        self.failed = True
                else:
                    # [新增] 空间不足判断
                    if code == "InsufficientStorageSpace":
                        self.error_msg = "❌ 天翼云盘空间不足"
                    else:
                        self.error_msg = f"保存目录失败 Code: {code}"
                    
                    log.error(f"save dir response error: {code}")
                    self.failed = True
            else:
                self.__incSaveDirNum()
        except Exception as e2:
            self.error_msg = f"处理目录异常: {e2}"
            log.error(f"TestAndSaveDir occurred exception: {e2}")
            self.failed = True
        finally:
            self.__incTaskNum(-1)

    def __mustSave(self, saveFiles, targetFolderId):
        try:
            taskInfos = []
            for fileInfo in saveFiles:
                taskInfos.append(
                    {
                            "fileId": fileInfo.get("id"),
                            "fileName": clean_filename(fileInfo.get("name")),
                            "isFolder": 0
                        }
                )
            code = self.shareInfo.saveShareFiles(taskInfos, targetFolderId)
            if code:
                # [新增] 空间不足判断
                if code == "InsufficientStorageSpace":
                    self.error_msg = "❌ 天翼云盘空间不足"
                else:
                    self.error_msg = f"保存文件失败 Code: {code}"
                
                log.error(f"save only files response error [num={len(saveFiles)}][code: {code}]")
                self.failed = True
        except Exception as e1:
            self.error_msg = f"保存文件异常: {e1}"
            log.error(f"mustSave occurred exception: {e1}")
            self.failed = True
        finally:
            self.__incTaskNum(-1)

    def __splitFileListAndSave(self, fileList: list, targetFolderId):
        for i in range(0, len(fileList), self.batchSize):
            if self.failed:
                return
            self.__incTaskNum(1)
            self.threadPool.submit(self.__mustSave, fileList[i: i + self.batchSize], targetFolderId)

    def __batchSave(self, targetFolderId, shareFolderId: None):
        try:
            rootFiles = self.shareInfo.getAllShareFiles(shareFolderId)
            self.__incWalkDirNum()
            
            files = rootFiles.get("files", [])
            folders = rootFiles.get("folders", [])
            
            self.__splitFileListAndSave(files, targetFolderId)

            for folderInfo in folders:
                if self.failed:
                    return
                self.__incTaskNum(1)
                self.threadPool.submit(self.__testAndSaveDir, folderInfo, targetFolderId)
            return
        except Exception as e1:
            self.error_msg = f"遍历目录异常: {e1}"
            log.error(f"batchSave occurred exception: {e1}")
        finally:
            self.__incTaskNum(-1)
        self.failed = True


class Cloud189ShareInfo:
    # [修改] 增加 shareCode 和 shareName 参数
    def __init__(self, shareDirFileId, shareId, shareMode, cloud189Client, accessCode="", shareName="", shareCode=""):
        self.shareDirFileId = shareDirFileId
        self.shareId = shareId
        self.session = cloud189Client.session
        self.client = cloud189Client
        self.shareMode = shareMode
        self.accessCode = accessCode 
        self.shareName = shareName # 存储文件夹名
        self.shareCode = shareCode #

    def getAllShareFiles(self, folder_id=None):
        if folder_id is None:
            folder_id = self.shareDirFileId
        fileList = []
        folders = []
        pageNumber = 1
        
        while True:
            # 使用原始 shareCode 构造 Referer
            referer_code = getattr(self, 'shareCode', None) or self.shareId
            
            custom_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json;charset=UTF-8",
                "Referer": f"https://cloud.189.cn/web/share.html?code={referer_code}",
                "Origin": "https://cloud.189.cn",
                "Host": "cloud.189.cn"
            }

            params = {
                "pageNum": pageNumber,
                "pageSize": "10000",
                "fileId": folder_id,
                "shareDirFileId": self.shareDirFileId,
                "isFolder": "true",
                "shareId": self.shareId,
                "iconOption": "5",
                "orderBy": "lastOpTime",
                "descending": "true",
                "accessCode": self.accessCode
            }
            
            if self.shareMode is not None:
                params["shareMode"] = self.shareMode

            response = self.session.get(
                "https://cloud.189.cn/api/open/share/listShareDir.action", 
                headers=custom_headers, 
                params=params
            )
            
            result = self.client._parse_json(response)
            
            # 自动重试机制
            if result.get('res_code') != 0 and "shareMode" in params:
                del params["shareMode"]
                response = self.session.get(
                    "https://cloud.189.cn/api/open/share/listShareDir.action", 
                    headers=custom_headers, 
                    params=params
                )
                result = self.client._parse_json(response)

            if result.get('res_code') is None:
                log.error(f"🛑【调试信息】API响应异常，完整内容: {result}")
            
            if result.get('res_code') != 0:
                error_msg = result.get('res_message', 'Unknown Error')
                log.error(f"获取文件列表失败: {error_msg}")
            
            if not isinstance(result.get("fileListAO"), dict):
                error_info = f"Invalid fileListAO format: {result}"
                log.error(error_info)
                raise Exception(error_info) 
            
            fileListAO = result["fileListAO"]

            current_files = fileListAO.get("fileList", [])
            current_folders = fileListAO.get("folderList", [])
            
            if fileListAO.get("fileListSize", 0) == 0 and len(current_folders) == 0:
                break
            
            fileList += current_files
            folders += current_folders
            pageNumber += 1
            
            if pageNumber > 1000:
                break
                
        return {"files": fileList, "folders": folders}

    def saveShareFiles(self, tasksInfos, targetFolderId):
        try:
            # saveShareFiles 不需要 accessCode，它是基于 taskId 的操作
            response = self.session.post("https://cloud.189.cn/api/open/batch/createBatchTask.action", data={
                "type": "SHARE_SAVE",
                "taskInfos": str(tasksInfos),
                "targetFolderId": targetFolderId,
                "shareId": self.shareId,
            })
            if response.status_code != 200:
                log.error(f"保存文件请求失败，状态码: {response.status_code}")
                return f"HTTP_ERROR_{response.status_code}"
            
            if not response.content.strip():
                log.error("保存文件请求返回空响应")
                return "EMPTY_RESPONSE"
            
            result = self.client._parse_json(response)

            if result.get("res_code") != 0:
                log.error(f"保存文件失败: {result.get('res_message', '未知错误')}")
                return result.get('res_message', 'UNKNOWN_ERROR')
            
            taskId = result["taskId"]
            
            # 轮询检查任务状态
            while True:
                response = self.session.post("https://cloud.189.cn/api/open/batch/checkBatchTask.action", data={
                    "taskId": taskId,
                    "type": "SHARE_SAVE"
                })
                result = self.client._parse_json(response)

                taskStatus = result.get("taskStatus")
                errorCode = result.get("errorCode")
                # taskStatus: 4=成功, 3=处理中? (需根据实际抓包调整，通常4是完成)
                # 原代码逻辑是 !=3 就退出，这里保持原样，如有问题再调整
                if taskStatus != 3 or errorCode:
                    break
                time.sleep(1)
            
            return errorCode # 如果errorCode存在则返回，否则返回None表示成功
            
        except Exception as e:
            log.error(f"保存文件时发生异常: {e}")
            return f"EXCEPTION: {str(e)}"

    def createBatchSaveTask(self, targetFolderId, batchSize, shareFolderId=None, maxWorkers=3):
        return BatchSaveTask(shareInfo=self, batchSize=batchSize, targetFolderId=targetFolderId,
                             shareFolderId=shareFolderId, maxWorkers=maxWorkers)


class Cloud189:
    def __init__(self):
        self.session = requests.session()
        # 初始化时使用 PC User-Agent
        self.session.headers = {
            'User-Agent': PC_USER_AGENT,
            "Accept": "application/json;charset=UTF-8",
        }
        # 尝试加载 ENV_189_COOKIES
        if ENV_189_COOKIES:
            self.load_cookies_from_str(ENV_189_COOKIES)

    def _parse_json(self, response):
        try:
            return response.json()
        except Exception:
            try:
                # 处理 BOM
                text = response.content.decode('utf-8-sig').strip()
                if not text:
                    return {"res_code": -1, "res_message": "Empty response"}
                return json.loads(text)
            except Exception as e:
                if "<html" in response.text.lower() or "<title>" in response.text.lower():
                    logger.debug(f"API返回了HTML而非JSON，可能是请求头被拒绝或Cookie失效: {response.text[:200]}")
                    return {"res_code": -1, "res_message": "Server returned HTML instead of JSON (Request Rejected)"}
                logger.error(f"JSON解析失败: {str(e)} | URL: {response.url}")
                return {"res_code": -1, "res_message": f"JSON Parse Error: {str(e)}"}

    def load_cookies_from_str(self, cookie_str):
        try:
            cookie_dict = {}
            for item in cookie_str.split(';'):
                if '=' in item:
                    k, v = item.strip().split('=', 1)
                    cookie_dict[k] = v
            self.session.cookies.update(cookie_dict)
            return True
        except Exception as e:
            log.error(f"加载Cookie失败: {e}")
            return False

    # 检查 Cookie 是否有效
    def check_cookie_valid(self):
        try:
            response = self.session.get("https://cloud.189.cn/api/open/file/listFiles.action", params={
                "folderId": -11, "pageNum": 1, "pageSize": 1
            })
            res = self._parse_json(response)
            if res.get('res_code') == 0:
                return True
            return False
        except:
            return False

    # 账号密码登录 (RSA Flow)
    def login(self, username, password):
        # 登录前再次检查 Cookie，如果有效直接返回
        if self.check_cookie_valid():
            logger.info("天翼云盘Cookie 有效，跳过账号密码登录")
            return True

        notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
        try:
            # 1. 获取公钥
            encryptKey = self.getEncrypt()
            
            # 2. 获取登录参数
            formData = self.getLoginFormData(username, password, encryptKey)
            
            data = {
                "appKey": 'cloud',
                "version": '2.0',
                "accountType": '01',
                "mailSuffix": '@189.cn',
                "validateCode": '',
                "returnUrl": formData['returnUrl'],
                "paramId": formData['paramId'],
                "captchaToken": '',
                "dynamicCheck": 'FALSE',
                "clientType": '1',
                "cb_SaveName": '0',
                "isOauth2": "false",
                "userName": formData['userName'],
                "password": formData['password'],
            }
            
            headers = {
                'User-Agent': PC_USER_AGENT,
                'Referer': 'https://open.e.189.cn/',
                'lt': formData['lt'],
                'REQID': formData['REQID'],
            }
            
            # 3. 提交登录
            response = self.session.post('https://open.e.189.cn/api/logbox/oauth2/loginSubmit.do', data=data, headers=headers)
            result = self._parse_json(response)

            if result.get('result') == 0:
                # 4. 跳转以设置完整 Cookie
                self.session.get(result['toUrl'], headers={
                    "Referer": 'https://m.cloud.189.cn/zhuanti/2016/sign/index.jsp?albumBackupOpened=1',
                    'Accept-Encoding': 'gzip, deflate',
                    "Host": 'cloud.189.cn',
                })
                logger.info("账号密码登录成功")
                return True
            else:
                msg = result.get('msg', 'Unknown Error')
                logger.error(f"天翼云盘账号密码登录失败: {msg}")
                notifier.send_message(f"天翼云盘登录失败，原因：{msg}")
                return False
        except Exception as e:
            logger.error(f"账号密码登录异常: {e}")
            return False
        

    def getEncrypt(self):
        response = self.session.post("https://open.e.189.cn/api/logbox/config/encryptConf.do", data={
            'appId': 'cloud'
        })
        result = self._parse_json(response)
        return result.get('data', {}).get('pubKey')

    def getRedirectURL(self):
        headers = {
            'User-Agent': PC_USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Connection': 'keep-alive'
        }
        rsp = self.session.get(
            'https://cloud.189.cn/api/portal/loginUrl.action?redirectURL=https://cloud.189.cn/web/redirect.html?returnURL=/main.action',
            headers=headers
        )
        if rsp.status_code == 200:
            return parse.parse_qs(parse.urlparse(rsp.url).query)
        else:
            raise Exception(f"status code must be 200, but real is {rsp.status_code}")

    def getLoginFormData(self, username, password, encryptKey):
        query = self.getRedirectURL()
        headers = {
            'User-Agent': PC_USER_AGENT,
            "Referer": 'https://open.e.189.cn/',
            "lt": query["lt"][0],
            "REQID": query["reqId"][0],
        }
        response = self.session.post('https://open.e.189.cn/api/logbox/oauth2/appConf.do', data={
            "version": '2.0',
            "appKey": 'cloud',
        }, headers=headers)
        
        resData = self._parse_json(response)

        if resData.get('result') == '0':
            keyData = f"-----BEGIN PUBLIC KEY-----\n{encryptKey}\n-----END PUBLIC KEY-----"
            usernameEncrypt = rsaEncrpt(username, keyData)
            passwordEncrypt = rsaEncrpt(password, keyData)
            return {
                "returnUrl": resData['data']['returnUrl'],
                "paramId": resData['data']['paramId'],
                "lt": query['lt'][0],
                "REQID": query['reqId'][0],
                "userName": f"{{NRP}}{usernameEncrypt}",
                "password": f"{{NRP}}{passwordEncrypt}",
            }
        else:
            raise Exception(resData.get("msg", "Failed to get login form data"))

    def getObjectFolderNodes(self, folderId=-11):
        response = self.session.post("https://cloud.189.cn/api/portal/getObjectFolderNodes.action", data={
            "id": folderId,
            "orderBy": 1,
            "order": "ASC"
        })
        return self._parse_json(response)

    def list_files(self, folder_id: str = "-11") -> dict:
        try:
            response = self.session.get(
                "https://cloud.189.cn/api/open/file/listFiles.action",
                params={
                    "folderId": folder_id,
                    "mediaType": 0,
                    "orderBy": "lastOpTime",
                    "descending": True,
                    "pageNum": 1,
                    "pageSize": 1000
                }
            )
            return self._parse_json(response)
        except Exception as e:
            log.error(f"获取文件列表时发生异常: {e}")
            return {}
            
    def delete_files(self, file_ids: list) -> dict:
        try:
            task_params = {
                "type": "DELETE",
                "taskInfos": str(file_ids),
                "targetFolderId": "",
            }
            response = self.session.post(
                "https://cloud.189.cn/api/open/batch/createBatchTask.action",
                data=task_params
            )
            result = self._parse_json(response)
            if result.get("res_code") != 0:
                return {"success": False, "message": f"删除失败: {result.get('res_message')}"}
            
            task_id = result.get("taskId")
            if not task_id:
                return {"success": False, "message": "未返回taskId"}
            
            start_time = time.time()
            max_timeout = 30
            
            while True:
                if time.time() - start_time > max_timeout:
                    return {"success": False, "message": "任务执行超时", "task_id": task_id}
                
                status_response = self.session.post(
                    "https://cloud.189.cn/api/open/batch/checkBatchTask.action",
                    data={"taskId": task_id, "type": "DELETE"}
                )
                status_result = self._parse_json(status_response)

                if status_result.get("res_code") != 0:
                    time.sleep(1)
                    continue
                
                task_status = status_result.get("taskStatus")
                if task_status == 4:
                    return {"success": True, "message": "删除成功", "task_id": task_id}
                elif task_status in [1, 3]:
                    time.sleep(1)
                else:
                    return {"success": False, "message": f"任务状态异常 {task_status}", "task_id": task_id}
        except Exception as e:
            return {"success": False, "message": f"删除异常: {str(e)}"}
            
    def delete_folder_contents(self, folder_id: str) -> dict:
        try:
            log.info(f"开始删除文件夹 {folder_id} 下的所有内容")
            files_result = self.list_files(folder_id)
            if not files_result or not files_result.get("fileListAO"):
                return {"success": True, "message": "文件夹为空或获取失败"}
            
            file_list = files_result["fileListAO"].get("fileList", [])
            folder_list = files_result["fileListAO"].get("folderList", [])
            task_infos = []
            
            for file in file_list:
                if "id" not in file: continue
                task_infos.append({"fileId": file["id"], "fileName": file.get("fileName", "file"), "isFolder": 0})
            
            for folder in folder_list:
                if "id" not in folder: continue
                task_infos.append({"fileId": folder["id"], "fileName": folder.get("fileName", "folder"), "isFolder": 1})
            
            if not task_infos:
                return {"success": True, "message": "无内容删除"}
            
            return self.delete_files(task_infos)
        except Exception as e:
            return {"success": False, "message": f"异常: {str(e)}"}
        

    # [新增方法] 递归清理指定目录下的空文件夹
    def delete_empty_folders(self, folder_id):
        """
        递归删除指定文件夹下的所有空文件夹（从最底层向上清理）
        """
        log.info(f"开始清理文件夹[{folder_id}]下的空目录...")
        
        # 1. 获取所有文件夹列表
        all_folders = []
        folder_queue = [folder_id]
        
        # 广度优先遍历获取所有子文件夹ID
        while folder_queue:
            curr = folder_queue.pop(0)
            try:
                # 只获取文件夹列表
                response = self.session.get(
                    "https://cloud.189.cn/api/open/file/listFiles.action",
                    params={"folderId": curr, "mediaType": 0, "pageNum": 1, "pageSize": 1000}, # 假设单层文件夹不超过1000
                    timeout=10
                )
                res = self._parse_json(response)
                
                folders = res.get("fileListAO", {}).get("folderList", [])
                for f in folders:
                    fid = f.get("id") or f.get("fileId")
                    if fid:
                        all_folders.append(fid)
                        folder_queue.append(fid)
                time.sleep(0.1)
            except Exception as e:
                log.error(f"扫描子文件夹失败: {e}")

        # 2. 倒序排列（从最深层开始删）
        # 由于我们是BFS获取的，列表后面的通常是深层的，倒序即可
        all_folders.reverse()
        
        deleted_count = 0
        
        # 3. 逐个检查并删除
        for fid in all_folders:
            try:
                # 检查该文件夹是否为空（既无文件也无子文件夹）
                response = self.session.get(
                    "https://cloud.189.cn/api/open/file/listFiles.action",
                    params={"folderId": fid, "mediaType": 0, "pageNum": 1, "pageSize": 1},
                    timeout=10
                )
                res = self._parse_json(response)
                count = res.get("fileListAO", {}).get("count", 0)
                
                if count == 0:
                    # 执行删除
                    self.delete_files([{"fileId": fid, "fileName": "empty_dir", "isFolder": 1}])
                    deleted_count += 1
                    # log.info(f"已删除空文件夹: {fid}")
                    time.sleep(0.2) # 避免太快
            except Exception as e:
                log.error(f"清理文件夹{fid}异常: {e}")
                
        log.info(f"空文件夹清理完成，共删除 {deleted_count} 个目录")
        return deleted_count

    def get_folder_files_for_transfer(self, folder_id):
        """
        递归获取指定文件夹下的所有文件信息（含MD5）
        兼容各种字段名缺失的情况
        """
        all_files = []
        
        # 待扫描的文件夹队列 (初始放入根目录ID)
        folder_queue = [(folder_id, "/")]
        
        scanned_folders = 0
        MAX_SCANNED_FOLDERS = 500 

        while folder_queue:
            if scanned_folders >= MAX_SCANNED_FOLDERS:
                log.warning(f"扫描达到最大文件夹限制 ({MAX_SCANNED_FOLDERS})，停止扫描剩余目录")
                break
                
            current_id, current_path = folder_queue.pop(0)
            scanned_folders += 1
            
            page_num = 1
            page_size = 200
            
            try:
                while True:
                    response = self.session.get(
                        "https://cloud.189.cn/api/open/file/listFiles.action",
                        params={
                            "folderId": current_id,
                            "mediaType": 0,
                            "orderBy": "lastOpTime",
                            "descending": True,
                            "pageNum": page_num,
                            "pageSize": page_size
                        },
                        timeout=15
                    )
                    res = self._parse_json(response)
                    
                    if res.get("res_code") != 0:
                        log.error(f"获取天翼云目录[{current_path}]失败: {res.get('res_message')}")
                        break

                    file_list_ao = res.get("fileListAO", {})
                    current_file_list = file_list_ao.get("fileList", [])
                    current_folder_list = file_list_ao.get("folderList", [])

                    # --- 处理文件 ---
                    if current_file_list:
                        for file in current_file_list:
                            # 必须确保有MD5值
                            if "md5" in file and file["md5"]:
                                # [全面防御] 对所有字段使用 .get() 
                                f_name = file.get("fileName") or file.get("name") or "Unknown_File"
                                # 尝试获取大小，如果都没有则默认为 0
                                f_size = file.get("fileSize") or file.get("size") or 0
                                f_id = file.get("id") or file.get("fileId")
                                
                                if f_id: # 只有当ID存在时才添加
                                    all_files.append({
                                        "file_id": f_id,
                                        "file_name": f_name,
                                        "file_size": f_size,
                                        "md5": file["md5"].lower(),
                                        "parent_path": current_path
                                    })

                    # --- 处理文件夹 ---
                    if page_num == 1 and current_folder_list:
                        for folder in current_folder_list:
                            # 文件夹通常使用 'name' 字段
                            folder_name = folder.get("name") or folder.get("fileName") or "Unknown_Folder"
                            folder_id = folder.get("id") or folder.get("fileId")
                            
                            if folder_id:
                                sub_path = f"{current_path}{folder_name}/"
                                folder_queue.append((folder_id, sub_path))

                    # 翻页判断
                    current_page_count = len(current_file_list) + len(current_folder_list)
                    if current_page_count < page_size:
                        break
                    
                    page_num += 1
                    time.sleep(0.2)
                    
            except Exception as e:
                log.error(f"遍历天翼云目录[{current_path}]异常: {str(e)}")
        
        log.info(f"天翼云扫描结束: 共扫描 {scanned_folders} 个目录，发现 {len(all_files)} 个有效文件")
        return all_files


    def getShareInfo(self, link):
        url = parse.urlparse(link)
        query_params = parse.parse_qs(url.query)
        
        access_code = query_params.get('accessCode', [''])[0]

        try:
            if "code" in query_params:
                code = query_params["code"][0]
            else:
                path_parts = url.path.split('/')
                if len(path_parts) >= 3 and path_parts[1] == 't':
                    code = path_parts[2]
                else:
                    code = path_parts[-1]
        except (KeyError, IndexError):
             raise Exception("无法从分享链接中提取分享码")
        
        # 定义变量存储真实的数字 shareId
        numeric_share_id = None

        # === 1. 优先通过验证接口获取 numeric_share_id ===
        if access_code:
            try:
                check_url = "https://cloud.189.cn/api/open/share/checkAccessCode.action"
                check_headers = {
                    "User-Agent": PC_USER_AGENT,
                    "Referer": f"https://cloud.189.cn/web/share.html?code={code}",
                    "Host": "cloud.189.cn"
                }
                check_params = {
                    "shareCode": code,
                    "accessCode": access_code
                }
                
                check_res = self.session.get(check_url, params=check_params, headers=check_headers)
                check_data = self._parse_json(check_res)
                
                # [核心修复] 从验证结果中提取 shareId
                # 成功时通常返回: {"res_code": 0, "shareId": 123456789, ...}
                if check_data.get("res_code") == 0 and "shareId" in check_data:
                    numeric_share_id = check_data["shareId"]
                    log.info(f"访问码验证成功，获取到数字 shareId: {numeric_share_id}")
                else:
                    log.warning(f"访问码验证未返回 shareId: {check_data}")
                    
            except Exception as e:
                log.warning(f"访问码验证请求异常: {e}")

        # === 2. 获取详细信息 ===
        api_params = {
            "shareCode": code
        }
        if access_code:
            api_params["accessCode"] = access_code

        response = self.session.get("https://cloud.189.cn/api/open/share/getShareInfoByCodeV2.action", params=api_params)
        result = self._parse_json(response)

        if result.get('res_code') != 0:
            raise Exception(f"获取分享信息失败: {result.get('res_message', '未知错误')} (Code: {result.get('res_code')})")

        # 优先使用 checkAccessCode 返回的 id，其次用 info 返回的，最后才兜底用 code (但这步会导致 InternalError)
        real_share_id = numeric_share_id if numeric_share_id else result.get("shareId", code)
        
        real_file_id = result.get("fileId")
        real_share_mode = result.get("shareMode", 1)
        real_share_name = result.get("fileName", "天翼分享")

        if not real_file_id:
             # 尝试容错：如果是文件分享，可能 info 里没有 fileId
             # 但对于文件夹转存，没有 fileId 是致命的
             if "fileListAO" in result and result["fileListAO"].get("fileList"):
                 # 这是一个纯文件分享，根目录可能是虚拟的
                 real_file_id = 0 # 或者其他标识
             else:
                 pass 
                 # raise Exception(f"API返回数据异常，未找到文件ID(fileId)。API响应: {result}")
            
        return Cloud189ShareInfo(
            shareId=real_share_id, # 这里必须是数字！
            shareDirFileId=real_file_id,
            cloud189Client=self,
            shareMode=real_share_mode,
            accessCode=access_code,
            shareName=real_share_name,
            shareCode=code # 这里是字符串
        )

    def createFolderFromShareLink(self, link, parentFolderId):
        try:
            url = parse.urlparse(link)
            try:
                code = parse.parse_qs(url.query)["code"][0]
            except (KeyError, IndexError):
                path_parts = url.path.split('/')
                if len(path_parts) >= 3 and path_parts[1] == 't':
                    code = path_parts[2]
                else:
                    raise Exception("无法从分享链接中提取分享码")
            
            response = self.session.get("https://cloud.189.cn/api/open/share/getShareInfoByCodeV2.action", params={
                "shareCode": code
            })
            result = self._parse_json(response)

            if result.get('res_code') != 0:
                log.error(f"获取分享信息失败: {result.get('res_message', '未知错误')}")
                return None
            
            fileName = result['fileName']
            cleaned_fileName = clean_filename(fileName) + " " + time.strftime("[%m%d%H%M%S]")
            folderId = self.createFolder(cleaned_fileName, parentFolderId)
            return folderId
        except Exception as e:
            log.error(f"从分享链接创建文件夹时发生异常: {e}")
            return None

    def createFolder(self, name, parentFolderId=-11):
        response = self.session.post("https://cloud.189.cn/api/open/file/createFolder.action", data={
            "parentFolderId": parentFolderId,
            "folderName": name,
        })
        result = self._parse_json(response)

        if result.get("res_code") != 0:
            raise Exception(result.get("res_message"))
        return result["id"]

    def empty_recycle_bin(self):
        try:
            response = self.session.post("https://cloud.189.cn/api/open/batch/createBatchTask.action", data={
                "type": "EMPTY_RECYCLE",
                "taskInfos": "[]",
                "targetFolderId": "",
            })
            if response.status_code != 200:
                return False
            
            result = self._parse_json(response)
            if result.get("res_code") != 0:
                log.error(f"清空回收站失败: {result.get('res_message', '未知错误')}")
                return False
            
            log.info("清空回收站成功")
            return True
        except Exception as e:
            log.error(f"清空回收站时发生异常: {e}")
            return False


def getArgs():
    parser = argparse.ArgumentParser(description="天翼云盘保存分享文件(无单次转存上限)")
    parser.add_argument('-l', help='分享链接', required=True)
    return parser.parse_args()


def save_189_link(client : Cloud189, link, parentFolderId):
    notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
    log.info("正在获取文件分享信息...")
    info = None
    try:
        info = client.getShareInfo(link)
    except Exception as e:
        log.error(f"获取分享信息出现错误: {e}")
        notifier.send_message(f"获取分享信息出现错误: {e}")
        return False
    log.info("正在检查并创建目录...")
    saveDir = None
    try:
        saveDir = client.createFolderFromShareLink(link,parentFolderId)
    except Exception as e:
        log.error(f"检查并创建目录出现错误: {e}")
        notifier.send_message(f"检查并创建目录出现错误: {e}")
        return False
    if not saveDir:
        log.error("无法获取保存目录信息，请检查天翼账号登录情况")
        notifier.send_message(f"无法获取保存目录信息，请检查天翼账号登录情况")
        return False
    else:
        log.info("开始转储分享文件...")
        
        # [修改] 接收元组返回值 (success, msg)
        success, error_msg = info.createBatchSaveTask(saveDir, 500, maxWorkers=5).run()
        
        if success:
            log.info("所有分享文件已保存.")
            return True
        else:
            # [修改] 使用具体的错误信息
            final_msg = f"保存分享文件失败: {error_msg}" if error_msg else "保存分享文件出现未知错误"
            log.error(final_msg)
            notifier.send_message(final_msg)
            return False
        
# === [新增] 递归获取分享链接中的所有文件信息（只读不存） ===
def get_share_file_snapshot(client: Cloud189, link):
    """
    递归提取分享链接中的所有文件元数据(MD5, Size, Name)
    返回: (file_list, root_folder_name)
    """
    try:
        # 1. 获取分享基本信息
        share_info = client.getShareInfo(link)
        # [新增] 获取根目录名
        root_folder_name = share_info.shareName 
        
        all_files = []
        # 待扫描的文件夹队列 (folder_id, relative_path)
        # 根目录 folder_id 使用 shareInfo 中的 shareDirFileId
        queue = [(share_info.shareDirFileId, "/")]
        
        # 限制扫描数量防止超时
        max_scan_folders = 200
        scanned_count = 0
        
        while queue:
            if scanned_count > max_scan_folders:
                logger.warning(f"分享链接文件夹过多(>{max_scan_folders})，停止扫描")
                break
                
            curr_id, curr_path = queue.pop(0)
            scanned_count += 1
            
            # 获取当前目录内容
            data = share_info.getAllShareFiles(curr_id)
            
            # 处理文件
            for f in data.get('files', []):
                # 必须有MD5
                if f.get('md5'):
                    all_files.append({
                        "name": f.get('name'),
                        "size": int(f.get('size', 0)),
                        "md5": f.get('md5').lower(),
                        "path": curr_path + f.get('name') # 完整相对路径
                    })
            
            # 处理文件夹 (加入队列继续扫描)
            for d in data.get('folders', []):
                sub_path = curr_path + d.get('name') + "/"
                queue.append((d.get('id'), sub_path))
                
            time.sleep(0.1) # 避免请求过快
            
        return all_files, root_folder_name
        
    except Exception as e:
        logger.error(f"提取分享快照失败: {e}")
        return None, None      

def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS messages
                 (msg_id INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, date TEXT, message_url TEXT, target_url TEXT, 
                   transfer_status TEXT, transfer_time TEXT, transfer_result TEXT)''')
    conn.commit()
    conn.close()

class TelegramNotifier:
    def __init__(self, bot_token, user_id):
        self.bot_token = bot_token
        self.user_id = user_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/" if self.bot_token else None

    def send_message(self, message):
        max_retries = 3
        if not self.bot_token: return False
        
        # [修改] 纯文本模式
        params = {"chat_id": self.user_id, "text": message}
        for attempt in range(max_retries):
            try:
                requests.get(f"{self.base_url}sendMessage", params=params, timeout=15)
                return True
            except:
                time.sleep(2)
        return False

def is_message_processed(message_url):
    conn = sqlite3.connect(DATABASE_FILE)
    result = conn.execute("SELECT 1 FROM messages WHERE message_url = ?", (message_url,)).fetchone()
    conn.close()
    return result is not None

def save_message(message_id, date, message_url, target_url, status, result):
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        conn.execute("INSERT INTO messages (id, date, message_url, target_url, transfer_status, transfer_time, transfer_result) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (message_id, date, message_url, target_url, status, datetime.now().isoformat(), result))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.execute("UPDATE messages SET transfer_status=?, transfer_result=?, transfer_time=? WHERE id=?",
                     (status, result, datetime.now().isoformat(), message_id))
        conn.commit()
    finally:
        conn.close()

def get_latest_messages():
    try:
        channel_urls = os.getenv("ENV_189_TG_CHANNEL", "").split('|')
        if not channel_urls or channel_urls == ['']: return []
        
        all_new_messages = []
        for channel_url in channel_urls:
            if not channel_url.strip(): continue
            if channel_url.startswith('https://t.me/') and '/s/' not in channel_url:
                channel_url = f'https://t.me/s/{channel_url.split("https://t.me/")[-1]}'

            session = requests.Session()
            retry = Retry(total=RETRY_TIMES, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
            session.mount("https://", HTTPAdapter(max_retries=retry))
            headers = {"User-Agent": USER_AGENTS[int(time.time()) % len(USER_AGENTS)]}
            response = session.get(channel_url, headers=headers, timeout=TIMEOUT)
            soup = BeautifulSoup(response.text, 'html.parser')
            message_divs = soup.find_all('div', class_='tgme_widget_message')

            for i in range(len(message_divs)):
                msg = message_divs[len(message_divs) - 1 - i]
                data_post = msg.get('data-post', '')
                message_id = data_post.split('/')[-1] if data_post else f"未知_{i}"
                
                link_elem = msg.find('a', class_='tgme_widget_message_date')
                message_url = f"{link_elem.get('href').lstrip('/')}" if link_elem else ''
                text_elem = msg.find('div', class_='tgme_widget_message_text')

                if text_elem:
                    message_text = text_elem.get_text(strip=True).replace('\n', ' ')
                    target_urls = extract_target_url(f"{msg}")
                    for url in target_urls:
                        if not is_message_processed(message_url):
                            all_new_messages.append((message_id, datetime.now().isoformat(), message_url, url, message_text))
                            
        return sorted(all_new_messages, key=lambda x: x[1])
    except:
        return []

def extract_target_url(text):
    # 1. 匹配标准分享链接
    pattern = r'https?:\/\/cloud\.189\.cn\/(?:t\/\w+|web\/share\?code=\w+)'
    links = re.findall(pattern, text, re.IGNORECASE)
    unique_links = list(set([match.strip() for match in links]))
    # 2. 提取访问码/提取码
    code_pattern = r'(?:访问码|提取码)\s*[:：]\s*([a-zA-Z0-9]+)'
    code_match = re.search(code_pattern, text)
    access_code = code_match.group(1) if code_match else None

    final_links = []
    for link in unique_links:
        if not link.startswith("http"):
            link = f"https://cloud.189.cn/{link.lstrip('/')}"
        
        # 拼接到 URL 参数中
        if access_code:
            separator = "&" if "?" in link else "?"
            link = f"{link}{separator}accessCode={access_code}"
            
        final_links.append(link)
        
    return final_links

def tg_189monitor(client):
    init_database()
    notifier = TelegramNotifier(TG_BOT_TOKEN, TG_ADMIN_USER_ID)
    logger.info("===== 开始检查 天翼网盘监控 =====")
    new_messages = get_latest_messages()
    
    for msg in new_messages:
        message_id, date_str, message_url, target_url, message_text = msg
        logger.info(f"处理新消息: {target_url}")
        
        result = save_189_link(client, target_url, ENV_189_UPLOAD_PID)
        
        # [修改] 极简通知格式
        if result:
            status = "转存成功"
            result_msg = (
                f"✅天翼云盘转存成功\n"
                f"消息内容: {message_url}\n"
                f"链接: {target_url}"
            )
        else:
            status = "转存失败"
            result_msg = (
                f"❌天翼云盘转存失败\n"
                f"消息内容: {message_url}\n"
                f"链接: {target_url}"
            )
            
        notifier.send_message(result_msg)
        save_message(message_id, date_str, message_url, target_url, status, result_msg)

if __name__ == '__main__':
    client = Cloud189()
    login_success = False

    # 1. 优先尝试 Cookie 登录
    if client.check_cookie_valid():
        logger.info("天翼云盘Cookie 有效，登录成功")
        login_success = True
    
    # 2. 如果 Cookie 无效，且配置了账号密码，尝试账号密码登录
    elif ENV_189_CLIENT_ID and ENV_189_CLIENT_SECRET:
        try:
            logger.info("天翼云盘Cookie 无效或未配置，尝试账号密码登录...")
            if client.login(ENV_189_CLIENT_ID, ENV_189_CLIENT_SECRET):
                login_success = True
            else:
                logger.warning("账号密码登录失败，请检查账号密码或验证码拦截")
        except Exception as e:
            logger.error(f"登录过程异常: {e}")
    
    if not login_success:
        logger.error("所有登录方式均失败，请在 Web 端手动输入 Cookie")
        exit(-1)
            
    info = client.getShareInfo("https://cloud.189.cn/t/NZzmYrQjMb6z")
    info = client.getShareInfo("https://cloud.189.cn/t/ZzyYfmeE3uIb")
    logger.info(info)
    save_189_link(client, "https://cloud.189.cn/t/NZzmYrQjMb6z", 923961206742226023)
    exit(-1)
