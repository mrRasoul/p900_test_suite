"""
کمک‌کننده مسیرها برای سازگاری Cross-Platform
"""
import os
import platform
from datetime import datetime

def get_timestamp():
    """دریافت timestamp یکسان برای همه سیستم‌ها"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def create_result_path(prefix, extension=".txt"):
    """ایجاد مسیر نتیجه cross-platform"""
    from .config import RESULTS_DIR
    
    timestamp = get_timestamp()
    filename = f"{prefix}_{timestamp}{extension}"
    return os.path.join(RESULTS_DIR, filename)

def create_log_path(name):
    """ایجاد مسیر log cross-platform"""
    from .config import LOG_DIR
    
    timestamp = get_timestamp()
    filename = f"{name}_{timestamp}.log"
    return os.path.join(LOG_DIR, filename)

def ensure_dirs_exist():
    """اطمینان از وجود پوشه‌های ضروری"""
    from .config import RESULTS_DIR, LOG_DIR
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

def normalize_path(path):
    """نرمال‌سازی مسیر برای OS فعلی"""
    return os.path.normpath(os.path.expanduser(path))
