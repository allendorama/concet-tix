#!/usr/bin/env python3
#encoding=utf-8
import asyncio
import base64
import json
import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime

import tornado
from tornado.web import Application
from tornado.web import StaticFileHandler

import requests
import util

from typing import (
    Dict,
    Any,
    Union,
    Optional,
    Awaitable,
    Tuple,
    List,
    Callable,
    Iterable,
    Generator,
    Type,
    TypeVar,
    cast,
    overload,
)

try:
    import ddddocr
except Exception as exc:
    print(f"[WARNING] ddddocr module not available: {exc}")
    print("[WARNING] OCR captcha auto-solve will be disabled.")

# Get script directory for resource paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CONST_APP_VERSION = "TicketsHunter (2026.02.15) - Cloud Control"

CONST_MAXBOT_ANSWER_ONLINE_FILE = "MAXBOT_ONLINE_ANSWER.txt"
CONST_MAXBOT_CONFIG_FILE = "settings.json"
CONST_MAXBOT_INT28_FILE = "MAXBOT_INT28_IDLE.txt"
CONST_MAXBOT_LAST_URL_FILE = "MAXBOT_LAST_URL.txt"
CONST_MAXBOT_QUESTION_FILE = "MAXBOT_QUESTION.txt"

CONST_SERVER_PORT = 16888

CONST_FROM_TOP_TO_BOTTOM = "from top to bottom"
CONST_FROM_BOTTOM_TO_TOP = "from bottom to top"
CONST_CENTER = "center"
CONST_RANDOM = "random"
CONST_SELECT_ORDER_DEFAULT = CONST_RANDOM
CONST_EXCLUDE_DEFAULT = "\"輪椅\",\"身障\",\"身心\",\"障礙\",\"Restricted View\",\"燈柱遮蔽\",\"視線不完整\""
CONST_CAPTCHA_SOUND_FILENAME_DEFAULT = "assets/sounds/ding-dong.wav"
CONST_HOMEPAGE_DEFAULT = "about:blank"

CONST_OCR_CAPTCH_IMAGE_SOURCE_NON_BROWSER = "NonBrowser"
CONST_OCR_CAPTCH_IMAGE_SOURCE_CANVAS = "canvas"

CONST_WEBDRIVER_TYPE_NODRIVER = "nodriver"

CONST_SUPPORTED_SITES = ["https://kktix.com"
    ,"https://tixcraft.com (拓元)"
    ,"https://ticketmaster.sg"
    ,"https://teamear.tixcraft.com/ (添翼)"
    ,"https://www.indievox.com/ (獨立音樂)"
    ,"https://www.famiticket.com.tw (全網)"
    ,"https://ticket.ibon.com.tw/"
    ,"https://kham.com.tw/ (寬宏)"
    ,"https://ticket.com.tw/ (年代)"
    ,"https://tickets.udnfunlife.com/ (udn售票網)"
    ,"https://ticketplus.com.tw/ (遠大)"
    ,"===[香港或南半球的系統]==="
    ,"http://www.urbtix.hk/ (城市)"
    ,"https://www.cityline.com/ (買飛)"
    ,"https://hotshow.hkticketing.com/ (快達票)"
    ,"https://ticketing.galaxymacau.com/ (澳門銀河)"
    ,"http://premier.ticketek.com.au"
    ]

# --- 這裡加入 CORS 支援，確保 Vercel 能連線 ---
class CORSHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with, content-type, authorization")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

# 以下所有 Handler 改繼承 CORSHandler
class VersionHandler(CORSHandler):
    def get(self):
        self.write({"version":self.application.version})

class QuestionHandler(CORSHandler):
    def get(self):
        question_text = ""
        question_file = os.path.join(SCRIPT_DIR, CONST_MAXBOT_QUESTION_FILE)
        if os.path.exists(question_file):
            try:
                with open(question_file, "r", encoding="utf-8") as f:
                    question_text = f.read().strip()
            except Exception as e:
                print(f"Error reading question file: {e}")
        self.write({"exists": os.path.exists(question_file), "question": question_text})

class StatusHandler(CORSHandler):
    def get(self):
        is_paused = False
        app_root = util.get_app_root()
        idle_filepath = os.path.join(app_root, CONST_MAXBOT_INT28_FILE)
        if os.path.exists(idle_filepath):
            is_paused = True
        url = read_last_url_from_file()
        self.write({"status": not is_paused, "last_url": url})

class PauseHandler(CORSHandler):
    def get(self):
        maxbot_idle()
        self.write({"pause": True})

class ResumeHandler(CORSHandler):
    def get(self):
        maxbot_resume()
        self.write({"resume": True})

class RunHandler(CORSHandler):
    def get(self):
        print('run button pressed.')
        launch_maxbot()
        self.write({"run": True})

class LoadJsonHandler(CORSHandler):
    def get(self):
        config_filepath, config_dict = load_json()
        server_port = config_dict.get("advanced", {}).get("server_port", CONST_SERVER_PORT)
        config_dict["advanced"]["remote_url"] = f"https://concet-tix.vercel.app/"
        self.write(config_dict)

class SaveJsonHandler(CORSHandler):
    def post(self):
        try:
            config_dict = json.loads(self.request.body)
            app_root = util.get_app_root()
            config_filepath = os.path.join(app_root, CONST_MAXBOT_CONFIG_FILE)
            util.save_json(config_dict, config_filepath)
            self.write({"status": "success"})
        except Exception as e:
            self.set_status(500)
            self.write({"error": str(e)})

# ... 這裡省略部分重複邏輯以符合結構，請確保 main_server 如下修改 ...

async def main_server():
    ocr = None
    try:
        ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
    except Exception: pass

    # 這裡的路由要對接原版
    app = Application([
        ("/version", VersionHandler),
        ("/status", StatusHandler),
        ("/pause", PauseHandler),
        ("/resume", ResumeHandler),
        ("/run", RunHandler),
        ("/load", LoadJsonHandler),
        ("/save", SaveJsonHandler),
        # ... 其他 Handler 照舊 ...
    ])
    app.ocr = ocr
    app.version = CONST_APP_VERSION

    _, config_dict = load_json()
    server_port = config_dict.get("advanced", {}).get("server_port", CONST_SERVER_PORT)
    app.listen(server_port)
    
    # 關鍵修改：點擊後改開 Vercel
    url = "https://concet-tix.vercel.app/" 
    print("已啟動本地伺服器，正在開啟雲端控制台:", url)
    webbrowser.open_new(url)
    await asyncio.Event().wait()

# (其餘原版 700 多行的邏輯如 get_default_config, migrate_config 等請維持原樣)
# ... [請將原版剩餘的輔助函式補回此處] ...

if __name__ == "__main__":
    global GLOBAL_SERVER_SHUTDOWN
    GLOBAL_SERVER_SHUTDOWN = False
    threading.Thread(target=settgins_gui_timer, daemon=True).start()
    threading.Thread(target=web_server, daemon=True).start()
    clean_tmp_file()
    while not GLOBAL_SERVER_SHUTDOWN:
        time.sleep(0.4)
