#!/usr/bin/env python3
"""
Duino-Coin Official PC Miner 4.3 - STANDARD LIBRARY VERSION
Only uses colorama and psutil as external libraries
Removed: requests, cpuinfo, pypresence, pip auto-install
"""

import sys
import os
import json
import socket
import time
import hashlib
import threading
import multiprocessing
import subprocess
import urllib.request
import urllib.parse
import random
import platform
import locale
import configparser
import io
import base64
import signal
from datetime import datetime
from pathlib import Path
import re

# ==================== EXTERNAL LIBRARIES (KEPT) ====================
try:
    from colorama import Back, Fore, Style, init
    init(autoreset=True)
except ImportError:
    # Fallback if colorama not available
    class Fore:
        RED = YELLOW = GREEN = BLUE = CYAN = MAGENTA = WHITE = RESET = ''
        BLACK = LIGHTBLACK_EX = LIGHTRED_EX = LIGHTCYAN_EX = ''
    class Back:
        RED = YELLOW = GREEN = BLUE = CYAN = MAGENTA = WHITE = RESET = ''
    class Style:
        BRIGHT = NORMAL = DIM = RESET_ALL = ''

try:
    import psutil
except ImportError:
    psutil = None
    print("Warning: psutil not available. Some features disabled.")

# ==================== SETTINGS ====================
class Settings:
    ENCODING = "UTF8"
    SEPARATOR = ","
    VER = 4.3
    DATA_DIR = "Duino-Coin PC Miner " + str(VER)
    TRANSLATIONS_URL = "https://raw.githubusercontent.com/revoxhere/duino-coin/master/Resources/PC_Miner_langs.json"
    TRANSLATIONS_FILE = "/Translations.json"
    SETTINGS_FILE = "/Settings.cfg"
    SOC_TIMEOUT = 10
    REPORT_TIME = 300
    
    try:
        BLOCK = " ‖ "
        "‖".encode(sys.stdout.encoding)
    except:
        BLOCK = " | "
    PICK = ""
    COG = " @"
    if os.name != "nt" or (os.name == "nt" and os.environ.get("WT_SESSION")):
        try:
            "⛏ ⚙".encode(sys.stdout.encoding)
            PICK = " ⛏"
            COG = " ⚙"
        except:
            pass

# ==================== GLOBALS ====================
debug = "n"
running_on_rpi = False
configparser = configparser.ConfigParser()
printlock = threading.Lock()
lang_file = {}
lang = "english"

# ==================== UTILITY FUNCTIONS ====================
def now():
    return datetime.now()

def get_string(string_name):
    if string_name in lang_file.get(lang, {}):
        return lang_file[lang][string_name]
    elif string_name in lang_file.get("english", {}):
        return lang_file["english"][string_name]
    return string_name

def pretty_print(msg=None, state="success", sender="sys0", print_queue=None):
    if sender.startswith("net"):
        bg_color = Back.BLUE
    elif sender.startswith("cpu"):
        bg_color = Back.YELLOW
    else:
        bg_color = Back.GREEN
    
    if state == "success":
        fg_color = Fore.GREEN
    elif state == "info":
        fg_color = Fore.BLUE
    elif state == "error":
        fg_color = Fore.RED
    else:
        fg_color = Fore.YELLOW
    
    output = (Fore.WHITE + datetime.now().strftime("%H:%M:%S ") + 
              Style.RESET_ALL + Style.BRIGHT + bg_color + " " + sender + " " +
              Style.NORMAL + Back.RESET + " " + fg_color + (msg or "").strip())
    
    if print_queue is not None:
        print_queue.append(output)
    else:
        print(output)

def get_prefix(symbol, val, accuracy):
    if val >= 1_000_000_000_000:
        return str(round(val / 1_000_000_000_000, accuracy)) + " T" + symbol
    elif val >= 1_000_000_000:
        return str(round(val / 1_000_000_000, accuracy)) + " G" + symbol
    elif val >= 1_000_000:
        return str(round(val / 1_000_000, accuracy)) + " M" + symbol
    elif val >= 1_000:
        return str(round(val / 1_000)) + " k" + symbol
    return str(round(val)) + " " + symbol

def format_hashrate(hr):
    return get_prefix("H/s", hr, 2)

def calculate_uptime(start_time):
    uptime = time.time() - start_time
    if uptime >= 7200:
        return str(int(uptime // 3600)) + get_string('uptime_hours')
    elif uptime >= 3600:
        return str(int(uptime // 3600)) + get_string('uptime_hour')
    elif uptime >= 120:
        return str(int(uptime // 60)) + get_string('uptime_minutes')
    elif uptime >= 60:
        return str(int(uptime // 60)) + get_string('uptime_minute')
    return str(round(uptime)) + get_string('uptime_seconds')

# ==================== SIMPLE HTTP REQUEST (no requests lib) ====================
def http_get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        raise Exception(f"HTTP request failed: {e}")

def http_get_json(url, timeout=10):
    return json.loads(http_get(url, timeout))

# ==================== ALGORITHMS ====================
class Algorithms:
    @staticmethod
    def DUCOS1(last_h, exp_h, diff, eff):
        time_start = time.time_ns()
        base_hash = hashlib.sha1(last_h.encode('ascii'))
        
        for nonce in range(100 * diff + 1):
            temp_h = base_hash.copy()
            temp_h.update(str(nonce).encode('ascii'))
            d_res = temp_h.hexdigest()
            
            if eff != 0 and nonce % 5000 == 0:
                time.sleep(eff / 100)
            
            if d_res == exp_h:
                time_elapsed = time.time_ns() - time_start
                if time_elapsed > 0:
                    hashrate = 1e9 * nonce / time_elapsed
                else:
                    return [nonce, 0]
                return [nonce, hashrate]
        
        return [0, 0]

# ==================== CLIENT (SOCKET) ====================
class Client:
    s = None
    
    @classmethod
    def connect(cls, pool):
        cls.s = socket.socket()
        cls.s.settimeout(Settings.SOC_TIMEOUT)
        cls.s.connect(pool)
    
    @classmethod
    def send(cls, msg):
        return cls.s.sendall(str(msg).encode(Settings.ENCODING))
    
    @classmethod
    def recv(cls, limit=128):
        return cls.s.recv(limit).decode(Settings.ENCODING).rstrip("\n")
    
    @classmethod
    def fetch_pool(cls):
        retry_count = 1
        while True:
            try:
                pretty_print(get_string("connection_search"), "info", "net0")
                data = http_get_json("https://server.duinocoin.com/getPool", Settings.SOC_TIMEOUT)
                
                if data.get("success"):
                    pretty_print(get_string("connecting_node") + data.get("name", ""), "info", "net0")
                    return (data["ip"], data["port"])
                else:
                    pretty_print(f"Warning: {data.get('message', 'Unknown error')}, retrying in {retry_count*2}s", "warning", "net0")
            except Exception as e:
                pretty_print(f"Node picker error: {e}, retrying in {retry_count*2}s", "error", "net0")
            
            time.sleep(retry_count * 2)
            retry_count = min(retry_count + 1, 60)

# ==================== CONFIGURATION ====================
def get_rpi_temperature():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return round(int(f.read().strip()) / 1000, 2)
    except:
        return 0

def has_mining_key(username):
    try:
        data = http_get_json(f"https://server.duinocoin.com/mining_key?u={username}", 10)
        return data.get("has_key", False)
    except:
        return False

def check_mining_key(user_settings):
    try:
        if user_settings.get("mining_key", "None") != "None":
            key = '&k=' + urllib.parse.quote(base64.b64decode(user_settings["mining_key"]).decode('utf-8'))
        else:
            key = ''
        
        response = http_get_json(f"https://server.duinocoin.com/mining_key?u={user_settings['username']}{key}", Settings.SOC_TIMEOUT)
        
        if response.get("success") and not response.get("has_key"):
            user_settings["mining_key"] = "None"
            with open(Settings.DATA_DIR + Settings.SETTINGS_FILE, "w") as f:
                configparser.write(f)
            return
        
        if not response.get("success") and user_settings.get("mining_key") == "None":
            pretty_print(get_string("mining_key_required"), "warning")
            mining_key = input("\t\t" + get_string("ask_mining_key") + Style.BRIGHT + Fore.YELLOW)
            if not mining_key:
                mining_key = "None"
            user_settings["mining_key"] = base64.b64encode(mining_key.encode('utf-8')).decode('utf-8')
            with open(Settings.DATA_DIR + Settings.SETTINGS_FILE, "w") as f:
                configparser.write(f)
            check_mining_key(user_settings)
    except Exception as e:
        pretty_print(f"Error checking mining key: {e}", "error")

def load_translations():
    global lang_file, lang
    trans_file = Settings.DATA_DIR + Settings.TRANSLATIONS_FILE
    
    if not Path(trans_file).is_file():
        try:
            content = http_get(Settings.TRANSLATIONS_URL, Settings.SOC_TIMEOUT)
            with open(trans_file, "wb") as f:
                f.write(content.encode('utf-8'))
        except:
            pass
    
    try:
        with open(trans_file, "r", encoding=Settings.ENCODING) as f:
            lang_file = json.load(f)
    except:
        lang_file = {"english": {}}
    
    # Detect language
    try:
        if Path(Settings.DATA_DIR + Settings.SETTINGS_FILE).is_file():
            configparser.read(Settings.DATA_DIR + Settings.SETTINGS_FILE)
            lang = configparser["PC Miner"].get("language", "english")
        else:
            loc = locale.getdefaultlocale()[0] or ""
            if loc.startswith("es"):
                lang = "spanish"
            elif loc.startswith("pl"):
                lang = "polish"
            elif loc.startswith("fr"):
                lang = "french"
            elif loc.startswith("ru"):
                lang = "russian"
            elif loc.startswith("de"):
                lang = "german"
            elif loc.startswith("zh"):
                lang = "chinese_simplified"
            else:
                lang = "english"
    except:
        lang = "english"

def load_config():
    global configparser
    config_file = Settings.DATA_DIR + Settings.SETTINGS_FILE
    
    if not Path(config_file).is_file():
        print(Style.BRIGHT + get_string("basic_config_tool") + Settings.DATA_DIR)
        print(Style.RESET_ALL + get_string("dont_have_account") + Fore.YELLOW + get_string("wallet") + Fore.RESET)
        
        # Get username
        while True:
            username = input(get_string("ask_username") + Style.BRIGHT).strip()
            if not username:
                username = random.choice(["revox", "Bilaboz"])
            try:
                r = http_get_json(f"https://server.duinocoin.com/users/{username}", Settings.SOC_TIMEOUT)
                if r.get("success"):
                    break
                print(get_string("incorrect_username"))
            except:
                break
        
        # Get mining key
        mining_key = "None"
        if has_mining_key(username):
            mk = input(Style.RESET_ALL + get_string("ask_mining_key") + Style.BRIGHT).strip()
            if mk:
                mining_key = base64.b64encode(mk.encode('utf-8')).decode('utf-8')
        
        # Get intensity
        intensity = input(Style.NORMAL + get_string("ask_intensity") + Style.BRIGHT).strip()
        intensity = re.sub(r"\D", "", intensity)
        if not intensity:
            intensity = 95
        intensity = max(1, min(100, int(intensity)))
        
        # Get threads
        threads = input(Style.NORMAL + get_string("ask_threads") + str(multiprocessing.cpu_count()) + "): " + Style.BRIGHT).strip()
        threads = re.sub(r"\D", "", threads)
        if not threads:
            threads = multiprocessing.cpu_count()
        threads = max(1, min(16, int(threads)))
        
        # Get difficulty
        print(Style.BRIGHT + "1" + Style.NORMAL + " - " + get_string("low_diff"))
        print(Style.BRIGHT + "2" + Style.NORMAL + " - " + get_string("medium_diff"))
        print(Style.BRIGHT + "3" + Style.NORMAL + " - " + get_string("net_diff"))
        diff = input(Style.NORMAL + get_string("ask_difficulty") + Style.BRIGHT).strip()
        if diff == "1":
            start_diff = "LOW"
        elif diff == "3":
            start_diff = "NET"
        else:
            start_diff = "MEDIUM"
        
        # Get rig ID
        rig_id = input(Style.NORMAL + get_string("ask_rig_identifier") + Style.BRIGHT).strip()
        if rig_id.lower() == "y":
            rig_id = input(Style.NORMAL + get_string("ask_rig_name") + Style.BRIGHT).strip()
        else:
            rig_id = "None"
        
        # Get donation level
        donation = input(Style.NORMAL + get_string('ask_donation_level') + Style.BRIGHT).strip()
        donation = re.sub(r'\D', '', donation)
        if not donation:
            donation = 1
        donation = max(0, min(5, int(donation)))
        
        configparser["PC Miner"] = {
            "username": username,
            "mining_key": mining_key,
            "intensity": str(intensity),
            "threads": str(threads),
            "start_diff": start_diff,
            "donate": str(donation),
            "identifier": rig_id,
            "algorithm": "DUCO-S1",
            "language": lang,
            "soc_timeout": str(Settings.SOC_TIMEOUT),
            "report_sec": str(Settings.REPORT_TIME),
            "raspi_leds": "y",
            "raspi_cpu_iot": "y",
            "discord_rp": "n"
        }
        
        with open(config_file, "w") as f:
            configparser.write(f)
        print(Style.RESET_ALL + get_string("config_saved"))
    
    configparser.read(config_file)
    return configparser["PC Miner"]

# ==================== MINER CORE ====================
def share_print(id, share_type, accept, reject, thread_hr, total_hr, 
                computetime, diff, ping, back_color, reject_cause=None, print_queue=None):
    thread_hr_str = get_prefix("H/s", thread_hr, 2)
    total_hr_str = get_prefix("H/s", total_hr, 1)
    diff_str = get_prefix("", int(diff), 0)
    
    if share_type == "accept":
        share_str = get_string("accepted")
        fg_color = Fore.GREEN
    elif share_type == "block":
        share_str = get_string("block_found")
        fg_color = Fore.YELLOW
    else:
        share_str = get_string("rejected")
        if reject_cause:
            share_str += f"{Style.NORMAL}({reject_cause}) "
        fg_color = Fore.RED
    
    output = (Fore.WHITE + datetime.now().strftime("%H:%M:%S ") +
              Style.RESET_ALL + Fore.WHITE + Style.BRIGHT + back_color +
              f" cpu{id} " + Back.RESET + fg_color + Settings.PICK +
              share_str + Fore.RESET + f"{accept}/{(accept + reject)}" +
              Fore.YELLOW + f" ({(round(accept / max(1, accept + reject) * 100))}%)" +
              Style.NORMAL + Fore.RESET +
              f" ∙ {computetime:.1f}s" +
              Style.NORMAL + " ∙ " + Fore.BLUE + Style.BRIGHT +
              f"{thread_hr_str}" + Style.DIM +
              f" ({total_hr_str} {get_string('hashrate_total')})" + Fore.RESET + Style.NORMAL +
              Settings.COG + f" {get_string('diff')} {diff_str} ∙ " + Fore.CYAN +
              f"ping {int(ping)}ms")
    
    if print_queue is not None:
        print_queue.append(output)
    else:
        print(output)

def print_queue_handler(print_queue):
    while True:
        if print_queue:
            with printlock:
                print(print_queue.pop(0))
        time.sleep(0.01)

def mining_thread(id, user_settings, blocks, pool, accept, reject, hashrate, single_miner_id, print_queue):
    pretty_print(get_string("mining_thread") + str(id) + get_string("mining_thread_starting") + 
                 Style.NORMAL + Fore.RESET + get_string("using_algo") + Fore.YELLOW +
                 str(user_settings["intensity"]) + "% " + get_string("efficiency"),
                 "success", "sys"+str(id), print_queue=print_queue)
    
    last_report = time.time()
    last_shares = 0
    
    while True:
        try:
            # Connect
            Client.connect(pool)
            if id == 0:
                Client.send("MOTD")
                motd = Client.recv(512)
                pretty_print(get_string("motd") + Fore.RESET + Style.NORMAL + str(motd), "success", "net0", print_queue)
            
            # Main mining loop
            while True:
                try:
                    # Get key
                    if user_settings.get("mining_key", "None") != "None":
                        key = base64.b64decode(user_settings["mining_key"]).decode('utf-8')
                    else:
                        key = "None"
                    
                    # Get job
                    while True:
                        Client.send(f"JOB,{user_settings['username']},{user_settings['start_diff']},{key}")
                        job = Client.recv().split(Settings.SEPARATOR)
                        if len(job) == 3:
                            break
                        pretty_print(f"Node message: {job}", "warning", print_queue=print_queue)
                        time.sleep(3)
                    
                    # Mining
                    while True:
                        time_start = time.time()
                        back_color = Back.YELLOW
                        
                        # Efficiency setting
                        eff_setting = int(user_settings["intensity"])
                        if eff_setting >= 90:
                            eff = 0.005
                        elif eff_setting >= 70:
                            eff = 0.1
                        elif eff_setting >= 50:
                            eff = 0.8
                        elif eff_setting >= 30:
                            eff = 1.8
                        else:
                            eff = 3
                        
                        result = Algorithms.DUCOS1(job[0], job[1], int(job[2]), eff)
                        computetime = time.time() - time_start
                        
                        hashrate[id] = result[1]
                        total_hashrate = sum(hashrate.values()) if hashrate else result[1]
                        
                        # Send solution
                        while True:
                            Client.send(f"{result[0]},{result[1]},Official PC Miner {Settings.VER},"
                                       f"{user_settings['identifier']},,{single_miner_id}")
                            
                            ping_start = time.time()
                            feedback = Client.recv().split(Settings.SEPARATOR)
                            ping = (time.time() - ping_start) * 1000
                            
                            if feedback[0] == "GOOD":
                                accept.value += 1
                                share_print(id, "accept", accept.value, reject.value,
                                           hashrate[id], total_hashrate, computetime,
                                           job[2], ping, back_color, print_queue=print_queue)
                            elif feedback[0] == "BLOCK":
                                accept.value += 1
                                blocks.value += 1
                                share_print(id, "block", accept.value, reject.value,
                                           hashrate[id], total_hashrate, computetime,
                                           job[2], ping, back_color, print_queue=print_queue)
                            elif feedback[0] == "BAD":
                                reject.value += 1
                                share_print(id, "reject", accept.value, reject.value,
                                           hashrate[id], total_hashrate, computetime,
                                           job[2], ping, back_color, feedback[1] if len(feedback) > 1 else None,
                                           print_queue=print_queue)
                            
                            # Periodic report
                            if id == 0 and time.time() - last_report >= int(user_settings.get("report_sec", 300)):
                                r_shares = accept.value - last_shares
                                uptime = calculate_uptime(mining_start_time)
                                end_time = time.time()
                                pretty_print(
                                    get_string("periodic_mining_report") + 
                                    f"Period: {int(end_time - last_report)}s | Shares: {r_shares} | "
                                    f"Rate: {get_prefix('H/s', total_hashrate, 2)} | "
                                    f"Total: {int(total_hashrate * (end_time - last_report))} | "
                                    f"Uptime: {uptime}",
                                    "success", "sys0", print_queue
                                )
                                last_report = end_time
                                last_shares = accept.value
                            break
                        break
                except Exception as e:
                    pretty_print(f"Error while mining: {e}", "error", f"net{id}", print_queue)
                    time.sleep(5)
                    break
        except Exception as e:
            pretty_print(f"Connection error: {e}", "error", f"net{id}", print_queue)
            time.sleep(5)

# ==================== MAIN ====================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    # Create data directory
    if not Path(Settings.DATA_DIR).is_dir():
        os.mkdir(Settings.DATA_DIR)
    
    # Load translations
    load_translations()
    
    # Load config
    user_settings = load_config()
    
    # Detect Raspberry Pi
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as f:
            if 'raspberry pi' in f.read().lower():
                running_on_rpi = True
                pretty_print(get_string("running_on_rpi") + " - LED control enabled", "success")
    except:
        pass
    
    # Check mining key
    try:
        check_mining_key(user_settings)
    except Exception as e:
        pretty_print(f"Error checking mining key: {e}", "error")
    
    # Start mining
    mining_start_time = time.time()
    manager = multiprocessing.Manager()
    accept = manager.Value('i', 0)
    reject = manager.Value('i', 0)
    blocks = manager.Value('i', 0)
    hashrate = manager.dict()
    print_queue = manager.list()
    
    # Start print handler thread
    print_thread = threading.Thread(target=print_queue_handler, args=(print_queue,))
    print_thread.daemon = True
    print_thread.start()
    
    # Get fastest pool
    pretty_print(get_string("connection_search"), "info", "net0")
    pool = Client.fetch_pool()
    pretty_print(get_string("connecting_node") + f"{pool[0]}:{pool[1]}", "info", "net0")
    
    # Start miner processes
    threads = min(int(user_settings.get("threads", multiprocessing.cpu_count())), 16)
    processes = []
    single_miner_id = random.randint(0, 2811)
    
    for i in range(threads):
        p = multiprocessing.Process(target=mining_thread, args=(
            i, user_settings, blocks, pool, accept, reject,
            hashrate, single_miner_id, print_queue
        ))
        p.start()
        processes.append(p)
    
    # Wait for processes
    for p in processes:
        p.join()
