"""
تنظیمات مرکزی پروژه - Cross-Platform
Compatible with Windows/Linux/Mac
"""
import platform
import os
import sys

# تشخیص سیستم عامل
SYSTEM = platform.system()  # 'Linux', 'Windows', 'Darwin'

# ========== SERIAL PORT CONFIGURATION ==========
DEFAULT_BAUDRATE = 57600
DEFAULT_TIMEOUT = 0.1

# تنظیمات پورت بر اساس سیستم عامل
if SYSTEM == "Windows":
    # Windows: COM1, COM2, etc.
    MASTER_PORT = "COM5"
    SLAVE_PORT = "COM6"
    MAVSDK_CONNECTION = "serial:///COM5:57600"  # فرمت MAVSDK برای ویندوز
    # Alternative ports for testing
    AVAILABLE_PORTS = ["COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8"]

elif SYSTEM == "Linux":
    # Linux: /dev/ttyUSB0, /dev/ttyACM0, etc.
    MASTER_PORT = "/dev/ttyUSB0"
    SLAVE_PORT = "/dev/ttyUSB1"
    MAVSDK_CONNECTION = "serial:///dev/ttyUSB0:57600"  # فرمت MAVSDK برای لینوکس
    # Alternative ports for testing
    AVAILABLE_PORTS = [
        "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2",
        "/dev/ttyACM0", "/dev/ttyACM1",
        "/dev/ttyS0", "/dev/ttyS1"
    ]

elif SYSTEM == "Darwin":  # macOS
    # macOS: /dev/cu.usbserial-*
    MASTER_PORT = "/dev/cu.usbserial-1"
    SLAVE_PORT = "/dev/cu.usbserial-2"
    MAVSDK_CONNECTION = "serial:///dev/cu.usbserial-1:57600"
    AVAILABLE_PORTS = [
        "/dev/cu.usbserial-1", "/dev/cu.usbserial-2",
        "/dev/cu.usbmodem1", "/dev/cu.usbmodem2"
    ]
else:
    # Fallback
    MASTER_PORT = "SERIAL1"
    SLAVE_PORT = "SERIAL2"
    MAVSDK_CONNECTION = "serial:///SERIAL1:57600"
    AVAILABLE_PORTS = []

# ========== FILE PATHS (Cross-Platform) ==========
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# ایجاد پوشه‌ها در صورت عدم وجود
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ========== TEST PARAMETERS ==========
DEFAULT_NUM_PACKETS = 100
DEFAULT_INTERVAL_MS = 100

# ========== PROBE INJECTION SETTINGS ==========
PROBE_INTERVAL_MS = 100        # Probe injection interval in milliseconds
PROBE_PACKET_SIZE = 40          # Default probe packet size
PROBE_TIMEOUT_MS = 1000         # ✅ اضافه شد - Timeout for probe response
PROBE_HISTORY_SIZE = 1000       # ✅ اضافه شد - Number of probes to keep in history
PROBE_BUFFER_SIZE = 4096        # ✅ اضافه شد - Buffer size for probe data

# ========== RTT MEASUREMENT SETTINGS ==========
RTT_PACKET_SIZES = list(range(28, 280, 25))  # اندازه‌های مختلف برای تست
RTT_PACKETS_PER_SIZE = 50                     # تعداد پکت برای هر اندازه
RTT_MEASUREMENT_INTERVAL = 100                # فاصله بین اندازه‌گیری‌ها (ms)

# ========== MAVLINK SETTINGS ==========
MAVLINK_MSG_RATE = 20  # Hz
MAVLINK_TYPES = ['HEARTBEAT', 'ATTITUDE', 'GPS_RAW_INT']
MAVLINK_SYSTEM_ID = 1
MAVLINK_COMPONENT_ID = 1

# ========== PERFORMANCE SETTINGS ==========
USE_HIGH_PRIORITY = True        # استفاده از real-time priority
HIGH_PRIORITY_VALUE = -20       # Nice value for high priority
BUFFER_SIZE = 8192              # Serial buffer size
READ_CHUNK_SIZE = 1024          # Size of chunks to read from serial

# ========== LOGGING SETTINGS ==========
LOG_LEVEL = "INFO"              # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_TO_FILE = True
LOG_TO_CONSOLE = True
LOG_ROTATION = True
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# ========== ANALYSIS SETTINGS ==========
JITTER_WINDOW_SIZE = 100        # Window size for jitter calculation
HISTOGRAM_BINS = 50             # Number of bins for latency histogram
PERCENTILES = [50, 90, 95, 99, 99.9]  # Percentiles to calculate

# ========== ASYNC CONFIGURATION (Cross-Platform) ==========
# در ویندوز ممکنه نیاز به ProactorEventLoop باشه
if SYSTEM == "Windows" and sys.version_info >= (3, 8):
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ========== HELPER FUNCTIONS ==========
def get_mavsdk_connection_string(port: str = None, baudrate: int = DEFAULT_BAUDRATE) -> str:
    """
    ساخت connection string برای MAVSDK
    Compatible with Windows/Linux/Mac
    """
    if port is None:
        port = MASTER_PORT

    # تشخیص نوع connection
    if "COM" in port.upper():  # Windows
        return f"serial:///{port}:{baudrate}"
    elif "/dev/" in port:  # Linux/Mac
        return f"serial://{port}:{baudrate}"
    else:
        # فرض بر UDP
        return f"udp://:{port}"

def print_system_info():
    """نمایش اطلاعات سیستم"""
    print("="*50)
    print(f"🖥️  Operating System: {SYSTEM}")
    print(f"🐍 Python Version: {sys.version}")
    print(f"📂 Base Directory: {BASE_DIR}")
    print(f"📁 Results Directory: {RESULTS_DIR}")
    print(f"📁 Logs Directory: {LOG_DIR}")
    print(f"🔌 Default Master Port: {MASTER_PORT}")
    print(f"🔌 Default Slave Port: {SLAVE_PORT}")
    print(f"🔗 MAVSDK Connection: {MAVSDK_CONNECTION}")
    print("="*50)

def detect_available_ports():
    """تشخیص پورت‌های موجود"""
    try:
        import serial.tools.list_ports
        available = []
        ports = serial.tools.list_ports.comports()

        for port in ports:
            available.append(port.device)

        return available
    except ImportError:
        print("⚠️ pyserial not installed, can't detect ports")
        return []

def auto_detect_ports():
    """تشخیص خودکار پورت‌ها"""
    ports = detect_available_ports()

    if len(ports) >= 2:
        return ports[0], ports[1]
    elif len(ports) == 1:
        return ports[0], None
    else:
        return None, None

# ========== VALIDATION FUNCTIONS ==========
def validate_config():
    """بررسی صحت تنظیمات"""
    errors = []
    
    # بررسی پورت‌ها
    if SYSTEM == "Linux":
        if not os.path.exists(MASTER_PORT) and not MASTER_PORT.startswith("/dev/"):
            errors.append(f"Master port {MASTER_PORT} may not exist")
    
    # بررسی دسترسی به دایرکتوری‌ها
    if not os.access(BASE_DIR, os.W_OK):
        errors.append(f"No write permission for {BASE_DIR}")
    
    return errors

# ========== HITL SPECIFIC SETTINGS ==========
# برای تست با PX4 HITL
HITL_ENABLED = False
HITL_FC_PORT = "/dev/ttyACM0"      # Flight Controller port
HITL_RADIO_PORT = "/dev/ttyUSB0"   # P900 Master radio port
HITL_BAUDRATE = 57600               # Baudrate for HITL connection
HITL_MAVLINK_RATE = 50              # Hz - MAVLink message rate in HITL
