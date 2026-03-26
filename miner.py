#!/usr/bin/env python3
"""
Duino-Coin Official PC Miner 4.3 - STANDARD LIBRARY EDITION
Modified to use only standard library + colorama, psutil, requests
https://duinocoin.com
"""

import sys
import os
import io
import json
import time
import socket
import hashlib
import threading
import multiprocessing
import subprocess
import urllib.request
import urllib.parse
import configparser
import random
import re
import traceback
import platform
import locale
import signal
import zipfile
from datetime import datetime
from pathlib import Path
from collections import deque

# ============================================================================
# THIRD PARTY LIBRARIES (required, will be auto-installed if missing)
# ============================================================================

def install_package(package, import_name=None):
    """Auto-install missing packages"""
    if import_name is None:
        import_name = package
    try:
        __import__(import_name)
        return True
    except ImportError:
        print(f"{package} is not installed. Attempting to install...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"Successfully installed {package}")
            return True
        except Exception as e:
            print(f"Failed to install {package}: {e}")
            print(f"Please manually run: python3 -m pip install {package}")
            return False

# Check and install required packages
required_packages = {
    "colorama": "colorama",
    "psutil": "psutil",
    "requests": "requests"
}

for pkg, imp in required_packages.items():
    if not install_package(pkg, imp):
        print(f"Cannot continue without {pkg}. Exiting.")
        sys.exit(1)

# Now import the required packages
import colorama
from colorama import Back, Fore, Style
import psutil
import requests

# Initialize colorama
colorama.init(autoreset=True)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Settings:
    ENCODING = "UTF-8"
    SEPARATOR = ","
    VER = 4.3
    DATA_DIR = f"Duino-Coin PC Miner {VER}"
    TRANSLATIONS_URL = "https://raw.githubusercontent.com/revoxhere/duino-coin/master/Resources/PC_Miner_langs.json"
    TRANSLATIONS_FILE = "/Translations.json"
    SETTINGS_FILE = "/Settings.cfg"
    SOC_TIMEOUT = 10
    REPORT_TIME = 300
    DONATE_LVL = 0
    RASPI_LEDS = "y"
    RASPI_CPU_IOT = "y"
    disable_title = False
    
    try:
        BLOCK = " ‖ "
        "‖".encode(sys.stdout.encoding)
    except:
        BLOCK = " | "
    PICK = ""
    COG = " @"
    if os.name != "nt":
        try:
            "⛏ ⚙".encode(sys.stdout.encoding)
            PICK = " ⛏"
            COG = " ⚙"
        except UnicodeEncodeError:
            PICK = ""
            COG = " @"

# ============================================================================
# GLOBAL VARIABLES
# ============================================================================

debug = "n"
running_on_rpi = False
configparser = configparser.ConfigParser()
printlock = threading.Lock()
lang_file = {}
lang = "english"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def now():
    return datetime.now()

def handler(signal_received, frame):
    """Handle Ctrl+C gracefully"""
    if multiprocessing.current_process().name == "MainProcess":
        print(f"\n{Style.RESET_ALL}{Fore.YELLOW}Stopping miner... Goodbye!")
    
    if running_on_rpi and user_settings.get("raspi_leds") == "y":
        os.system('echo mmc0 | sudo tee /sys/class/leds/led0/trigger >/dev/null 2>&1')
        os.system('echo 1 | sudo tee /sys/class/leds/led1/brightness >/dev/null 2>&1')
    
    if sys.platform == "win32":
        os._exit(0)
    else:
        subprocess.Popen("kill $(ps aux | grep PC_Miner | awk '{print $2}')",
                         shell=True, stdout=subprocess.PIPE)

def debug_output(text):
    if debug == 'y':
        print(f"{Style.RESET_ALL}{Fore.WHITE}{now().strftime('%H:%M:%S.%f')} DEBUG: {text}")

def title(title_str):
    if not Settings.disable_title:
        if os.name == 'nt':
            os.system('title ' + title_str)
        else:
            try:
                print(f'\33]0;{title_str}\a', end='')
                sys.stdout.flush()
            except:
                Settings.disable_title = True

def get_string(string_name):
    """Get string from language file"""
    if string_name in lang_file.get(lang, {}):
        return lang_file[lang][string_name]
    elif string_name in lang_file.get("english", {}):
        return lang_file["english"][string_name]
    return string_name

def get_prefix(symbol, val, accuracy):
    """Format hash rate with prefix"""
    if val >= 1_000_000_000_000:
        val = f"{round(val / 1_000_000_000_000, accuracy)} T"
    elif val >= 1_000_000_000:
        val = f"{round(val / 1_000_000_000, accuracy)} G"
    elif val >= 1_000_000:
        val = f"{round(val / 1_000_000, accuracy)} M"
    elif val >= 1_000:
        val = f"{round(val / 1_000)} k"
    else:
        val = f"{round(val)} "
    return f"{val}{symbol}"

def get_rpi_temperature():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read().strip()) / 1000
        return round(temp, 2)
    except:
        return 0

def calculate_uptime(start_time):
    uptime = time.time() - start_time
    if uptime >= 7200:
        return f"{int(uptime // 3600)} hours"
    elif uptime >= 3600:
        return f"{int(uptime // 3600)} hour"
    elif uptime >= 120:
        return f"{int(uptime // 60)} minutes"
    elif uptime >= 60:
        return f"{int(uptime // 60)} minute"
    else:
        return f"{int(uptime)} seconds"

def pretty_print(msg=None, state="success", sender="sys0", print_queue=None):
    """Nicely formatted output"""
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
    
    output = (f"{Fore.WHITE}{now().strftime('%H:%M:%S ')}"
              f"{Style.RESET_ALL}{Style.BRIGHT}{bg_color} {sender} "
              f"{Style.NORMAL}{Back.RESET} {fg_color}{msg.strip()}")
    
    if print_queue is not None:
        print_queue.append(output)
    else:
        print(output)

def share_print(id, type_, accept, reject, thread_hashrate, total_hashrate,
                computetime, diff, ping, back_color, reject_cause=None,
                print_queue=None):
    """Print share info"""
    thread_hashrate = get_prefix("H/s", thread_hashrate, 2)
    total_hashrate = get_prefix("H/s", total_hashrate, 1)
    diff_str = get_prefix("", int(diff), 0)
    
    def blink_led(led="green"):
        if led == "green":
            os.system('echo 1 | sudo tee /sys/class/leds/led0/brightness >/dev/null 2>&1')
            time.sleep(0.1)
            os.system('echo 0 | sudo tee /sys/class/leds/led0/brightness >/dev/null 2>&1')
        else:
            os.system('echo 1 | sudo tee /sys/class/leds/led1/brightness >/dev/null 2>&1')
            time.sleep(0.1)
            os.system('echo 0 | sudo tee /sys/class/leds/led1/brightness >/dev/null 2>&1')
    
    if type_ == "accept":
        if running_on_rpi and user_settings.get("raspi_leds") == "y":
            blink_led()
        share_str = "Accepted"
        fg_color = Fore.GREEN
    elif type_ == "block":
        if running_on_rpi and user_settings.get("raspi_leds") == "y":
            blink_led()
        share_str = "Block found"
        fg_color = Fore.YELLOW
    else:
        if running_on_rpi and user_settings.get("raspi_leds") == "y":
            blink_led("red")
        share_str = "Rejected"
        if reject_cause:
            share_str += f"({reject_cause}) "
        fg_color = Fore.RED
    
    total = accept + reject
    pct = int(accept / total * 100) if total > 0 else 0
    
    output = (f"{Fore.WHITE}{now().strftime('%H:%M:%S ')}"
              f"{Style.RESET_ALL}{Fore.WHITE}{Style.BRIGHT}{back_color} cpu{id} "
              f"{Back.RESET}{fg_color}{Settings.PICK}{share_str}{Fore.RESET}"
              f"{accept}/{total}{Fore.YELLOW} ({pct}%){Style.NORMAL}{Fore.RESET}"
              f" ∙ {computetime:.1f}s{Style.NORMAL} ∙ {Fore.BLUE}{Style.BRIGHT}"
              f"{thread_hashrate}{Style.DIM} ({total_hashrate} total){Fore.RESET}"
              f"{Settings.COG} diff {diff_str} ∙ {Fore.CYAN}ping {int(ping)}ms")
    
    if print_queue is not None:
        print_queue.append(output)
    else:
        print(output)

def print_queue_handler(print_queue):
    """Handle print queue for multi-threading"""
    while True:
        if len(print_queue):
            msg = print_queue[0]
            with printlock:
                print(msg)
            print_queue.pop(0)
        time.sleep(0.01)

# ============================================================================
# NETWORK CLIENT
# ============================================================================

class Client:
    @staticmethod
    def connect(pool):
        global s
        s = socket.socket()
        s.settimeout(Settings.SOC_TIMEOUT)
        s.connect(pool)
    
    @staticmethod
    def send(msg):
        return s.sendall(str(msg).encode(Settings.ENCODING))
    
    @staticmethod
    def recv(limit=128):
        return s.recv(limit).decode(Settings.ENCODING).rstrip("\n")
    
    @staticmethod
    def fetch_pool(retry_count=1):
        while True:
            if retry_count > 60:
                retry_count = 60
            try:
                pretty_print("Searching for the fastest server...", "info", "net0")
                response = requests.get("https://server.duinocoin.com/getPool",
                                       timeout=Settings.SOC_TIMEOUT).json()
                if response.get("success"):
                    pretty_print(f"Connecting to {response.get('name')} node...", "info", "net0")
                    return (response["ip"], response["port"])
                elif "message" in response:
                    pretty_print(f"Warning: {response['message']}, retrying in {retry_count*2}s",
                                "warning", "net0")
                else:
                    raise Exception("no response")
            except Exception as e:
                pretty_print(f"Error fetching pool: {e}, retrying in {retry_count*2}s",
                            "error", "net0")
            time.sleep(retry_count * 2)
            retry_count += 1

# ============================================================================
# MINING ALGORITHM
# ============================================================================

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
                hashrate = 1e9 * nonce / time_elapsed if time_elapsed > 0 else 0
                return [nonce, hashrate]
        
        return [0, 0]

# ============================================================================
# MINER CLASS
# ============================================================================

class Miner:
    @staticmethod
    def preload():
        global lang_file, lang
        
        # Create data directory
        if not Path(Settings.DATA_DIR).is_dir():
            os.mkdir(Settings.DATA_DIR)
        
        # Download translations if needed
        trans_file = Settings.DATA_DIR + Settings.TRANSLATIONS_FILE
        if not Path(trans_file).is_file():
            try:
                r = requests.get(Settings.TRANSLATIONS_URL, timeout=Settings.SOC_TIMEOUT)
                with open(trans_file, "wb") as f:
                    f.write(r.content)
            except:
                pass
        
        # Load translations
        try:
            with open(trans_file, "r", encoding=Settings.ENCODING) as f:
                lang_file = json.load(f)
        except:
            lang_file = {"english": {}}
        
        # Detect language
        try:
            if not Path(Settings.DATA_DIR + Settings.SETTINGS_FILE).is_file():
                locale_lang = locale.getdefaultlocale()[0]
                if locale_lang:
                    lang_map = {
                        "es": "spanish", "pl": "polish", "fr": "french",
                        "de": "german", "ru": "russian", "zh": "chinese_simplified"
                    }
                    lang = lang_map.get(locale_lang[:2], "english")
                else:
                    lang = "english"
            else:
                configparser.read(Settings.DATA_DIR + Settings.SETTINGS_FILE)
                lang = configparser["PC Miner"].get("language", "english")
        except:
            lang = "english"
    
    @staticmethod
    def load_cfg():
        cfg_file = Settings.DATA_DIR + Settings.SETTINGS_FILE
        if not Path(cfg_file).is_file():
            # Create default config
            username = input("Enter your Duino-Coin username: ").strip()
            if not username:
                username = "revox"
            
            threads = input(f"Number of threads (default: {multiprocessing.cpu_count()}): ").strip()
            threads = int(threads) if threads.isdigit() else multiprocessing.cpu_count()
            threads = max(1, min(threads, 16))
            
            configparser["PC Miner"] = {
                "username": username,
                "mining_key": "None",
                "intensity": "95",
                "threads": str(threads),
                "start_diff": "MEDIUM",
                "donate": "1",
                "identifier": "None",
                "algorithm": "DUCO-S1",
                "language": lang,
                "soc_timeout": str(Settings.SOC_TIMEOUT),
                "report_sec": str(Settings.REPORT_TIME),
                "raspi_leds": "y",
                "raspi_cpu_iot": "y",
                "discord_rp": "y"
            }
            
            with open(cfg_file, "w") as f:
                configparser.write(f)
            print("Configuration saved.")
        
        configparser.read(cfg_file)
        return configparser["PC Miner"]
    
    @staticmethod
    def greeting():
        print(f"\n{Style.DIM}{Fore.YELLOW}{Settings.BLOCK}{Fore.YELLOW}{Style.BRIGHT}"
              f"Duino-Coin PC Miner{Style.RESET_ALL}{Fore.MAGENTA} ({Settings.VER}) "
              f"{Fore.RESET}2019-2026")
        print(f"{Style.DIM}{Fore.YELLOW}{Settings.BLOCK}{Style.NORMAL}{Fore.YELLOW}"
              f"https://github.com/revoxhere/duino-coin")
        print(f"{Style.DIM}{Fore.YELLOW}{Settings.BLOCK}{Style.NORMAL}{Fore.RESET}"
              f"CPU: {Style.BRIGHT}{Fore.YELLOW}{user_settings.get('threads', 1)}x threads")
        print(f"{Style.DIM}{Fore.YELLOW}{Settings.BLOCK}{Style.NORMAL}{Fore.RESET}"
              f"Donation level: {Style.BRIGHT}{Fore.YELLOW}{user_settings.get('donate', 0)}")
        print(f"{Style.DIM}{Fore.YELLOW}{Settings.BLOCK}{Style.NORMAL}{Fore.RESET}"
              f"Algorithm: {Style.BRIGHT}{Fore.YELLOW}{user_settings.get('algorithm', 'DUCO-S1')}")
        print(f"{Style.DIM}{Fore.YELLOW}{Settings.BLOCK}{Style.NORMAL}{Fore.RESET}"
              f"Username: {Style.BRIGHT}{Fore.YELLOW}{user_settings.get('username', '')}!\n")
    
    @staticmethod
    def m_connect(id_, pool):
        retry_count = 0
        while True:
            try:
                if retry_count > 3:
                    pool = Client.fetch_pool()
                    retry_count = 0
                
                Client.connect(pool)
                pool_ver = Client.recv(5)
                
                if id_ == 0:
                    Client.send("MOTD")
                    motd = Client.recv(512)
                    if motd:
                        pretty_print(f"Message of the day: {motd}", "success", f"net{id_}")
                    
                    pretty_print(f"Connected to server v{pool_ver} ({pool[0]})", "success", f"net{id_}")
                break
            except Exception as e:
                pretty_print(f"Connection error: {e}", "error", f"net{id_}")
                retry_count += 1
                time.sleep(10)
    
    @staticmethod
    def mine(id_, user_settings, blocks, pool, accept, reject, hashrate, single_miner_id, print_queue):
        pretty_print(f"Mining thread {id_} starting...", "success", f"sys{id_}", print_queue)
        
        last_report = time.time()
        last_shares = 0
        
        while True:
            try:
                Miner.m_connect(id_, pool)
                while True:
                    try:
                        key = user_settings.get("mining_key", "None")
                        if key != "None":
                            try:
                                import base64
                                key = base64.b64decode(key).decode('utf-8')
                            except:
                                pass
                        
                        # Request job
                        job_req = f"JOB,{user_settings['username']},{user_settings['start_diff']},{key}"
                        Client.send(job_req)
                        
                        job = Client.recv().split(Settings.SEPARATOR)
                        if len(job) != 3:
                            time.sleep(3)
                            continue
                        
                        while True:
                            time_start = time.time()
                            back_color = Back.YELLOW
                            
                            eff = 0
                            intensity = int(user_settings.get("intensity", 95))
                            if intensity >= 90:
                                eff = 0.005
                            elif intensity >= 70:
                                eff = 0.1
                            elif intensity >= 50:
                                eff = 0.8
                            elif intensity >= 30:
                                eff = 1.8
                            elif intensity >= 1:
                                eff = 3
                            
                            result = Algorithms.DUCOS1(job[0], job[1], int(job[2]), eff)
                            computetime = time.time() - time_start
                            
                            hashrate[id_] = result[1]
                            total_hashrate = sum(hashrate.values())
                            
                            # Send result
                            Client.send(f"{result[0]},{result[1]},Official PC Miner {Settings.VER},"
                                       f"{user_settings.get('identifier', 'None')},,{single_miner_id}")
                            
                            time_start = time.time()
                            feedback = Client.recv().split(Settings.SEPARATOR)
                            ping = (time.time() - time_start) * 1000
                            
                            if feedback[0] == "GOOD":
                                accept.value += 1
                                share_print(id_, "accept", accept.value, reject.value,
                                           hashrate[id_], total_hashrate, computetime,
                                           job[2], ping, back_color, print_queue=print_queue)
                            elif feedback[0] == "BLOCK":
                                accept.value += 1
                                blocks.value += 1
                                share_print(id_, "block", accept.value, reject.value,
                                           hashrate[id_], total_hashrate, computetime,
                                           job[2], ping, back_color, print_queue=print_queue)
                            elif feedback[0] == "BAD":
                                reject.value += 1
                                cause = feedback[1] if len(feedback) > 1 else None
                                share_print(id_, "reject", accept.value, reject.value,
                                           hashrate[id_], total_hashrate, computetime,
                                           job[2], ping, back_color, cause, print_queue)
                            
                            title(f"Duino-Coin Miner v{Settings.VER}) - {accept.value}/"
                                  f"{accept.value + reject.value} accepted shares")
                            
                            if id_ == 0:
                                end_time = time.time()
                                if end_time - last_report >= int(user_settings.get("report_sec", 300)):
                                    r_shares = accept.value - last_shares
                                    uptime = calculate_uptime(mining_start_time)
                                    pretty_print(f"Mining report: {r_shares} shares, "
                                                f"{sum(hashrate.values()):.0f} H/s, uptime {uptime}",
                                                "success", "sys0", print_queue)
                                    last_report = time.time()
                                    last_shares = accept.value
                            break
                        break
                    except Exception as e:
                        pretty_print(f"Mining error: {e}", "error", f"net{id_}", print_queue)
                        time.sleep(5)
                        break
            except Exception as e:
                pretty_print(f"Connection error: {e}", "error", f"net{id_}", print_queue)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    multiprocessing.freeze_support()
    signal.signal(signal.SIGINT, handler)
    title(f"Duino-Coin PC Miner v{Settings.VER})")
    
    if sys.platform == "win32":
        os.system('')  # Enable ANSI escape sequences
    
    # Initialize miner
    Miner.preload()
    
    # Check for updates (disabled to keep minimal)
    # check_updates()
    
    # Load settings
    user_settings = Miner.load_cfg()
    Miner.greeting()
    
    # Check for Raspberry Pi
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as f:
            if 'raspberry pi' in f.read().lower():
                running_on_rpi = True
                pretty_print("Running on Raspberry Pi - LED indicators enabled", "success")
    except:
        pass
    
    if running_on_rpi:
        os.system('echo gpio | sudo tee /sys/class/leds/led1/trigger >/dev/null 2>&1')
        os.system('echo gpio | sudo tee /sys/class/leds/led0/trigger >/dev/null 2>&1')
    
    # Setup multiprocessing
    manager = multiprocessing.Manager()
    accept = manager.Value('i', 0)
    reject = manager.Value('i', 0)
    blocks = manager.Value('i', 0)
    hashrate = manager.dict()
    print_queue = manager.list()
    
    # Start print queue handler
    printer_thread = threading.Thread(target=print_queue_handler, args=(print_queue,))
    printer_thread.daemon = True
    printer_thread.start()
    
    # Get pool
    fastest_pool = Client.fetch_pool()
    
    # Generate miner ID
    single_miner_id = random.randint(0, 2811)
    
    # Start miner processes
    threads = int(user_settings.get("threads", multiprocessing.cpu_count()))
    threads = max(1, min(threads, 16))
    
    processes = []
    for i in range(threads):
        p = multiprocessing.Process(target=Miner.mine,
                                    args=(i, user_settings, blocks, fastest_pool,
                                          accept, reject, hashrate, single_miner_id, print_queue))
        p.start()
        processes.append(p)
    
    # Wait for processes
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        handler(None, None)
