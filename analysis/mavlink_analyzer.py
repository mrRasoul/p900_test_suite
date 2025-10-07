#!/usr/bin/env python3
"""
MAVLink Traffic Logger and Analyzer
ثبت و تحلیل ترافیک MAVLink برای استفاده در تست‌های تأخیر P900
Version: 1.0 - Complete Edition
Compatible with: rtt_newlogic_test03.py
"""

import serial
import time
import struct
import json
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
import threading
import queue
import os
import sys

@dataclass
class MAVLinkPacket:
    """ساختار پکت MAVLink ضبط شده"""
    timestamp: float          # زمان دریافت (از شروع logging)
    absolute_time: float      # زمان مطلق سیستم
    size: int                # اندازه پکت به بایت
    msg_id: int              # MAVLink message ID
    seq: int                 # Sequence number
    sys_id: int              # System ID
    comp_id: int             # Component ID
    raw_data: bytes          # داده خام
    direction: str           # 'RX' or 'TX'
    
@dataclass
class TrafficStatistics:
    """آمار ترافیک MAVLink"""
    message_type: str
    msg_id: int
    count: int
    total_bytes: int
    avg_size: float
    min_size: int
    max_size: int
    frequency_hz: float
    avg_interval_ms: float
    std_interval_ms: float
    size_samples: List[int]
    interval_samples: List[float]

class MAVLinkTrafficLogger:
    """
    Logger برای ضبط و تحلیل ترافیک MAVLink
    طراحی شده برای شناسایی الگوهای ترافیک جهت تست تأخیر P900
    """
    
    # MAVLink v1.0 protocol constants
    MAVLINK_STX = 0xFE
    MAVLINK_STX_V2 = 0xFD
    HEADER_LEN_V1 = 6
    HEADER_LEN_V2 = 10
    CHECKSUM_LEN = 2
    
    # Common MAVLink message IDs and names
    MESSAGE_NAMES = {
        0: 'HEARTBEAT',
        1: 'SYS_STATUS', 
        2: 'SYSTEM_TIME',
        24: 'GPS_RAW_INT',
        27: 'RAW_IMU',
        30: 'ATTITUDE',
        32: 'LOCAL_POSITION_NED',
        33: 'GLOBAL_POSITION_INT',
        35: 'RC_CHANNELS_RAW',
        36: 'SERVO_OUTPUT_RAW',
        42: 'MISSION_CURRENT',
        62: 'NAV_CONTROLLER_OUTPUT',
        65: 'RC_CHANNELS',
        74: 'VFR_HUD',
        76: 'COMMAND_LONG',
        77: 'COMMAND_ACK',
        83: 'ATTITUDE_TARGET',
        84: 'POSITION_TARGET_LOCAL_NED',
        87: 'POSITION_TARGET_GLOBAL_INT',
        105: 'HIGHRES_IMU',
        111: 'TIMESYNC',
        116: 'SCALED_IMU2',
        141: 'ALTITUDE',
        147: 'BATTERY_STATUS',
        166: 'WIND',
        230: 'ESTIMATOR_STATUS',
        241: 'VIBRATION',
        253: 'STATUSTEXT',
        254: 'DEBUG'
    }
    
    def __init__(self, port: str, baudrate: int = 57600, buffer_size: int = 10000):
        """
        Args:
            port: Serial port (e.g., 'COM5' or '/dev/ttyUSB0')
            baudrate: Baud rate (typically 57600 for telemetry)
            buffer_size: Maximum packets to keep in memory
        """
        self.port = port
        self.baudrate = baudrate
        self.buffer_size = buffer_size
        
        self.serial_conn = None
        self.packets: List[MAVLinkPacket] = []
        self.rx_buffer = bytearray()
        
        self.logging = False
        self.start_time = None
        self.log_thread = None
        self.packet_queue = queue.Queue()
        
        # آمار real-time
        self.bytes_received = 0
        self.packets_received = 0
        self.packets_lost = 0
        self.last_seq = {}  # برای تشخیص packet loss
        
    def connect(self) -> bool:
        """اتصال به پورت سریال"""
        try:
            print(f"🔌 Connecting to {self.port} at {self.baudrate} baud...")
            
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=0.01
            )
            
            if self.serial_conn.is_open:
                self.serial_conn.reset_input_buffer()
                print(f"✅ Connected to {self.port}")
                return True
                
        except serial.SerialException as e:
            print(f"❌ Failed to connect: {e}")
            return False
            
        return False
        
    def disconnect(self):
        """قطع اتصال از پورت سریال"""
        if self.serial_conn and self.serial_conn.is_open:
            self.stop_logging()  # اطمینان از توقف logging
            self.serial_conn.close()
            print(f"🔌 Disconnected from {self.port}")
            
    def _parse_mavlink_v1(self, data: bytes, offset: int) -> Optional[MAVLinkPacket]:
        """پارس پکت MAVLink v1"""
        if len(data) < offset + self.HEADER_LEN_V1:
            return None
            
        # Extract header
        payload_len = data[offset + 1]
        seq = data[offset + 2]
        sys_id = data[offset + 3]
        comp_id = data[offset + 4]
        msg_id = data[offset + 5]
        
        # محاسبه طول کل پکت
        packet_len = self.HEADER_LEN_V1 + payload_len + self.CHECKSUM_LEN
        
        if len(data) < offset + packet_len:
            return None
            
        # استخراج پکت کامل
        packet_data = data[offset:offset + packet_len]
        
        # ایجاد packet object
        return MAVLinkPacket(
            timestamp=time.perf_counter() - self.start_time if self.start_time else 0,
            absolute_time=time.time(),
            size=packet_len,
            msg_id=msg_id,
            seq=seq,
            sys_id=sys_id,
            comp_id=comp_id,
            raw_data=bytes(packet_data),
            direction='RX'
        )
        
    def _parse_mavlink_v2(self, data: bytes, offset: int) -> Optional[MAVLinkPacket]:
        """پارس پکت MAVLink v2"""
        if len(data) < offset + self.HEADER_LEN_V2:
            return None
            
        # Extract header
        payload_len = data[offset + 1]
        incompat_flags = data[offset + 2]
        compat_flags = data[offset + 3]
        seq = data[offset + 4]
        sys_id = data[offset + 5]
        comp_id = data[offset + 6]
        msg_id = struct.unpack('<I', data[offset+7:offset+10] + b'\x00')[0]
        
        # محاسبه طول کل پکت
        packet_len = self.HEADER_LEN_V2 + payload_len + self.CHECKSUM_LEN
        if incompat_flags & 0x01:  # Signature present
            packet_len += 13
            
        if len(data) < offset + packet_len:
            return None
            
        # استخراج پکت کامل
        packet_data = data[offset:offset + packet_len]
        
        return MAVLinkPacket(
            timestamp=time.perf_counter() - self.start_time if self.start_time else 0,
            absolute_time=time.time(),
            size=packet_len,
            msg_id=msg_id,
            seq=seq,
            sys_id=sys_id,
            comp_id=comp_id,
            raw_data=bytes(packet_data),
            direction='RX'
        )
        
    def _logging_thread(self):
        """Thread اصلی برای logging"""
        print("📡 Logging thread started...")
        
        while self.logging:
            try:
                # خواندن داده از سریال
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    new_data = self.serial_conn.read(self.serial_conn.in_waiting)
                    self.rx_buffer.extend(new_data)
                    self.bytes_received += len(new_data)
                    
                    # پردازش buffer
                    self._process_buffer()
                    
                # پردازش پکت‌های در صف
                try:
                    while not self.packet_queue.empty():
                        packet = self.packet_queue.get_nowait()
                        self.packets.append(packet)
                        
                        # حفظ buffer size
                        if len(self.packets) > self.buffer_size:
                            self.packets.pop(0)
                            
                except queue.Empty:
                    pass
                    
                time.sleep(0.001)  # 1ms
                
            except Exception as e:
                if self.logging:  # فقط در صورت فعال بودن logging
                    print(f"❌ Logging error: {e}")
                
        print("🛑 Logging thread stopped")
        
    def _process_buffer(self):
        """پردازش buffer و استخراج پکت‌های MAVLink"""
        while len(self.rx_buffer) > 0:
            # جستجوی MAVLink start byte
            stx_v1 = self.rx_buffer.find(self.MAVLINK_STX)
            stx_v2 = self.rx_buffer.find(self.MAVLINK_STX_V2)
            
            # پیدا کردن نزدیک‌ترین start byte
            if stx_v1 == -1 and stx_v2 == -1:
                # No valid start found, clear buffer if too large
                if len(self.rx_buffer) > 1000:
                    self.rx_buffer = bytearray()
                break
                
            # تعیین کدام نسخه
            if stx_v1 != -1 and (stx_v2 == -1 or stx_v1 < stx_v2):
                # MAVLink v1
                packet = self._parse_mavlink_v1(self.rx_buffer, stx_v1)
                if packet:
                    self.packets_received += 1
                    self._check_sequence(packet)
                    self.packet_queue.put(packet)
                    self.rx_buffer = self.rx_buffer[stx_v1 + packet.size:]
                else:
                    # Not enough data yet
                    break
                    
            else:
                # MAVLink v2
                packet = self._parse_mavlink_v2(self.rx_buffer, stx_v2)
                if packet:
                    self.packets_received += 1
                    self._check_sequence(packet)
                    self.packet_queue.put(packet)
                    self.rx_buffer = self.rx_buffer[stx_v2 + packet.size:]
                else:
                    break
                    
    def _check_sequence(self, packet: MAVLinkPacket):
        """بررسی sequence برای تشخیص packet loss"""
        key = (packet.sys_id, packet.comp_id)
        
        if key in self.last_seq:
            expected = (self.last_seq[key] + 1) % 256
            if packet.seq != expected:
                lost = (packet.seq - expected) % 256
                self.packets_lost += lost
                
        self.last_seq[key] = packet.seq
        
    def start_logging(self, duration_seconds: Optional[float] = None):
        """
        شروع logging
        
        Args:
            duration_seconds: مدت زمان logging (None = تا فراخوانی stop)
        """
        if self.logging:
            print("⚠️ Already logging!")
            return
            
        if not self.serial_conn or not self.serial_conn.is_open:
            print("❌ Not connected!")
            return
            
        # Reset everything
        self.packets.clear()
        self.rx_buffer = bytearray()
        self.bytes_received = 0
        self.packets_received = 0
        self.packets_lost = 0
        self.last_seq.clear()
        
        self.start_time = time.perf_counter()
        self.logging = True
        
        # شروع logging thread
        self.log_thread = threading.Thread(target=self._logging_thread)
        self.log_thread.daemon = True
        self.log_thread.start()
        
        print(f"🔴 Started logging MAVLink traffic...")
        
        if duration_seconds:
            print(f"   Will stop after {duration_seconds} seconds")
            time.sleep(duration_seconds)
            self.stop_logging()
    def stop_logging(self):
        """توقف logging"""
        if not self.logging:
            return
            
        self.logging = False
        
        if self.log_thread:
            self.log_thread.join(timeout=2)
            
        duration = time.perf_counter() - self.start_time if self.start_time else 0
        
        print(f"⭕ Stopped logging")
        print(f"   Duration: {duration:.1f} seconds")
        print(f"   Packets captured: {len(self.packets)}")
        print(f"   Total bytes: {self.bytes_received}")
        print(f"   Packets lost: {self.packets_lost}")
        
    def analyze_traffic(self) -> Dict[int, TrafficStatistics]:
        """
        تحلیل ترافیک ضبط شده
        
        Returns:
            دیکشنری از آمار برای هر message ID
        """
        if not self.packets:
            print("⚠️ No packets to analyze!")
            return {}
            
        print("\n📊 Analyzing captured traffic...")
        
        # گروه‌بندی بر اساس message ID
        messages = {}
        
        for packet in self.packets:
            mid = packet.msg_id
            name = self.MESSAGE_NAMES.get(mid, f"MSG_{mid}")
            if mid not in messages:
                messages[mid] = {
                    "name": name,
                    "count": 0,
                    "bytes": 0,
                    "sizes": [],
                    "times": []
                }
            rec = messages[mid]
            rec["count"] += 1
            rec["bytes"] += packet.size
            rec["sizes"].append(packet.size)
            rec["times"].append(packet.timestamp)

        stats = {}
        for mid, rec in messages.items():
            if rec["count"] > 1:
                intervals = np.diff(rec["times"])
                avg_interval = np.mean(intervals) * 1000.0
                std_interval = np.std(intervals) * 1000.0
                freq = 1.0 / np.mean(intervals) if np.mean(intervals) > 0 else 0.0
            else:
                avg_interval = 0
                std_interval = 0
                freq = 0

            stats[mid] = TrafficStatistics(
                message_type=rec["name"],
                msg_id=mid,
                count=rec["count"],
                total_bytes=rec["bytes"],
                avg_size=float(np.mean(rec["sizes"])),
                min_size=int(np.min(rec["sizes"])),
                max_size=int(np.max(rec["sizes"])),
                frequency_hz=freq,
                avg_interval_ms=avg_interval,
                std_interval_ms=std_interval,
                size_samples=rec["sizes"],
                interval_samples=list(intervals) if rec["count"] > 1 else []
            )

        return stats

    def save_statistics(self, stats: Dict[int, TrafficStatistics], output_prefix: str):
        """ذخیره آمار در فایل JSON و چاپ خلاصه"""
        out_data = {mid: asdict(stat) for mid, stat in stats.items()}
        json_path = f"{output_prefix}_traffic_stats.json"
        with open(json_path, "w") as f:
            json.dump(out_data, f, indent=2)
        txt_path = f"{output_prefix}_traffic_summary.txt"
        with open(txt_path, "w") as f:
            f.write(f"MAVLink Traffic Summary - {datetime.now().isoformat()}\n")
            f.write("="*60 + "\n")
            for mid, stat in stats.items():
                f.write(f"[{mid:3}] {stat.message_type:<30} Count:{stat.count:5} "
                        f"AvgSize:{stat.avg_size:.1f} "
                        f"Freq:{stat.frequency_hz:.2f}Hz\n")
        print(f"✅ Statistics saved to {json_path} and {txt_path}")

    def plot_message_size_distribution(self, stats: Dict[int, TrafficStatistics]):
        """نمایش توزیع اندازه پیام‌ها"""
        if not stats:
            print("⚠️ No data to plot!")
            return
        plt.figure(figsize=(10, 6))
        mids = [stat.msg_id for stat in stats.values()]
        avgs = [stat.avg_size for stat in stats.values()]
        plt.bar(mids, avgs)
        plt.xlabel("Message ID")
        plt.ylabel("Average size (bytes)")
        plt.title("MAVLink Message Size Distribution")
        plt.grid(True, linestyle="--", alpha=0.5)
        plt.tight_layout()
        plt.show()

def main():
    PORT = "COM5"
    BAUD = 57600
    logger = MAVLinkTrafficLogger(PORT, BAUD)
    if not logger.connect():
        return
    try:
        logger.start_logging(duration_seconds=10)
        stats = logger.analyze_traffic()
        logger.save_statistics(stats, f"mavlink_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        logger.plot_message_size_distribution(stats)
    finally:
        logger.disconnect()

if __name__ == "__main__":
    main()
