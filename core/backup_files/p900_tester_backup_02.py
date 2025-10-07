#!/usr/bin/env python3
"""
P900 Network Latency Measurement Tool - Enhanced Version with Detailed Analysis
اندازه‌گیری دقیق تأخیر شبکه رادیویی P900 با محاسبه جداگانه تأخیر رفت و برگشت
Version: 2.0 - Full Featured with Visualizations
"""
import serial
import time
import struct
import threading
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
import queue
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logger
from utils.path_helper import create_result_path, get_timestamp
from utils.config import DEFAULT_BAUDRATE, DEFAULT_TIMEOUT

@dataclass
class DetailedLatencyMeasurement:
    """نتیجه اندازه‌گیری تأخیر با جزئیات کامل"""
    packet_id: int
    packet_size: int              # اضافه شده برای تست A
    t1_master_send: float         # زمان ارسال REQUEST از Master
    t2_slave_receive: float       # زمان دریافت REQUEST در Slave
    t3_slave_send: float          # زمان ارسال RESPONSE از Slave
    t4_master_receive: float      # زمان دریافت RESPONSE در Master
    forward_delay_ms: float       # تأخیر رفت (T2-T1)
    return_delay_ms: float        # تأخیر برگشت (T4-T3)
    rtt_ms: float                # کل RTT (T4-T1)
    processing_time_ms: float     # زمان پردازش در Slave (T3-T2)
    asymmetry_ms: float          # عدم تقارن (Forward - Return)
    status: str                  # "OK", "TIMEOUT", "MISMATCH"

class P900NetworkTesterEnhanced:
    """
    تستر پیشرفته برای اندازه‌گیری دقیق تأخیر شبکه P900
    با قابلیت محاسبه جداگانه تأخیر رفت و برگشت
    """

    # ثابت‌های پروتکل
    HEADER_SIZE = 20  # 2(marker) + 4(ID) + 1(type) + 12(timestamps) + 1(reserved)
    MIN_PACKET_SIZE = 28  # حداقل اندازه معقول برای پکت
    MAX_PACKET_SIZE = 279  # حداکثر اندازه برای تست

    REQUEST_MARKER = b'\xAA\x55'
    RESPONSE_MARKER = b'\x55\xAA'

    TYPE_REQUEST = 0x01
    TYPE_RESPONSE = 0x02

    def __init__(self, local_port: str, remote_port: str, baudrate: int = 57600):
        """
        Args:
            local_port: پورت متصل به رادیو محلی (Master) - COM5
            remote_port: پورت متصل به رادیو دور (Slave) - COM6
            baudrate: سرعت سریال
        """
        self.local_port = local_port
        self.remote_port = remote_port
        self.baudrate = baudrate

        # متغیرهای اندازه پکت (برای تست A)
        self.total_packet_size = 108  # اندازه پیش‌فرض
        self.payload_size = self.total_packet_size - self.HEADER_SIZE

        self.local_serial = None
        self.remote_serial = None

        self.measurements: List[DetailedLatencyMeasurement] = []
        self.response_queue = queue.Queue()
        self.request_timestamps = {}  # ذخیره T1 برای هر packet_id

        self.running = False
        self.slave_thread = None
        self.master_receiver_thread = None

        # شمارنده‌های دیباگ
        self.requests_sent = 0
        self.requests_received = 0
        self.responses_sent = 0
        self.responses_received = 0

        # Setup logger
        self.logger = setup_logger(self.__class__.__name__)

    def set_packet_size(self, size: int) -> bool:
        """
        تنظیم اندازه پکت برای تست
        
        Args:
            size: اندازه کل پکت به بایت (28-279)
            
        Returns:
            bool: موفقیت در تنظیم اندازه
        """
        if size < self.MIN_PACKET_SIZE or size > self.MAX_PACKET_SIZE:
            self.logger.error(f"Invalid packet size: {size}. Must be between {self.MIN_PACKET_SIZE}-{self.MAX_PACKET_SIZE}")
            return False
        
        self.total_packet_size = size
        self.payload_size = size - self.HEADER_SIZE
        self.logger.info(f"Packet size set to {size} bytes (payload: {self.payload_size} bytes)")
        return True

    def connect(self) -> bool:
        """اتصال به هر دو پورت"""
        success = True

        try:
            self.logger.info(f"🔌 Connecting to Master port: {self.local_port}...")
            self.local_serial = serial.Serial(
                port=self.local_port,
                baudrate=self.baudrate,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=0.1,
                write_timeout=1.0
            )

            if self.local_serial.is_open:
                self.local_serial.reset_input_buffer()
                self.local_serial.reset_output_buffer()
                self.logger.info(f"✅ Successfully connected to Master port: {self.local_port}")
            else:
                self.logger.error(f"❌ Failed to open Master port: {self.local_port}")
                success = False

        except Exception as e:
            self.logger.error(f"❌ Error connecting to Master port {self.local_port}: {e}")
            success = False

        try:
            self.logger.info(f"🔌 Connecting to Slave port: {self.remote_port}...")
            self.remote_serial = serial.Serial(
                port=self.remote_port,
                baudrate=self.baudrate,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=0.1,
                write_timeout=1.0
            )

            if self.remote_serial.is_open:
                self.remote_serial.reset_input_buffer()
                self.remote_serial.reset_output_buffer()
                self.logger.info(f"✅ Successfully connected to Slave port: {self.remote_port}")
            else:
                self.logger.error(f"❌ Failed to open Slave port: {self.remote_port}")
                success = False

        except Exception as e:
            self.logger.error(f"❌ Error connecting to Slave port {self.remote_port}: {e}")
            success = False

        if success:
            self.logger.info("✅ Both ports connected successfully!")
            self.logger.info("-" * 50)
            time.sleep(1.0)
        else:
            self.logger.error("❌ Connection failed! Please check your ports.")
            self.disconnect()

        return success

    def _create_packet(self, packet_id: int, packet_type: int,
                      t1: float = 0, t2: float = 0, t3: float = 0) -> bytes:
        """
        ایجاد پکت با ساختار جدید شامل timestamp های متعدد

        ساختار پکت:
        [Marker:2] + [PacketID:4] + [Type:1] + [T1:4] + [T2:4] + [T3:4] + [Reserved:1] + [Payload:N]
        """
        packet = bytearray()

        # Marker بر اساس نوع
        if packet_type == self.TYPE_REQUEST:
            packet.extend(self.REQUEST_MARKER)
        else:
            packet.extend(self.RESPONSE_MARKER)

        # Packet ID (4 bytes)
        packet.extend(struct.pack('<I', packet_id))

        # Type (1 byte)
        packet.append(packet_type)

        # Timestamps (هر کدام 4 bytes) - به microseconds تبدیل می‌شوند
        packet.extend(struct.pack('<I', int(t1 * 1_000_000) & 0xFFFFFFFF))
        packet.extend(struct.pack('<I', int(t2 * 1_000_000) & 0xFFFFFFFF))
        packet.extend(struct.pack('<I', int(t3 * 1_000_000) & 0xFFFFFFFF))

        # Reserved (1 byte)
        packet.append(0x00)

        # Payload (با اندازه متغیر)
        payload = bytes([(i + packet_id) % 256 for i in range(self.payload_size)])
        packet.extend(payload)

        return bytes(packet)

    def _inject_timestamp(self, packet: bytes, position: int, timestamp: float) -> bytes:
        """تزریق timestamp در موقعیت مشخص شده"""
        packet_array = bytearray(packet)
        timestamp_us = int(timestamp * 1_000_000) & 0xFFFFFFFF
        packet_array[position:position+4] = struct.pack('<I', timestamp_us)
        return bytes(packet_array)

    def _parse_packet(self, data: bytes) -> Optional[Dict]:
        """پارس کردن پکت دریافتی با استخراج تمام timestamp ها"""
        if len(data) < self.total_packet_size:
            return None

        # بررسی marker
        marker = data[:2]
        if marker == self.REQUEST_MARKER:
            expected_type = self.TYPE_REQUEST
            packet_type_str = "REQUEST"
        elif marker == self.RESPONSE_MARKER:
            expected_type = self.TYPE_RESPONSE
            packet_type_str = "RESPONSE"
        else:
            return None

        # استخراج فیلدها
        try:
            packet_id = struct.unpack('<I', data[2:6])[0]
            packet_type = data[6]

            # استخراج timestamps (از microseconds به seconds)
            t1_us = struct.unpack('<I', data[7:11])[0]
            t2_us = struct.unpack('<I', data[11:15])[0]
            t3_us = struct.unpack('<I', data[15:19])[0]

            payload = data[20:self.total_packet_size]

            if packet_type != expected_type:
                return None

            return {
                'packet_id': packet_id,
                'packet_type': packet_type_str,
                't1': t1_us / 1_000_000.0 if t1_us > 0 else 0,
                't2': t2_us / 1_000_000.0 if t2_us > 0 else 0,
                't3': t3_us / 1_000_000.0 if t3_us > 0 else 0,
                'payload': payload
            }
        except Exception:
            return None

    def _slave_loop(self):
        """حلقه Slave - دریافت REQUEST و ارسال RESPONSE با ثبت دقیق زمان‌ها"""
        buffer = bytearray()
        self.logger.info(f"🟢 Slave service started on {self.remote_port}")
        self.logger.info("   Waiting for REQUESTs...")

        while self.running:
            try:
                if self.remote_serial and self.remote_serial.in_waiting > 0:
                    data = self.remote_serial.read(self.remote_serial.in_waiting)
                    buffer.extend(data)

                    while len(buffer) >= self.total_packet_size:
                        marker_pos = buffer.find(self.REQUEST_MARKER)

                        if marker_pos == -1:
                            if len(buffer) > self.total_packet_size * 2:
                                buffer = bytearray()
                            break

                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]

                        if len(buffer) >= self.total_packet_size:
                            # ثبت زمان دریافت REQUEST (T2)
                            t2_slave_receive = time.perf_counter()

                            packet_data = bytes(buffer[:self.total_packet_size])
                            packet = self._parse_packet(packet_data)

                            if packet and packet['packet_type'] == "REQUEST":
                                self.requests_received += 1
                                packet_id = packet['packet_id']
                                t1_master_send = packet['t1']

                                # کمی پردازش (شبیه‌سازی)
                                time.sleep(0.0001)  # 100 microseconds

                                # ثبت زمان ارسال RESPONSE (T3)
                                t3_slave_send = time.perf_counter()

                                # ایجاد RESPONSE با تمام timestamps
                                response = self._create_packet(
                                    packet_id,
                                    self.TYPE_RESPONSE,
                                    t1=t1_master_send,
                                    t2=t2_slave_receive,
                                    t3=t3_slave_send
                                )

                                self.remote_serial.write(response)
                                self.remote_serial.flush()

                                self.responses_sent += 1

                                # محاسبه زمان پردازش
                                processing_ms = (t3_slave_send - t2_slave_receive) * 1000
                                self.logger.debug(f"   📨 Slave: REQ #{packet_id} → RESP (Process: {processing_ms:.3f}ms)")

                            buffer = buffer[self.total_packet_size:]

                time.sleep(0.00001)  # 10 microseconds

            except Exception as e:
                if self.running:
                    self.logger.error(f"   ❌ Slave error: {e}")
                    time.sleep(0.01)

        self.logger.info(f"🔴 Slave stopped (Received: {self.requests_received}, Sent: {self.responses_sent})")

    def _master_receiver_loop(self):
        """حلقه دریافت RESPONSE در Master با ثبت زمان دقیق"""
        buffer = bytearray()
        self.logger.info(f"🟢 Master receiver started on {self.local_port}")
        self.logger.info("   Waiting for RESPONSEs...")

        while self.running:
            try:
                if self.local_serial and self.local_serial.in_waiting > 0:
                    data = self.local_serial.read(self.local_serial.in_waiting)
                    buffer.extend(data)

                    while len(buffer) >= self.total_packet_size:
                        marker_pos = buffer.find(self.RESPONSE_MARKER)

                        if marker_pos == -1:
                            if len(buffer) > self.total_packet_size * 2:
                                buffer = bytearray()
                            break

                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]

                        if len(buffer) >= self.total_packet_size:
                            # ثبت زمان دریافت RESPONSE (T4)
                            t4_master_receive = time.perf_counter()

                            packet_data = bytes(buffer[:self.total_packet_size])
                            parsed = self._parse_packet(packet_data)

                            if parsed and parsed['packet_type'] == "RESPONSE":
                                self.responses_received += 1

                                # قرار دادن در صف برای پردازش
                                self.response_queue.put({
                                    'packet_id': parsed['packet_id'],
                                    't1': parsed['t1'],
                                    't2': parsed['t2'],
                                    't3': parsed['t3'],
                                    't4': t4_master_receive
                                })

                                self.logger.debug(f"   📩 Master: Got RESP #{parsed['packet_id']}")

                            buffer = buffer[self.total_packet_size:]

                time.sleep(0.00001)  # 10 microseconds

            except Exception as e:
                if self.running:
                    self.logger.error(f"   ❌ Master receiver error: {e}")
                    time.sleep(0.01)

        self.logger.info(f"🔴 Master receiver stopped (Received: {self.responses_received})")
    def measure_latency(self, num_packets: int = 100, interval_ms: float = 100) -> List[DetailedLatencyMeasurement]:
        """اجرای تست و اندازه‌گیری تأخیرها"""
        self.logger.info(f"🚀 Starting latency measurement: {num_packets} packets, interval {interval_ms} ms")
        self.measurements.clear()
        self.requests_sent = self.requests_received = self.responses_sent = self.responses_received = 0

        self.running = True
        self.slave_thread = threading.Thread(target=self._slave_loop)
        self.master_receiver_thread = threading.Thread(target=self._master_receiver_loop)
        self.slave_thread.start()
        self.master_receiver_thread.start()
        time.sleep(0.5)

        for packet_id in range(num_packets):
            # ساخت REQUEST و ثبت T1
            t1 = time.perf_counter()
            request = self._create_packet(packet_id, self.TYPE_REQUEST, t1=t1)

            while not self.response_queue.empty():
                self.response_queue.get()

            self.local_serial.write(request)
            self.local_serial.flush()
            self.requests_sent += 1

            try:
                resp_data = self.response_queue.get(timeout=1.0)  # تا 1 ثانیه منتظر پاسخ
                if resp_data['packet_id'] == packet_id:
                    forward_ms = (resp_data['t2'] - resp_data['t1']) * 1000
                    return_ms = (resp_data['t4'] - resp_data['t3']) * 1000
                    rtt_ms = (resp_data['t4'] - resp_data['t1']) * 1000
                    proc_ms = (resp_data['t3'] - resp_data['t2']) * 1000
                    asym_ms = forward_ms - return_ms

                    measurement = DetailedLatencyMeasurement(
                        packet_id=packet_id,
                        packet_size=self.total_packet_size,  # اضافه شده
                        t1_master_send=resp_data['t1'],
                        t2_slave_receive=resp_data['t2'],
                        t3_slave_send=resp_data['t3'],
                        t4_master_receive=resp_data['t4'],
                        forward_delay_ms=forward_ms,
                        return_delay_ms=return_ms,
                        rtt_ms=rtt_ms,
                        processing_time_ms=proc_ms,
                        asymmetry_ms=asym_ms,
                        status="OK"
                    )
                else:
                    measurement = DetailedLatencyMeasurement(
                        packet_id, self.total_packet_size, t1, 0, 0, 0, 0, 0, 0, 0, 0, "MISMATCH"
                    )

            except queue.Empty:
                measurement = DetailedLatencyMeasurement(
                    packet_id, self.total_packet_size, t1, 0, 0, 0, 0, 0, 0, 0, 0, "TIMEOUT"
                )

            self.measurements.append(measurement)
            if (packet_id + 1) % 10 == 0:
                self.logger.info(f"📊 Progress: {packet_id + 1}/{num_packets}")

            if packet_id < num_packets - 1:
                time.sleep(interval_ms / 1000)

        self.running = False
        self.slave_thread.join()
        self.master_receiver_thread.join()
        self.logger.info("✅ Measurement completed!")
        return self.measurements

    def measure_latency_multiple_sizes(self, packet_sizes: List[int], 
                                     packets_per_size: int = 50,
                                     interval_ms: float = 100) -> Dict[int, List[DetailedLatencyMeasurement]]:
        """
        اجرای تست با اندازه‌های مختلف پکت (برای تست A)
        
        Args:
            packet_sizes: لیست اندازه‌های پکت برای تست
            packets_per_size: تعداد پکت برای هر اندازه
            interval_ms: فاصله بین پکت‌ها
            
        Returns:
            دیکشنری از اندازه پکت به لیست اندازه‌گیری‌ها
        """
        all_results = {}
        
        for size in packet_sizes:
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Testing packet size: {size} bytes")
            self.logger.info(f"{'='*60}")
            
            if not self.set_packet_size(size):
                self.logger.error(f"Skipping invalid size: {size}")
                continue
                
            # اجرای تست برای این اندازه
            measurements = self.measure_latency(packets_per_size, interval_ms)
            all_results[size] = measurements
            
            # نمایش آمار مختصر
            ok_measurements = [m for m in measurements if m.status == "OK"]
            if ok_measurements:
                avg_forward = np.mean([m.forward_delay_ms for m in ok_measurements])
                avg_return = np.mean([m.return_delay_ms for m in ok_measurements])
                avg_rtt = np.mean([m.rtt_ms for m in ok_measurements])
                self.logger.info(f"Size {size}B: Avg Forward={avg_forward:.2f}ms, "
                               f"Return={avg_return:.2f}ms, RTT={avg_rtt:.2f}ms")
            
            # استراحت بین تست‌ها
            time.sleep(2)
            
        return all_results

    def get_statistics(self) -> Dict:
        """محاسبه آمار کلی تأخیرها"""
        ok = [m for m in self.measurements if m.status == "OK"]
        if not ok:
            return {
                'total_packets': len(self.measurements),
                'successful_packets': 0,
                'lost_packets': len(self.measurements),
                'packet_loss_rate': 100.0
            }
        
        def stats(vals): 
            return {
                'mean': np.mean(vals), 
                'median': np.median(vals), 
                'min': np.min(vals),
                'max': np.max(vals), 
                'std': np.std(vals),
                'p95': np.percentile(vals, 95), 
                'p99': np.percentile(vals, 99)
            }
        
        forward_vals = [m.forward_delay_ms for m in ok]
        return_vals = [m.return_delay_ms for m in ok]
        rtt_vals = [m.rtt_ms for m in ok]
        asym_vals = [m.asymmetry_ms for m in ok]
        proc_vals = [m.processing_time_ms for m in ok]
        
        jitter = [abs(ok[i].forward_delay_ms - ok[i-1].forward_delay_ms) for i in range(1, len(ok))]

        return {
            'total_packets': len(self.measurements),
            'successful_packets': len(ok),
            'lost_packets': len(self.measurements) - len(ok),
            'packet_loss_rate': ((len(self.measurements) - len(ok)) / len(self.measurements)) * 100,
            'forward': stats(forward_vals),
            'return': stats(return_vals),
            'rtt': stats(rtt_vals),
            'asymmetry': stats(asym_vals),
            'processing': stats(proc_vals),
            'jitter': {
                'mean': np.mean(jitter) if jitter else 0, 
                'max': np.max(jitter) if jitter else 0,
                'std': np.std(jitter) if jitter else 0
            }
        }


    def _plot_size_vs_latency(self, output_prefix: str):
        """رسم نمودار اثر اندازه پکت بر تأخیر (برای تست A)"""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('Packet Size Effect on Latency', fontsize=16, fontweight='bold')

        sizes = sorted(self.size_latency_results.keys())
        forward_means = []
        return_means = []
        rtt_means = []
        forward_stds = []
        return_stds = []
        
        for size in sizes:
            measurements = self.size_latency_results[size]
            ok_measurements = [m for m in measurements if m.status == "OK"]
            if ok_measurements:
                forward_means.append(np.mean([m.forward_delay_ms for m in ok_measurements]))
                return_means.append(np.mean([m.return_delay_ms for m in ok_measurements]))
                rtt_means.append(np.mean([m.rtt_ms for m in ok_measurements]))
                forward_stds.append(np.std([m.forward_delay_ms for m in ok_measurements]))
                return_stds.append(np.std([m.return_delay_ms for m in ok_measurements]))
            else:
                forward_means.append(0)
                return_means.append(0)
                rtt_means.append(0)
                forward_stds.append(0)
                return_stds.append(0)

        # 1. Forward/Return delay vs Size
        ax1.errorbar(sizes, forward_means, yerr=forward_stds, fmt='b-o', capsize=5, label='Forward')
        ax1.errorbar(sizes, return_means, yerr=return_stds, fmt='r-o', capsize=5, label='Return')
        ax1.set_xlabel('Packet Size (bytes)')
        ax1.set_ylabel('Delay (ms)')
        ax1.set_title('Forward/Return Delay vs Packet Size')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 2. RTT vs Size
        ax2.plot(sizes, rtt_means, 'g-o', linewidth=2, markersize=8)
        ax2.set_xlabel('Packet Size (bytes)')
        ax2.set_ylabel('RTT (ms)')
        ax2.set_title('RTT vs Packet Size')
        ax2.grid(True, alpha=0.3)

        # 3. Linear regression for model fitting
        from scipy import stats
        slope_f, intercept_f, r_value_f, _, _ = stats.linregress(sizes, forward_means)
        slope_r, intercept_r, r_value_r, _, _ = stats.linregress(sizes, return_means)
        
        ax3.scatter(sizes, forward_means, color='blue', label='Forward Data')
        ax3.scatter(sizes, return_means, color='red', label='Return Data')
        ax3.plot(sizes, [slope_f * s + intercept_f for s in sizes], 'b--', 
                label=f'Forward: y={slope_f:.4f}x+{intercept_f:.2f} (R²={r_value_f**2:.3f})')
        ax3.plot(sizes, [slope_r * s + intercept_r for s in sizes], 'r--',
                label=f'Return: y={slope_r:.4f}x+{intercept_r:.2f} (R²={r_value_r**2:.3f})')
        ax3.set_xlabel('Packet Size (bytes)')
        ax3.set_ylabel('Delay (ms)')
        ax3.set_title('Linear Model Fitting: delay = a + b*size')
        ax3.legend(fontsize=9)
        ax3.grid(True, alpha=0.3)

        # 4. Asymmetry vs Size
        asymmetries = [f - r for f, r in zip(forward_means, return_means)]
        ax4.plot(sizes, asymmetries, 'purple', linewidth=2, marker='o')
        ax4.axhline(y=0, color='black', linestyle='--', alpha=0.5)
        ax4.set_xlabel('Packet Size (bytes)')
        ax4.set_ylabel('Asymmetry (ms)')
        ax4.set_title('Path Asymmetry vs Packet Size')
        ax4.grid(True, alpha=0.3)

        plt.tight_layout()
        output_path = f"{output_prefix}_size_analysis.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        self.logger.info(f"📊 Size analysis plot saved to: {output_path}")

    def save_results(self, output_prefix: str):
        """
        ذخیره نتایج آزمایش در فایل‌های مختلف
        
        Args:
            output_prefix: پیشوند نام فایل خروجی
        """
        # محاسبه آمارها
        stats = self.get_statistics()
        
        # ایجاد اطلاعات کامل برای ذخیره
        test_info = {
            'timestamp': datetime.now().isoformat(),
            'master_port': self.local_port,
            'slave_port': self.remote_port,
            'baudrate': self.baudrate,
            'packet_size': self.total_packet_size
        }
        
        # تبدیل measurements به لیست دیکشنری
        measurements_list = []
        for m in self.measurements:
            measurements_list.append(asdict(m))
        
        # ساختار داده کامل
        full_data = {
            'test_info': test_info,
            'statistics': stats,
            'measurements': measurements_list
        }
        
        # 1. ذخیره JSON
        json_file = f"{output_prefix}.json"
        try:
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"✅ JSON saved: {json_file}")
        except Exception as e:
            self.logger.error(f"❌ Failed to save JSON: {e}")
        
        # 2. ذخیره خلاصه متنی
        summary_file = f"{output_prefix}_summary.txt"
        try:
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write("="*60 + "\n")
                f.write("P900 Network Test Results Summary\n")
                f.write("="*60 + "\n\n")
                
                # Test Information
                f.write("Test Configuration:\n")
                f.write("-"*40 + "\n")
                f.write(f"Timestamp: {test_info['timestamp']}\n")
                f.write(f"Master Port: {test_info['master_port']}\n")
                f.write(f"Slave Port: {test_info['slave_port']}\n")
                f.write(f"Baudrate: {test_info['baudrate']}\n")
                f.write(f"Packet Size: {test_info['packet_size']} bytes\n")
                f.write(f"Payload Size: {self.payload_size} bytes\n\n")
                
                # Overall Statistics
                f.write("Overall Statistics:\n")
                f.write("-"*40 + "\n")
                f.write(f"Total Packets: {stats['total_packets']}\n")
                f.write(f"Successful: {stats['successful_packets']}\n")
                f.write(f"Lost: {stats['lost_packets']}\n")
                f.write(f"Loss Rate: {stats['packet_loss_rate']:.2f}%\n\n")
                
                if stats['successful_packets'] > 0:
                    # Forward Delay
                    f.write("Forward Delay (Master → Slave) [ms]:\n")
                    f.write(f"  Mean:   {stats['forward']['mean']:.3f}\n")
                    f.write(f"  Median: {stats['forward']['median']:.3f}\n")
                    f.write(f"  Std:    {stats['forward']['std']:.3f}\n")
                    f.write(f"  Min:    {stats['forward']['min']:.3f}\n")
                    f.write(f"  Max:    {stats['forward']['max']:.3f}\n")
                    f.write(f"  P95:    {stats['forward']['p95']:.3f}\n")
                    f.write(f"  P99:    {stats['forward']['p99']:.3f}\n\n")
                    
                    # Return Delay
                    f.write("Return Delay (Slave → Master) [ms]:\n")
                    f.write(f"  Mean:   {stats['return']['mean']:.3f}\n")
                    f.write(f"  Median: {stats['return']['median']:.3f}\n")
                    f.write(f"  Std:    {stats['return']['std']:.3f}\n")
                    f.write(f"  Min:    {stats['return']['min']:.3f}\n")
                    f.write(f"  Max:    {stats['return']['max']:.3f}\n")
                    f.write(f"  P95:    {stats['return']['p95']:.3f}\n")
                    f.write(f"  P99:    {stats['return']['p99']:.3f}\n\n")
                    
                    # RTT
                    f.write("Round Trip Time (RTT) [ms]:\n")
                    f.write(f"  Mean:   {stats['rtt']['mean']:.3f}\n")
                    f.write(f"  Median: {stats['rtt']['median']:.3f}\n")
                    f.write(f"  Std:    {stats['rtt']['std']:.3f}\n")
                    f.write(f"  Min:    {stats['rtt']['min']:.3f}\n")
                    f.write(f"  Max:    {stats['rtt']['max']:.3f}\n")
                    f.write(f"  P95:    {stats['rtt']['p95']:.3f}\n")
                    f.write(f"  P99:    {stats['rtt']['p99']:.3f}\n\n")
                    
                    # Asymmetry
                    f.write("Path Asymmetry (Forward - Return) [ms]:\n")
                    f.write(f"  Mean:   {stats['asymmetry']['mean']:.3f}\n")
                    f.write(f"  Median: {stats['asymmetry']['median']:.3f}\n")
                    f.write(f"  Std:    {stats['asymmetry']['std']:.3f}\n")
                    f.write(f"  Min:    {stats['asymmetry']['min']:.3f}\n")
                    f.write(f"  Max:    {stats['asymmetry']['max']:.3f}\n\n")
                    
                    # Processing Time
                    f.write("Slave Processing Time [ms]:\n")
                    f.write(f"  Mean:   {stats['processing']['mean']:.3f}\n")
                    f.write(f"  Median: {stats['processing']['median']:.3f}\n")
                    f.write(f"  Std:    {stats['processing']['std']:.3f}\n")
                    f.write(f"  Min:    {stats['processing']['min']:.3f}\n")
                    f.write(f"  Max:    {stats['processing']['max']:.3f}\n\n")
                    
                    # Jitter
                    f.write("Jitter Statistics [ms]:\n")
                    f.write(f"  Mean:   {stats['jitter']['mean']:.3f}\n")
                    f.write(f"  Max:    {stats['jitter']['max']:.3f}\n")
                    f.write(f"  Std:    {stats['jitter']['std']:.3f}\n")
                    
            self.logger.info(f"✅ Summary saved: {summary_file}")
        except Exception as e:
            self.logger.error(f"❌ Failed to save summary: {e}")
        
        # 3. ذخیره داده‌های خام CSV
        csv_file = f"{output_prefix}_raw.csv"
        try:
            import csv
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                if self.measurements:
                    fieldnames = ['packet_id', 'packet_size', 'status', 
                                'forward_delay_ms', 'return_delay_ms', 'rtt_ms', 
                                'processing_time_ms', 'asymmetry_ms',
                                't1_master_send', 't2_slave_receive', 
                                't3_slave_send', 't4_master_receive']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for m in self.measurements:
                        writer.writerow({
                            'packet_id': m.packet_id,
                            'packet_size': m.packet_size,
                            'status': m.status,
                            'forward_delay_ms': m.forward_delay_ms,
                            'return_delay_ms': m.return_delay_ms,
                            'rtt_ms': m.rtt_ms,
                            'processing_time_ms': m.processing_time_ms,
                            'asymmetry_ms': m.asymmetry_ms,
                            't1_master_send': m.t1_master_send,
                            't2_slave_receive': m.t2_slave_receive,
                            't3_slave_send': m.t3_slave_send,
                            't4_master_receive': m.t4_master_receive
                        })
            self.logger.info(f"✅ CSV saved: {csv_file}")
        except Exception as e:
            self.logger.error(f"❌ Failed to save CSV: {e}")
        
        # 4. ✨ تولید نمودارها - این بخش مهمه!
        try:
            plot_file = self.plot_results(output_prefix)
            if plot_file:
                self.logger.info(f"✅ Plots saved: {plot_file}")
        except Exception as e:
            self.logger.error(f"❌ Failed to generate plots: {e}")
        
        # نمایش خلاصه در کنسول
        self.logger.info("="*50)
        self.logger.info("📊 TEST SUMMARY:")
        self.logger.info(f"   Total Packets: {stats['total_packets']}")
        self.logger.info(f"   Success Rate: {100 - stats['packet_loss_rate']:.1f}%")
        if stats['successful_packets'] > 0:
            self.logger.info(f"   RTT: {stats['rtt']['mean']:.2f} ± {stats['rtt']['std']:.2f} ms")
            self.logger.info(f"   Forward: {stats['forward']['mean']:.2f} ms")
            self.logger.info(f"   Return: {stats['return']['mean']:.2f} ms")
        self.logger.info("="*50)

        def plot_results(self, output_prefix: str = None) -> str:
            """
            رسم نمودارهای جامع نتایج تست
            
            Args:
                output_prefix: پیشوند نام فایل خروجی
                
            Returns:
                نام فایل نمودار ذخیره شده
            """
            if not self.measurements:
                self.logger.warning("No measurements to plot")
                return None
            
            # فیلتر کردن اندازه‌گیری‌های موفق
            ok_measurements = [m for m in self.measurements if m.status == "OK"]
            if not ok_measurements:
                self.logger.warning("No successful measurements to plot")
                return None
            
            # استخراج داده‌ها
            packet_ids = [m.packet_id for m in ok_measurements]
            rtts = [m.rtt_ms for m in ok_measurements]
            forward_delays = [m.forward_delay_ms for m in ok_measurements]
            return_delays = [m.return_delay_ms for m in ok_measurements]
            processing_times = [m.processing_time_ms for m in ok_measurements]
            asymmetries = [m.asymmetry_ms for m in ok_measurements]
            
            # پکت‌های گم‌شده
            lost_packets = [m for m in self.measurements if m.status != "OK"]
            lost_ids = [m.packet_id for m in lost_packets]
            
            # محاسبه jitter
            forward_jitter = []
            return_jitter = []
            for i in range(1, len(ok_measurements)):
                forward_jitter.append(abs(ok_measurements[i].forward_delay_ms - 
                                        ok_measurements[i-1].forward_delay_ms))
                return_jitter.append(abs(ok_measurements[i].return_delay_ms - 
                                    ok_measurements[i-1].return_delay_ms))
            
            # ایجاد figure با subplots
            fig = plt.figure(figsize=(20, 14))
            fig.suptitle(f'P900 Network Test Results - Packet Size: {self.total_packet_size} bytes', 
                        fontsize=16, fontweight='bold')
            
            # استفاده از GridSpec برای layout بهتر
            gs = gridspec.GridSpec(3, 3, hspace=0.3, wspace=0.3)
            
            # 1. RTT over Time
            ax1 = fig.add_subplot(gs[0, :])
            ax1.plot(packet_ids, rtts, 'b-', linewidth=1.5, alpha=0.7, label='RTT')
            ax1.scatter(packet_ids, rtts, c='blue', s=20, alpha=0.5)
            
            # نمایش پکت‌های گم‌شده
            if lost_ids:
                max_rtt = max(rtts) if rtts else 100
                for lost_id in lost_ids:
                    ax1.axvline(x=lost_id, color='red', linestyle='--', alpha=0.3)
                # اضافه کردن یک نمونه برای legend
                ax1.axvline(x=-1, color='red', linestyle='--', alpha=0.3, label=f'Lost ({len(lost_ids)})')
            
            # خط میانگین
            ax1.axhline(y=np.mean(rtts), color='g', linestyle='--', alpha=0.5, 
                    label=f'Mean: {np.mean(rtts):.2f}ms')
            ax1.axhline(y=np.median(rtts), color='orange', linestyle='--', alpha=0.5,
                    label=f'Median: {np.median(rtts):.2f}ms')
            
            ax1.set_xlabel('Packet ID')
            ax1.set_ylabel('RTT (ms)')
            ax1.set_title('Round Trip Time Over Time')
            ax1.grid(True, alpha=0.3)
            ax1.legend(loc='upper right')
            
            # 2. Forward vs Return Delay (Scatter)
            ax2 = fig.add_subplot(gs[1, 0])
            scatter = ax2.scatter(forward_delays, return_delays, 
                                c=packet_ids, cmap='viridis', 
                                s=30, alpha=0.6)
            ax2.set_xlabel('Forward Delay (ms)')
            ax2.set_ylabel('Return Delay (ms)')
            ax2.set_title('Forward vs Return Path Delay')
            ax2.grid(True, alpha=0.3)
            
            # خط y=x برای نمایش تقارن
            max_val = max(max(forward_delays), max(return_delays))
            min_val = min(min(forward_delays), min(return_delays))
            ax2.plot([min_val, max_val], [min_val, max_val], 'r--', alpha=0.3, label='y=x (symmetric)')
            ax2.legend()
            
            # رنگ‌بندی بر اساس packet ID
            cbar = plt.colorbar(scatter, ax=ax2)
            cbar.set_label('Packet ID')
            
            # 3. RTT Histogram
            ax3 = fig.add_subplot(gs[1, 1])
            n, bins, patches = ax3.hist(rtts, bins=30, edgecolor='black', alpha=0.7, color='blue')
            ax3.axvline(x=np.mean(rtts), color='red', linestyle='--', 
                    linewidth=2, label=f'Mean: {np.mean(rtts):.2f}ms')
            ax3.axvline(x=np.median(rtts), color='green', linestyle='--', 
                    linewidth=2, label=f'Median: {np.median(rtts):.2f}ms')
            ax3.axvline(x=np.percentile(rtts, 95), color='orange', linestyle='--',
                    linewidth=2, label=f'P95: {np.percentile(rtts, 95):.2f}ms')
            ax3.set_xlabel('RTT (ms)')
            ax3.set_ylabel('Frequency')
            ax3.set_title('RTT Distribution')
            ax3.legend()
            ax3.grid(True, alpha=0.3)
            
            # 4. Asymmetry Analysis
            ax4 = fig.add_subplot(gs[1, 2])
            ax4.plot(packet_ids, asymmetries, 'r-', linewidth=1, alpha=0.7)
            ax4.scatter(packet_ids, asymmetries, c='red', s=20, alpha=0.5)
            ax4.axhline(y=0, color='black', linestyle='-', alpha=0.3, linewidth=1)
            ax4.axhline(y=np.mean(asymmetries), color='blue', linestyle='--', 
                    alpha=0.5, label=f'Mean: {np.mean(asymmetries):.2f}ms')
            ax4.fill_between(packet_ids, asymmetries, 0, alpha=0.2, color='red')
            ax4.set_xlabel('Packet ID')
            ax4.set_ylabel('Asymmetry (ms)')
            ax4.set_title('Path Asymmetry (Forward - Return)')
            ax4.grid(True, alpha=0.3)
            ax4.legend()
            
            # 5. Processing Time at Slave
            ax5 = fig.add_subplot(gs[2, 0])
            ax5.plot(packet_ids, processing_times, 'g-', linewidth=1, alpha=0.7)
            ax5.scatter(packet_ids, processing_times, c='green', s=20, alpha=0.5)
            ax5.axhline(y=np.mean(processing_times), color='red', linestyle='--',
                    alpha=0.5, label=f'Mean: {np.mean(processing_times):.3f}ms')
            ax5.set_xlabel('Packet ID')
            ax5.set_ylabel('Processing Time (ms)')
            ax5.set_title('Slave Processing Time')
            ax5.grid(True, alpha=0.3)
            ax5.legend()
            
            # 6. Jitter Analysis
            ax6 = fig.add_subplot(gs[2, 1])
            if forward_jitter and return_jitter:
                jitter_ids = packet_ids[1:]  # جیتر برای پکت‌های 1 به بعد
                ax6.plot(jitter_ids, forward_jitter, 'b-', linewidth=1, 
                        alpha=0.7, label='Forward Jitter')
                ax6.plot(jitter_ids, return_jitter, 'r-', linewidth=1, 
                        alpha=0.7, label='Return Jitter')
                ax6.set_xlabel('Packet ID')
                ax6.set_ylabel('Jitter (ms)')
                ax6.set_title('Jitter Analysis')
                ax6.grid(True, alpha=0.3)
                ax6.legend()
            else:
                ax6.text(0.5, 0.5, 'Not enough data for jitter', 
                        ha='center', va='center', transform=ax6.transAxes)
            
            # 7. CDF of RTT
            ax7 = fig.add_subplot(gs[2, 2])
            sorted_rtts = np.sort(rtts)
            cdf = np.arange(1, len(sorted_rtts) + 1) / len(sorted_rtts) * 100
            ax7.plot(sorted_rtts, cdf, 'b-', linewidth=2)
            ax7.set_xlabel('RTT (ms)')
            ax7.set_ylabel('Cumulative Probability (%)')
            ax7.set_title('RTT Cumulative Distribution (CDF)')
            ax7.grid(True, alpha=0.3)
            
            # نمایش percentiles مهم
            for p in [50, 90, 95, 99]:
                val = np.percentile(rtts, p)
                ax7.axhline(y=p, color='gray', linestyle=':', alpha=0.3)
                ax7.axvline(x=val, color='red', linestyle=':', alpha=0.3)
                ax7.text(val, p, f'  P{p}: {val:.1f}ms', fontsize=8, va='center')
            
            # اطلاعات آماری در پایین
            stats_text = (
                f"Packets: Sent={len(self.measurements)}, Success={len(ok_measurements)}, "
                f"Lost={len(lost_packets)} ({len(lost_packets)/len(self.measurements)*100:.1f}%)\n"
                f"RTT: Mean={np.mean(rtts):.2f}±{np.std(rtts):.2f}ms, "
                f"Min={np.min(rtts):.2f}ms, Max={np.max(rtts):.2f}ms, "
                f"P95={np.percentile(rtts, 95):.2f}ms, P99={np.percentile(rtts, 99):.2f}ms"
            )
            fig.text(0.5, 0.02, stats_text, ha='center', fontsize=10, 
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
            
            # ذخیره نمودار
            if output_prefix:
                plot_file = f"{output_prefix}_analysis.png"
            else:
                plot_file = f"p900_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_analysis.png"
            
            plt.tight_layout()
            plt.savefig(plot_file, dpi=150, bbox_inches='tight')
            plt.close(fig)
            
            self.logger.info(f"📊 Plot saved to: {plot_file}")
            return plot_file

    def save_test_a_results(self, results: Dict[int, List[DetailedLatencyMeasurement]], 
                           output_prefix: str):
        """ذخیره نتایج تست A (اثر اندازه پکت)"""
        # ذخیره برای استفاده در plot
        self.size_latency_results = results
        
        # محاسبه مدل خطی
        sizes = []
        forward_means = []
        return_means = []
        
        for size, measurements in sorted(results.items()):
            ok_measurements = [m for m in measurements if m.status == "OK"]
            if ok_measurements:
                sizes.append(size)
                forward_means.append(np.mean([m.forward_delay_ms for m in ok_measurements]))
                return_means.append(np.mean([m.return_delay_ms for m in ok_measurements]))
        
        if len(sizes) >= 2:
            from scipy import stats
            slope_f, intercept_f, r_value_f, _, _ = stats.linregress(sizes, forward_means)
            slope_r, intercept_r, r_value_r, _, _ = stats.linregress(sizes, return_means)
            
            model_data = {
                'forward_model': {
                    'equation': f'delay = {intercept_f:.3f} + {slope_f:.6f} * size',
                    'a': intercept_f,
                    'b': slope_f,
                    'r_squared': r_value_f**2
                },
                'return_model': {
                    'equation': f'delay = {intercept_r:.3f} + {slope_r:.6f} * size',
                    'a': intercept_r,
                    'b': slope_r,
                    'r_squared': r_value_r**2
                }
            }
        else:
            model_data = {'error': 'Not enough data points for model fitting'}
        
        # ذخیره نتایج
        output_data = {
            'test_type': 'A - Packet Size Effect',
            'timestamp': datetime.now().isoformat(),
            'configuration': {
                'master_port': self.local_port,
                'slave_port': self.remote_port,
                'baudrate': self.baudrate,
                'tested_sizes': sorted(results.keys())
            },
            'linear_models': model_data,
            'detailed_results': {}
        }
        
        for size, measurements in sorted(results.items()):
            ok_measurements = [m for m in measurements if m.status == "OK"]
            if ok_measurements:
                output_data['detailed_results'][size] = {
                    'success_rate': (len(ok_measurements) / len(measurements)) * 100,
                    'forward_delay': {
                        'mean': np.mean([m.forward_delay_ms for m in ok_measurements]),
                        'std': np.std([m.forward_delay_ms for m in ok_measurements]),
                        'min': np.min([m.forward_delay_ms for m in ok_measurements]),
                        'max': np.max([m.forward_delay_ms for m in ok_measurements])
                    },
                    'return_delay': {
                        'mean': np.mean([m.return_delay_ms for m in ok_measurements]),
                        'std': np.std([m.return_delay_ms for m in ok_measurements]),
                        'min': np.min([m.return_delay_ms for m in ok_measurements]),
                        'max': np.max([m.return_delay_ms for m in ok_measurements])
                    },
                    'rtt': {
                        'mean': np.mean([m.rtt_ms for m in ok_measurements]),
                        'std': np.std([m.rtt_ms for m in ok_measurements]),
                        'min': np.min([m.rtt_ms for m in ok_measurements]),
                        'max': np.max([m.rtt_ms for m in ok_measurements])
                    }
                }
        
        output_file = f"{output_prefix}_test_a_results.json"
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        self.logger.info(f"📁 Test A results saved to: {output_file}")
        
        # رسم نمودارها
        self._plot_size_vs_latency(output_prefix)

    def disconnect(self):
        """قطع اتصال از پورت‌ها"""
        if self.local_serial and self.local_serial.is_open:
            self.local_serial.close()
            self.logger.info(f"🔌 Disconnected from {self.local_port}")
        
        if self.remote_serial and self.remote_serial.is_open:
            self.remote_serial.close()
            self.logger.info(f"🔌 Disconnected from {self.remote_port}")

def main():
    """نقطه ورود برنامه"""
    # تنظیمات
    MASTER_PORT = "COM5"  # تنظیم کنید
    SLAVE_PORT = "COM6"   # تنظیم کنید
    BAUDRATE = 57600
    
    # ایجاد نمونه تستر
    tester = P900NetworkTesterEnhanced(MASTER_PORT, SLAVE_PORT, BAUDRATE)
    
    if not tester.connect():
        print("Failed to connect to ports!")
        return
    
    try:
        # تست A: اثر اندازه پکت
        print("\n" + "="*60)
        print("Starting Test A: Packet Size Effect")
        print("="*60)
        
        # اندازه‌های مختلف برای تست (8 تا 279 بایت)
        packet_sizes = list(range(28, 280, 20))  # 28, 48, 68, ..., 268
        
        # اجرای تست
        results = tester.measure_latency_multiple_sizes(
            packet_sizes=packet_sizes,
            packets_per_size=50,
            interval_ms=100
        )
        
        # ذخیره نتایج
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_prefix = f"p900_test_a_{timestamp}"
        tester.save_test_a_results(results, output_prefix)
        
        print("\n✅ Test A completed successfully!")
        
    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tester.disconnect()

if __name__ == "__main__":
    main()
