import logging
logger = logging.getLogger(__name__)
import asyncio
import json
from quark import QuarkUcSDK
import base64
import time
import asyncio
import os
import re


class QuarkCookieError(Exception):
    pass

# 从分享URL中提取分享ID和密码
def extract_share_info_from_url(share_url):
    share_id_match = re.search(r'/s/([a-zA-Z0-9]+)', share_url)
    if not share_id_match:
        raise ValueError(f"无效的分享URL: {share_url}")
    share_id = share_id_match.group(1)
    password_match = re.search(r'pwd=([a-zA-Z0-9]+)', share_url)
    password = password_match.group(1) if password_match else ""
    return share_id, password

def sanitize_string(s: str) -> str:
    return s.encode('utf-8', errors='replace').decode('utf-8')

# [保持原有函数，虽然现在不使用了，但留着防止报错]
def should_skip_quark_file(filename):
    env_filter = os.getenv("ENV_EXT_FILTER", "")
    if not env_filter: return False
    skip_exts = [ext.strip().lower() for ext in env_filter.split(',') if ext.strip()]
    if not filename: return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in skip_exts

def export_share_info(share_url, cookie=""):
    json_data = {
            "usesBase62EtagsInExport": False,
            "files": [],
        }
    
    if not cookie:
        # [修改] 直接抛出异常，通知主程序
        raise QuarkCookieError("未配置 ENV_KUAKE_COOKIE，请填写 Cookie")

    async def main(batch_size: int = 50):
        start_time = time.time()
        my_cookie = cookie  
        try:
            code, password = extract_share_info_from_url(share_url)
            logger.info(f"从URL提取到分享ID: {code}，密码: {password if password else '无'}")
        except ValueError as e:
            logger.error(f"错误: {e}")
            return
        
        async with QuarkUcSDK(cookie=my_cookie) as quark:
            # 1. 获取分享信息
            share_info_result = await quark.get_share_info(code, password)
            logger.info("--- 正在获取分享信息 --- ")
            
            # [关键修改] 如果获取分享信息失败，大概率是 Cookie 失效或 IP 风控
            if share_info_result.get("code") != 0:
                err_msg = f"获取分享信息失败: {share_info_result.get('message')} (Code: {share_info_result.get('code')})"
                logger.error(err_msg)
                # 抛出异常，触发 Bot 通知
                raise QuarkCookieError(f"Cookie可能已失效或分享链接无效。API返回: {share_info_result.get('message')}")

            stoken = share_info_result["data"]["stoken"]
            
            # 2. 收集所有文件信息
            logger.info(f"--- 正在收集文件信息 --- ")
            
            files_needing_md5 = []
            file_mapping = {}
            
            async for file_info in quark.get_share_file_list(
                code=code,
                passcode=password,
                stoken=stoken,
                dir_id=0,
                is_get_folder=False,
                is_recursion=True,
            ):
                clean_path = sanitize_string(file_info["RootPath"].lstrip('/'))
                
                # [关键] 不过滤文件，全部交给主程序处理
                # if should_skip_quark_file(clean_path): continue
                
                file_base = {
                    "size": file_info["size"],
                    "path": clean_path,
                }
                
                origin_md5 = file_info.get("md5")
                
                if origin_md5 and isinstance(origin_md5, str) and len(origin_md5) == 32:
                    file_base["etag"] = origin_md5.lower()
                    json_data["files"].append(file_base)
                else:
                    file_mapping[file_info["fid"]] = file_base
                    files_needing_md5.append((file_info["fid"], file_info["share_fid_token"]))
                
            total_needing = len(files_needing_md5)
            total_found = len(json_data["files"])
            logger.info(f"--- 初步扫描: {total_found} 个文件已获MD5，{total_needing} 个需进一步请求 --- ")
            
            # 3. 批量获取剩余文件的MD5 (含重试机制)
            if total_needing > 0:
                for i in range(0, total_needing, batch_size):
                    batch_files = files_needing_md5[i : i + batch_size]
                    
                    retry_count = 3
                    md5_results = {}
                    
                    while retry_count > 0:
                        try:
                            md5_results = await quark.batch_send_create_share_download_request(
                                code=code,
                                pwd=password,
                                stoken=stoken,
                                file_info_list=batch_files,
                                batch_size=batch_size
                            )
                            if md5_results: break
                        except Exception as e:
                            logger.warning(f"获取MD5异常: {e}")
                        
                        retry_count -= 1
                        if retry_count > 0:
                            logger.info(f"网络波动，等待 2 秒后重试 (剩余 {retry_count} 次)...")
                            await asyncio.sleep(2)
                    
                    # [新增] 如果重试耗尽且完全没结果，可能也是 Cookie/风控 问题
                    if not md5_results:
                        logger.warning("⚠️ 本批次 MD5 获取完全失败，可能是接口风控")
                        # 这里可以选择是否抛出异常，或者继续尝试下一批
                        # 为了稳定性，暂时只记录警告，不中断整个任务
                    
                    # 处理结果
                    for fid, _ in batch_files:
                        file_base = file_mapping.get(fid)
                        if not file_base: continue

                        if fid in md5_results and md5_results[fid].get('md5'):
                            md5_info = md5_results[fid]
                            raw_md5 = md5_info['md5']
                            final_md5 = raw_md5
                            try:
                                if '==' in raw_md5: final_md5 = base64.b64decode(raw_md5).hex()
                            except Exception: pass
                                
                            file_base["etag"] = final_md5
                            json_data["files"].append(file_base)
                        else:
                            logger.warning(f"⚠️ 无法获取MD5: {file_base['path']}")
                            file_base["etag"] = "" 
                            json_data["files"].append(file_base)
                        
            logger.info(f"--- 信息收集完成，共 {len(json_data['files'])} 个文件 ---")
        
        end_time = time.time()
        logger.info(f"总耗时: {end_time - start_time:.2f} 秒")
        
    asyncio.run(main())
    return json_data

# 如果直接运行此脚本
if __name__ == "__main__":
    share_url = "https://pan.quark.cn/s/c094a3711bcc"
    cookie = "_qk_bx_ck_v1=eyJkZXZpY2VJZCI6ImVDeSNBQU9vVDZndkhOTzBOL1paNlBEcjEvL1B6cWxTRU5tSXBCRkVKakthaEczdmVDMzhQbVNXaVNlUy9wTXFtSnAyUFU0PSIsImRldmljZUZpbmdlcnByaW50IjoiYzE0NWNkY2U1ZTYyODUwMWU3NDMwYTAyZTY3YjhiNGYifQ==; b-user-id=9929ebb9-0dc2-5ed5-abac-6b84b193e8c9; __wpkreporterwid_=d13832ca-d23d-4242-96fc-5d4cc2fe78b7; _UP_A4A_11_=wb9cb17952bb43fe8b4f3695eff09cdd; b-user-id=9929ebb9-0dc2-5ed5-abac-6b84b193e8c9; ctoken=MF6J0Q81r_ijS0nNy6i8Rxdr; web-grey-id=80f1ce41-95a4-4e83-a08b-df6951fbac96; web-grey-id.sig=EIB_ia64X9AP-Nyd-aSj3klEUTZRz8B_sR_JC3G_8YY; grey-id=e04a0571-d3fd-b80e-2759-bce0e9ca17d9; grey-id.sig=M9UApHT-QexIN6gtYxrXESFrsEMUmgfUTu7CUGukAlc; isQuark=true; isQuark.sig=hUgqObykqFom5Y09bll94T1sS9abT1X-4Df_lzgl8nM; __sdid=AAR18dAzGeXddKEvUjPHmcnz76Iom8plLlP7zUd/BcOr0W5CEDTkwiy0ocATiu28duDuKHQXVnPkAGXKvZHnXydoIwOL48AMq7fK99aF46dx1w==; _UP_D_=pc; xlly_s=1; __chkey=; __pus=1a099988568d7709539e6d50835cbdd7AASEqIoKZbQx6jCw49mNdNcecnB54KyEXwt24Ow1+NN5ytPT051rMt4Q95RottoHhdZeLZkN9keENVjrHQY5QOSM; __kp=9e9940c0-949f-11f0-bd58-8bb2451e1ac6; __kps=AARQDre99j4kWTEzt1WZFgeD; __ktd=eaaqz0znDaxM+jVdRG78ug==; __uid=AARQDre99j4kWTEzt1WZFgeD; isg=BM_PCpzo-wqyf__Fe3VclXrRXmPZ9CMW4vdHhOHZTD5FsOSy6MQUZtvjsuAOyPuO; tfstk=g46jDU2l2q0jeg1pGdrrNmYrfhps5uyeHctOxGHqXKpAXd_Wznl4iCz1NNQykxJvMhMRWNgxMrcxCd_eSEpNgE-OPGQYmhrcC_D1xGX4mdrDnivMByzULRscmdVeisFYYLhJvgK9X7RA-NgneyzUL8Px2dab8N73hqAJjUKvXCKYVQKMDdK9DdEWyhtn6qQ9BuZWbHH9XIKO2LK2XdLOWdE52Ux6BnQ9BusJrhhky4taGhIbv7MyRKoucaYSBABW2PYCc-k2A9-XGeIAhADgvnOXJiL7kX0hBQIM1OmiCCsAtNxdkqUeiGC5Pn9_UjpdV1QBqteEl3fV2M8RADHdvKt69ddSXAIWnUARepeKP3fR01BclcM9mtWe1eA7XAAwe9Rd9ZigxgpvXNAhQyDDkGIhK6JQUjpdV1QC1g7ZLe9TvfiWtAtW8uZSsfX3B_avmz-A7IKkDJr7V4GMM3xW8uZSsfAvqnCUVugSs; __puus=df4074814eb2c70631be5ab02bf2a9b2AARpAPoHtOuWl5F5UVWt6nL6nBUMVsUw9Go4NYcEZJzE2P7xx4JeJ8YhweFptj29Cex6g+vTIBJCrp2XYticR3b3104076oq1M3YOiydk9hZBntbeSUiT2Fu1Hu85i6FspPc0VnxlH6i5Cu9sU3F1axhMq03GAtGs/nKQiKVIfw/H+HGkiHMqCERIbKJxSf6dFYM1tzjzfx3VK5A/freUU3W"
    print(export_share_info(share_url, cookie))
