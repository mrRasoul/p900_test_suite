#!/usr/bin/env python3
"""
Probe Injection Module for P900 Testing
ماژول تزریق Probe برای تست تحت بار و اندازه‌گیری دقیق تأخیر
Version: 3.0 - Variable Size Implementation
"""

import time
import threading
import struct
import queue
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import deque
import json
import logging
import sys
from pathlib import Path

# تنظیم مسیر برای import ها
current_dir = Path(__file__).parent
parent_dir = current_dir.parent
if parent_dir not in sys.path:
    sys.path.insert(0, str(parent_dir))

# حالا import های نسبی
try:
    from utils.logger import setup_logger
    from utils.config import (
        PROBE_INTERVAL_MS,
        PROBE_PACKET_SIZE,
        PROBE_TIMEOUT_MS,
        PROBE_HISTORY_SIZE,
        DEFAULT_BAUDRATE
    )
    logger = setup_logger('ProbeInjector')
except ImportError:
    # اگر utils موجود نبود، از logging استاندارد استفاده کن
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('ProbeInjector')
    # مقادیر پیش‌فرض
    PROBE_INTERVAL_MS = 100
    PROBE_PACKET_SIZE = 108
    PROBE_TIMEOUT_MS = 500
    PROBE_HISTORY_SIZE = 1000
    DEFAULT_BAUDRATE = 57600

# Import packet generator با مسیر نسبی
try:
    from core.packet_generator import PacketGenerator, create_generator
    from core.mavlink_profile import MAVLinkProfile
except ImportError:
    # اگر import مستقیم کار نکرد، مسیر محلی را امتحان کن
    try:
        from packet_generator import PacketGenerator, create_generator
        from mavlink_profile import MAVLinkProfile
    except ImportError as e:
        logger.error(f"Failed to import packet_generator: {e}")
        # تعریف کلاس ساده برای ادامه کار
        class PacketGenerator:
            def __init__(self, profile=None):
                self.profile = profile
            def generate_probe_packet(self, size, probe_id):
                # پکت ساده با اندازه مشخص
                packet = bytearray(size)
                packet[:4] = struct.pack('<I', probe_id)
                return bytes(packet)
            def get_test_sizes(self):
                return [64, 128, 256, 512, 1024]

@dataclass
class ProbeRecord:
    """ساختار داده برای ذخیره اطلاعات هر پروب"""
    probe_id: int
    timestamp_sent: float
    timestamp_received: float = 0
    packet_size: int = 0
    status: str = 'PENDING'  # 'PENDING', 'RECEIVED', 'TIMEOUT'
    rtt_ms: float = 0
    jitter_ms: float = 0

@dataclass
class ProbeStatistics:
    """آمار جامع پروب‌ها"""
    total_sent: int
    total_received: int
    total_lost: int
    loss_rate: float
    avg_rtt_ms: float
    min_rtt_ms: float
    max_rtt_ms: float
    std_rtt_ms: float
    avg_jitter_ms: float
    max_jitter_ms: float
    percentile_95_ms: float
    percentile_99_ms: float
    current_rate_hz: float
    bytes_sent: int
    bytes_received: int
    stats_by_size: Dict[int, Dict] = None
    size_distribution: Dict[int, int] = None

class ProbeInjector:
    """
    کلاس تزریق Probe با اندازه‌های متغیر
    """
    
    # Constants for probe protocol
    PROBE_MARKER = b'\xBB\x44'
    PROBE_TYPE_REQUEST = 0x10
    PROBE_TYPE_RESPONSE = 0x11
    PROBE_HEADER_SIZE = 24
    
    def __init__(self,
                 master_serial=None,
                 slave_serial=None,
                 interval_ms=PROBE_INTERVAL_MS,
                 timeout_ms=PROBE_TIMEOUT_MS,
                 history_size=PROBE_HISTORY_SIZE,
                 packet_generator=None,
                 size_mode='fixed',
                 fixed_size=PROBE_PACKET_SIZE):
        """
        Initialize ProbeInjector with variable size support
        
        Args:
            master_serial: Serial port for master side
            slave_serial: Serial port for slave side
            interval_ms: Interval between probes
            timeout_ms: Timeout for probe response
            history_size: Number of probes to keep in history
            packet_generator: Generator for creating packets
            size_mode: 'fixed', 'representative', 'realistic', 'random'
            fixed_size: Size for fixed mode
        """
        self.master_serial = master_serial
        self.slave_serial = slave_serial
        self.interval_ms = interval_ms
        self.timeout_ms = timeout_ms
        self.history_size = history_size
        
        # Packet generator و تنظیمات اندازه
        self.packet_generator = packet_generator or PacketGenerator()
        self.size_mode = size_mode
        self.fixed_size = fixed_size
        
        # دریافت اندازه‌های متغیر
        if size_mode == 'representative':
            self.variable_sizes = self.packet_generator.get_representative_sizes()
        elif size_mode == 'fixed':
            self.variable_sizes = [fixed_size]
        else:
            # برای realistic و random، هر بار تولید می‌کنیم
            self.variable_sizes = None
        
        self.current_size_index = 0
        
        # Threading control
        self.running = False
        self.injection_thread = None
        self.receiver_thread = None
        self.slave_responder_thread = None
        
        # Data structures
        self.probe_history = deque(maxlen=history_size)
        self.pending_probes = {}
        self.probe_lock = threading.Lock()
        
        # Statistics - با پشتیبانی از اندازه‌های مختلف
        self.stats = {
            'total_sent': 0,
            'total_received': 0,
            'total_lost': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'last_rtt_ms': 0,
            'last_jitter_ms': 0,
            'size_stats': {}  # آمار بر حسب اندازه
        }
        
        # Timing
        self.last_rtt_values = deque(maxlen=100)
        self.probe_id_counter = 0
        
        logger.info(f"ProbeInjector initialized:")
        logger.info(f"  Interval: {interval_ms}ms")
        logger.info(f"  Size mode: {size_mode}")
        logger.info(f"  Variable sizes: {self.variable_sizes}")
        logger.info(f"  Timeout: {timeout_ms}ms")
    
    def _get_timestamp(self) -> float:
        """Get high-precision timestamp"""
        return time.perf_counter()
    
    def _get_next_packet_size(self) -> int:
        """Get next packet size based on mode"""
        if self.size_mode == 'fixed':
            return self.fixed_size
        
        elif self.size_mode == 'representative':
            if self.variable_sizes:
                size = self.variable_sizes[self.current_size_index]
                self.current_size_index = (self.current_size_index + 1) % len(self.variable_sizes)
                return size
        
        elif self.size_mode in ['realistic', 'random']:
            # از packet generator درخواست اندازه
            sizes = self.packet_generator.profile.get_packet_sizes(1, self.size_mode)
            return sizes[0] if sizes else self.fixed_size
        
        return self.fixed_size
    
    def _create_probe_packet(self, probe_id: int, packet_type: int, 
                           packet_size: int, timestamp: float = None) -> bytes:
        """Create probe packet with specified size"""
        packet = bytearray()
        
        # Header
        packet.extend(self.PROBE_MARKER)
        packet.extend(struct.pack('<I', probe_id))
        packet.append(packet_type)
        
        # Timestamp
        if timestamp is None:
            timestamp = self._get_timestamp()
        timestamp_us = int(timestamp * 1_000_000)
        packet.extend(struct.pack('<Q', timestamp_us))
        
        # Size field
        packet.extend(struct.pack('<H', packet_size))
        
        # Reserved
        packet.extend(bytes(6))
        
        # Checksum
        checksum = 0
        for byte in packet:
            checksum ^= byte
        packet.append(checksum)
        
        # Payload to reach desired size
        payload_size = packet_size - len(packet)
        if payload_size > 0:
            payload = bytes([(i ^ probe_id) % 256 for i in range(payload_size)])
            packet.extend(payload)
        
        return bytes(packet)
    
    def _parse_probe_packet(self, data: bytes) -> Optional[Dict]:
        """Parse probe packet"""
        if len(data) < self.PROBE_HEADER_SIZE:
            return None
        
        try:
            if data[:2] != self.PROBE_MARKER:
                return None
            
            probe_id = struct.unpack('<I', data[2:6])[0]
            packet_type = data[6]
            timestamp_us = struct.unpack('<Q', data[7:15])[0]
            packet_size = struct.unpack('<H', data[15:17])[0]
            
            return {
                'probe_id': probe_id,
                'type': packet_type,
                'timestamp': timestamp_us / 1_000_000.0,
                'size': packet_size,
                'valid': True
            }
        except Exception as e:
            logger.error(f"Error parsing probe: {e}")
            return None
    
    def _injection_loop(self):
        """Main injection loop with variable sizes"""
        logger.info("Probe injection started")
        next_probe_time = self._get_timestamp()
        
        while self.running:
            try:
                current_time = self._get_timestamp()
                
                if current_time >= next_probe_time:
                    # تعیین اندازه بعدی
                    packet_size = self._get_next_packet_size()
                    
                    # ایجاد probe ID
                    probe_id = self.probe_id_counter
                    self.probe_id_counter = (self.probe_id_counter + 1) % 0xFFFFFFFF
                    
                    # ایجاد و ارسال پکت
                    timestamp_sent = self._get_timestamp()
                    probe_packet = self._create_probe_packet(
                        probe_id, 
                        self.PROBE_TYPE_REQUEST,
                        packet_size,
                        timestamp_sent
                    )
                    
                    if self.master_serial and self.master_serial.is_open:
                        self.master_serial.write(probe_packet)
                        self.master_serial.flush()
                        
                        # ثبت در pending
                        with self.probe_lock:
                            record = ProbeRecord(
                                probe_id=probe_id,
                                timestamp_sent=timestamp_sent,
                                packet_size=packet_size,
                                status='PENDING'
                            )
                            self.pending_probes[probe_id] = record
                            
                            # آپدیت آمار
                            self.stats['total_sent'] += 1
                            self.stats['bytes_sent'] += len(probe_packet)
                            
                            # آمار بر حسب اندازه
                            if packet_size not in self.stats['size_stats']:
                                self.stats['size_stats'][packet_size] = {
                                    'sent': 0, 'received': 0, 'lost': 0,
                                    'total_rtt': 0, 'min_rtt': float('inf'), 'max_rtt': 0
                                }
                            self.stats['size_stats'][packet_size]['sent'] += 1
                        
                        logger.debug(f"Probe {probe_id} sent: size={packet_size}B")
                    
                    # زمان‌بندی پروب بعدی
                    next_probe_time = current_time + (self.interval_ms / 1000.0)
                
                # بررسی timeout ها
                self._check_timeouts()
                
                time.sleep(0.0001)
                
            except Exception as e:
                logger.error(f"Injection error: {e}")
                time.sleep(0.001)
        
        logger.info("Probe injection stopped")
    
    def _receiver_loop(self):
        """Receiver loop for probe responses"""
        logger.info("Receiver loop started")
        buffer = bytearray()
        
        while self.running:
            try:
                if self.master_serial and self.master_serial.in_waiting > 0:
                    data = self.master_serial.read(self.master_serial.in_waiting)
                    buffer.extend(data)
                    
                    # جستجوی marker
                    while len(buffer) >= self.PROBE_HEADER_SIZE:
                        marker_pos = buffer.find(self.PROBE_MARKER)
                        
                        if marker_pos == -1:
                            buffer = bytearray()
                            break
                        
                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]
                        
                        # پردازش پکت
                        parsed = self._parse_probe_packet(buffer)
                        if parsed and parsed['type'] == self.PROBE_TYPE_RESPONSE:
                            self._process_probe_response(
                                parsed['probe_id'],
                                parsed['timestamp'],
                                self._get_timestamp(),
                                parsed['size']
                            )
                        
                        # حذف پکت پردازش شده
                        if parsed and 'size' in parsed:
                            buffer = buffer[parsed['size']:]
                        else:
                            buffer = buffer[self.PROBE_HEADER_SIZE:]
                
                time.sleep(0.0001)
                
            except Exception as e:
                logger.error(f"Receiver error: {e}")
                time.sleep(0.001)
        
        logger.info("Receiver loop stopped")
    
    def _slave_responder_loop(self):
        """Slave responder loop"""
        logger.info("Slave responder started")
        buffer = bytearray()
        
        while self.running:
            try:
                if self.slave_serial and self.slave_serial.in_waiting > 0:
                    data = self.slave_serial.read(self.slave_serial.in_waiting)
                    buffer.extend(data)
                    
                    while len(buffer) >= self.PROBE_HEADER_SIZE:
                        marker_pos = buffer.find(self.PROBE_MARKER)
                        
                        if marker_pos == -1:
                            buffer = bytearray()
                            break
                        
                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]
                        
                        parsed = self._parse_probe_packet(buffer)
                        if parsed and parsed['type'] == self.PROBE_TYPE_REQUEST:
                            # ارسال پاسخ
                            response = self._create_probe_packet(
                                parsed['probe_id'],
                                self.PROBE_TYPE_RESPONSE,
                                parsed['size'],
                                parsed['timestamp']
                            )
                            
                            self.slave_serial.write(response)
                            self.slave_serial.flush()
                            
                            logger.debug(f"Response sent for probe {parsed['probe_id']}")
                        
                        if parsed and 'size' in parsed:
                            buffer = buffer[parsed['size']:]
                        else:
                            buffer = buffer[self.PROBE_HEADER_SIZE:]
                
                time.sleep(0.0001)
                
            except Exception as e:
                logger.error(f"Slave responder error: {e}")
                time.sleep(0.001)
        
        logger.info("Slave responder stopped")
    
    def _process_probe_response(self, probe_id: int, original_timestamp: float, 
                               received_timestamp: float, packet_size: int):
        """Process probe response"""
        with self.probe_lock:
            if probe_id in self.pending_probes:
                record = self.pending_probes.pop(probe_id)
                
                # محاسبه RTT
                rtt_ms = (received_timestamp - record.timestamp_sent) * 1000
                
                # محاسبه jitter
                jitter_ms = 0
                if self.last_rtt_values:
                    jitter_ms = abs(rtt_ms - self.last_rtt_values[-1])
                self.last_rtt_values.append(rtt_ms)
                
                # آپدیت record
                record.timestamp_received = received_timestamp
                record.status = 'RECEIVED'
                record.rtt_ms = rtt_ms
                record.jitter_ms = jitter_ms
                
                # آپدیت آمار کلی
                self.stats['total_received'] += 1
                self.stats['bytes_received'] += packet_size
                self.stats['last_rtt_ms'] = rtt_ms
                self.stats['last_jitter_ms'] = jitter_ms
                
                # آمار بر حسب اندازه
                if packet_size in self.stats['size_stats']:
                    size_stat = self.stats['size_stats'][packet_size]
                    size_stat['received'] += 1
                    size_stat['total_rtt'] += rtt_ms
                    size_stat['min_rtt'] = min(size_stat['min_rtt'], rtt_ms)
                    size_stat['max_rtt'] = max(size_stat['max_rtt'], rtt_ms)
                
                # ذخیره در history
                self.probe_history.append(record)
                
                logger.info(f"Probe {probe_id} received: size={packet_size}B, "
                          f"RTT={rtt_ms:.3f}ms, Jitter={jitter_ms:.3f}ms")
    
    def _check_timeouts(self):
        """Check for probe timeouts"""
        current_time = self._get_timestamp()
        timeout_threshold = self.timeout_ms / 1000.0
        
        with self.probe_lock:
            timed_out = []
            for probe_id, record in list(self.pending_probes.items()):
                if current_time - record.timestamp_sent > timeout_threshold:
                    timed_out.append(probe_id)
            
            for probe_id in timed_out:
                record = self.pending_probes.pop(probe_id)
                record.status = 'TIMEOUT'
                self.stats['total_lost'] += 1
                
                # آپدیت آمار اندازه
                if record.packet_size in self.stats['size_stats']:
                    self.stats['size_stats'][record.packet_size]['lost'] += 1
                
                self.probe_history.append(record)
                logger.warning(f"Probe {probe_id} timed out (size={record.packet_size}B)")
    
    def start(self):
        """Start probe injection"""
        if self.running:
            logger.warning("ProbeInjector already running")
            return
        
        self.running = True
        
        # شروع thread ها
        if self.master_serial:
            self.injection_thread = threading.Thread(
                target=self._injection_loop, 
                daemon=True, 
                name="ProbeInjection"
            )
            self.injection_thread.start()
            
            self.receiver_thread = threading.Thread(
                target=self._receiver_loop, 
                daemon=True,
                name="ProbeReceiver"
            )
            self.receiver_thread.start()
        
        if self.slave_serial:
            self.slave_responder_thread = threading.Thread(
                target=self._slave_responder_loop, 
                daemon=True,
                name="SlaveResponder"
            )
            self.slave_responder_thread.start()
        
        logger.info("ProbeInjector started successfully")
    
    def stop(self):
        """Stop probe injection"""
        logger.info("Stopping ProbeInjector...")
        self.running = False
        
        # منتظر توقف thread ها
        if hasattr(self, 'injection_thread') and self.injection_thread:
            self.injection_thread.join(timeout=1.0)
        if hasattr(self, 'receiver_thread') and self.receiver_thread:
            self.receiver_thread.join(timeout=1.0)
        if hasattr(self, 'slave_responder_thread') and self.slave_responder_thread:
            self.slave_responder_thread.join(timeout=1.0)
        
        logger.info("ProbeInjector stopped")
    
    def get_statistics(self) -> ProbeStatistics:
        """Get comprehensive probe statistics"""
        with self.probe_lock:
            # فیلتر پروب‌های دریافت شده
            received_probes = [p for p in self.probe_history if p.status == 'RECEIVED']

            # اگر هیچ پروبی دریافت نشده
            if not received_probes:
                return ProbeStatistics(
                    total_sent=self.stats['total_sent'],
                    total_received=0,
                    total_lost=self.stats['total_lost'],
                    loss_rate=100.0 if self.stats['total_sent'] else 0,
                    avg_rtt_ms=0,
                    min_rtt_ms=0,
                    max_rtt_ms=0,
                    std_rtt_ms=0,
                    avg_jitter_ms=0,
                    max_jitter_ms=0,
                    percentile_95_ms=0,
                    percentile_99_ms=0,
                    current_rate_hz=1000.0/self.interval_ms if self.interval_ms else 0,
                    bytes_sent=self.stats['bytes_sent'],
                    bytes_received=self.stats['bytes_received'],
                    stats_by_size=self.stats['size_stats'],
                    size_distribution={size: stat['sent']
                                     for size, stat in self.stats['size_stats'].items()}
                )

            # محاسبه آمار
            rtts = [p.rtt_ms for p in received_probes]
            jitters = [p.jitter_ms for p in received_probes if p.jitter_ms > 0]

            loss_rate = 0
            if self.stats['total_sent'] > 0:
                loss_rate = (self.stats['total_lost'] / self.stats['total_sent']) * 100

            return ProbeStatistics(
                total_sent=self.stats['total_sent'],
                total_received=self.stats['total_received'],
                total_lost=self.stats['total_lost'],
                loss_rate=loss_rate,
                avg_rtt_ms=np.mean(rtts),
                min_rtt_ms=np.min(rtts),
                max_rtt_ms=np.max(rtts),
                std_rtt_ms=np.std(rtts),
                avg_jitter_ms=np.mean(jitters) if jitters else 0,
                max_jitter_ms=np.max(jitters) if jitters else 0,
                percentile_95_ms=np.percentile(rtts, 95),
                percentile_99_ms=np.percentile(rtts, 99),
                current_rate_hz=1000.0/self.interval_ms if self.interval_ms else 0,
                bytes_sent=self.stats['bytes_sent'],
                bytes_received=self.stats['bytes_received'],
                stats_by_size=self.stats['size_stats'],
                size_distribution={size: stat['sent']
                                 for size, stat in self.stats['size_stats'].items()}
            )

    def get_raw_data(self) -> List[ProbeRecord]:
        """دریافت داده‌های خام برای تحلیل بیشتر"""
        with self.probe_lock:
            return list(self.probe_history)

    def reset_statistics(self):
        """ریست کردن آمار"""
        with self.probe_lock:
            self.probe_history.clear()
            self.pending_probes.clear()
            self.stats = {
                'total_sent': 0,
                'total_received': 0,
                'total_lost': 0,
                'bytes_sent': 0,
                'bytes_received': 0,
                'last_rtt_ms': 0,
                'last_jitter_ms': 0,
                'size_stats': {}
            }
            self.last_rtt_values.clear()
            logger.info("Statistics reset")

    def save_results(self, filepath: str):
        """ذخیره نتایج در فایل JSON"""
        stats = self.get_statistics()
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'configuration': {
                'interval_ms': self.interval_ms,
                'timeout_ms': self.timeout_ms,
                'size_mode': self.size_mode,
                'variable_sizes': self.variable_sizes if self.variable_sizes else []
            },
            'statistics': asdict(stats),
            'raw_data': [asdict(r) for r in self.get_raw_data()[-100:]]  # آخرین 100 پروب
        }
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved to {filepath}")


# Helper function for creating with profile
def create_probe_injector(master_port: str = None, 
                         slave_port: str = None,
                         profile_path: str = None,
                         size_mode: str = 'representative',
                         **kwargs) -> ProbeInjector:
    """Helper function to create ProbeInjector with profile"""
    
    # ایجاد پروفایل
    profile = MAVLinkProfile(profile_path)
    
    # ایجاد packet generator
    generator = PacketGenerator(profile)
    
    # باز کردن پورت‌های سریال اگر مشخص شده
    master_serial = None
    slave_serial = None
    
    if master_port:
        try:
            import serial
            master_serial = serial.Serial(
                port=master_port,
                baudrate=kwargs.get('baudrate', DEFAULT_BAUDRATE),
                timeout=0.1
            )
            logger.info(f"Master serial opened: {master_port}")
        except Exception as e:
            logger.error(f"Failed to open master port: {e}")
    
    if slave_port:
        try:
            import serial
            slave_serial = serial.Serial(
                port=slave_port,
                baudrate=kwargs.get('baudrate', DEFAULT_BAUDRATE),
                timeout=0.1
            )
            logger.info(f"Slave serial opened: {slave_port}")
        except Exception as e:
            logger.error(f"Failed to open slave port: {e}")
    
    # ایجاد ProbeInjector
    injector = ProbeInjector(
        master_serial=master_serial,
        slave_serial=slave_serial,
        packet_generator=generator,
        size_mode=size_mode,
        **kwargs
    )
    
    return injector


# بخش اصلی برای تست مستقل
if __name__ == "__main__":
    import argparse
    from datetime import datetime
    
    parser = argparse.ArgumentParser(description="P900 Probe Injector Test")
    parser.add_argument('--master', type=str, help='Master serial port')
    parser.add_argument('--slave', type=str, help='Slave serial port')
    parser.add_argument('--interval', type=int, default=100, help='Probe interval in ms')
    parser.add_argument('--timeout', type=int, default=500, help='Probe timeout in ms')
    parser.add_argument('--duration', type=int, default=10, help='Test duration in seconds')
    parser.add_argument('--size-mode', type=str, default='representative',
                       choices=['fixed', 'representative', 'realistic', 'random'],
                       help='Packet size mode')
    parser.add_argument('--fixed-size', type=int, default=108, help='Fixed packet size')
    parser.add_argument('--profile', type=str, help='Path to MAVLink profile JSON')
    parser.add_argument('--output', type=str, help='Output file for results')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print(" P900 Probe Injector - Variable Size Test")
    print("="*70)
    
    # ایجاد injector
    injector = create_probe_injector(
        master_port=args.master,
        slave_port=args.slave,
        profile_path=args.profile,
        size_mode=args.size_mode,
        interval_ms=args.interval,
        timeout_ms=args.timeout,
        fixed_size=args.fixed_size
    )
    
    print(f"\n⚙️  Configuration:")
    print(f"  Master Port: {args.master or 'None'}")
    print(f"  Slave Port: {args.slave or 'None'}")
    print(f"  Interval: {args.interval}ms")
    print(f"  Timeout: {args.timeout}ms")
    print(f"  Size Mode: {args.size_mode}")
    print(f"  Duration: {args.duration}s")
    
    if not args.master:
        print("\n⚠️  No serial ports specified. Running in demo mode...")
        
        # تست تولید پکت‌ها
        print("\n📦 Testing packet generation:")
        for i in range(5):
            size = injector._get_next_packet_size()
            probe_id = 1000 + i
            packet = injector._create_probe_packet(
                probe_id, 
                injector.PROBE_TYPE_REQUEST,
                size
            )
            print(f"  Probe {probe_id}: size={size}B, packet_len={len(packet)}B")
            
            # تست parse
            parsed = injector._parse_probe_packet(packet)
            if parsed:
                print(f"    ✓ Parsed successfully: ID={parsed['probe_id']}")
        
    else:
        # اجرای تست واقعی
        print(f"\n🚀 Starting probe injection test...")
        injector.start()
        
        # نمایش آمار دوره‌ای
        start_time = time.time()
        report_interval = 2  # هر 2 ثانیه
        
        try:
            while time.time() - start_time < args.duration:
                time.sleep(report_interval)
                
                stats = injector.get_statistics()
                elapsed = time.time() - start_time
                
                print(f"\n⏱️  Time: {elapsed:.1f}s")
                print(f"  Sent: {stats.total_sent} | "
                      f"Received: {stats.total_received} | "
                      f"Lost: {stats.total_lost}")
                
                if stats.total_received > 0:
                    print(f"  RTT: {stats.avg_rtt_ms:.2f}ms "
                          f"(min: {stats.min_rtt_ms:.2f}, "
                          f"max: {stats.max_rtt_ms:.2f})")
                    print(f"  Jitter: {stats.avg_jitter_ms:.2f}ms")
                
                # آمار بر حسب اندازه
                if stats.stats_by_size:
                    print(f"  By Size:")
                    for size, size_stat in sorted(stats.stats_by_size.items()):
                        if size_stat['sent'] > 0:
                            recv_rate = (size_stat['received']/size_stat['sent'])*100
                            avg_rtt = (size_stat['total_rtt']/size_stat['received'] 
                                      if size_stat['received'] > 0 else 0)
                            print(f"    {size:4}B: {recv_rate:5.1f}% success, "
                                  f"RTT: {avg_rtt:6.2f}ms")
        
        except KeyboardInterrupt:
            print("\n\n⚠️  Test interrupted by user")
        
        finally:
            # توقف و ذخیره نتایج
            print("\n🛑 Stopping injection...")
            injector.stop()
            
            # نتایج نهایی
            final_stats = injector.get_statistics()
            
            print("\n" + "="*70)
            print(" Final Results")
            print("="*70)
            print(f"Total Packets Sent: {final_stats.total_sent}")
            print(f"Total Packets Received: {final_stats.total_received}")
            print(f"Total Packets Lost: {final_stats.total_lost}")
            print(f"Loss Rate: {final_stats.loss_rate:.2f}%")
            
            if final_stats.total_received > 0:
                print(f"\nRTT Statistics:")
                print(f"  Average: {final_stats.avg_rtt_ms:.3f} ms")
                print(f"  Min: {final_stats.min_rtt_ms:.3f} ms")
                print(f"  Max: {final_stats.max_rtt_ms:.3f} ms")
                print(f"  Std Dev: {final_stats.std_rtt_ms:.3f} ms")
                print(f"  95th %ile: {final_stats.percentile_95_ms:.3f} ms")
                print(f"  99th %ile: {final_stats.percentile_99_ms:.3f} ms")
            
            # ذخیره نتایج
            if args.output:
                output_file = args.output
            else:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = f"probe_results_{timestamp}.json"
            
            injector.save_results(output_file)
            print(f"\n💾 Results saved to: {output_file}")
    
    print("\n✅ Test completed successfully!")
