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
    t1_master_send: float      # زمان ارسال REQUEST از Master
    t2_slave_receive: float    # زمان دریافت REQUEST در Slave
    t3_slave_send: float       # زمان ارسال RESPONSE از Slave
    t4_master_receive: float   # زمان دریافت RESPONSE در Master
    forward_delay_ms: float    # تأخیر رفت (T2-T1)
    return_delay_ms: float     # تأخیر برگشت (T4-T3)
    rtt_ms: float             # کل RTT (T4-T1)
    processing_time_ms: float  # زمان پردازش در Slave (T3-T2)
    asymmetry_ms: float       # عدم تقارن (Forward - Return)
    status: str               # "OK", "TIMEOUT", "MISMATCH"

class P900NetworkTesterEnhanced:
    """
    تستر پیشرفته برای اندازه‌گیری دقیق تأخیر شبکه P900
    با قابلیت محاسبه جداگانه تأخیر رفت و برگشت
    """

    # ثابت‌های پروتکل
    HEADER_SIZE = 20  # 2(marker) + 4(ID) + 1(type) + 12(timestamps) + 1(reserved)
    PAYLOAD_SIZE = 88  # برای رسیدن به 108 بایت کل
    TOTAL_PACKET_SIZE = 108

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

    def connect(self) -> bool:
        """اتصال به هر دو پورت"""
        success = True
        
        try:
            print(f"🔌 Connecting to Master port: {self.local_port}...")
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
                print(f"✅ Successfully connected to Master port: {self.local_port}")
            else:
                print(f"❌ Failed to open Master port: {self.local_port}")
                success = False
                
        except Exception as e:
            print(f"❌ Error connecting to Master port {self.local_port}: {e}")
            success = False

        try:
            print(f"🔌 Connecting to Slave port: {self.remote_port}...")
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
                print(f"✅ Successfully connected to Slave port: {self.remote_port}")
            else:
                print(f"❌ Failed to open Slave port: {self.remote_port}")
                success = False
                
        except Exception as e:
            print(f"❌ Error connecting to Slave port {self.remote_port}: {e}")
            success = False

        if success:
            print("✅ Both ports connected successfully!")
            print("-" * 50)
            time.sleep(1.0)
        else:
            print("❌ Connection failed! Please check your ports.")
            self.disconnect()
            
        return success

    def _create_packet(self, packet_id: int, packet_type: int, 
                      t1: float = 0, t2: float = 0, t3: float = 0) -> bytes:
        """
        ایجاد پکت با ساختار جدید شامل timestamp های متعدد
        
        ساختار پکت (108 بایت):
        [Marker:2] + [PacketID:4] + [Type:1] + [T1:4] + [T2:4] + [T3:4] + [Reserved:1] + [Payload:88]
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

        # Payload (test pattern)
        payload = bytes([(i + packet_id) % 256 for i in range(self.PAYLOAD_SIZE)])
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
        if len(data) < self.TOTAL_PACKET_SIZE:
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
            
            payload = data[20:self.TOTAL_PACKET_SIZE]

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
        print(f"🟢 Slave service started on {self.remote_port}")
        print("   Waiting for REQUESTs...")

        while self.running:
            try:
                if self.remote_serial and self.remote_serial.in_waiting > 0:
                    data = self.remote_serial.read(self.remote_serial.in_waiting)
                    buffer.extend(data)

                    while len(buffer) >= self.TOTAL_PACKET_SIZE:
                        marker_pos = buffer.find(self.REQUEST_MARKER)
                        
                        if marker_pos == -1:
                            if len(buffer) > self.TOTAL_PACKET_SIZE * 2:
                                buffer = bytearray()
                            break

                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]

                        if len(buffer) >= self.TOTAL_PACKET_SIZE:
                            # ثبت زمان دریافت REQUEST (T2)
                            t2_slave_receive = time.perf_counter()
                            
                            packet_data = bytes(buffer[:self.TOTAL_PACKET_SIZE])
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
                                print(f"   📨 Slave: REQ #{packet_id} → RESP (Process: {processing_ms:.3f}ms)")

                            buffer = buffer[self.TOTAL_PACKET_SIZE:]

                time.sleep(0.00001)  # 10 microseconds

            except Exception as e:
                if self.running:
                    print(f"   ❌ Slave error: {e}")
                    time.sleep(0.01)

        print(f"🔴 Slave stopped (Received: {self.requests_received}, Sent: {self.responses_sent})")
    def _master_receiver_loop(self):
        """حلقه دریافت RESPONSE در Master با ثبت زمان دقیق"""
        buffer = bytearray()
        print(f"🟢 Master receiver started on {self.local_port}")
        print("   Waiting for RESPONSEs...")

        while self.running:
            try:
                if self.local_serial and self.local_serial.in_waiting > 0:
                    data = self.local_serial.read(self.local_serial.in_waiting)
                    buffer.extend(data)

                    while len(buffer) >= self.TOTAL_PACKET_SIZE:
                        marker_pos = buffer.find(self.RESPONSE_MARKER)
                        
                        if marker_pos == -1:
                            if len(buffer) > self.TOTAL_PACKET_SIZE * 2:
                                buffer = bytearray()
                            break

                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]

                        if len(buffer) >= self.TOTAL_PACKET_SIZE:
                            # ثبت زمان دریافت RESPONSE (T4)
                            t4_master_receive = time.perf_counter()
                            
                            packet_data = bytes(buffer[:self.TOTAL_PACKET_SIZE])
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
                                
                                print(f"   📩 Master: Got RESP #{parsed['packet_id']}")


                            buffer = buffer[self.TOTAL_PACKET_SIZE:]

                time.sleep(0.00001)  # 10 microseconds

            except Exception as e:
                if self.running:
                    print(f"   ❌ Master receiver error: {e}")
                    time.sleep(0.01)

        print(f"🔴 Master receiver stopped (Received: {self.responses_received})")

    def measure_latency(self, num_packets: int = 100, interval_ms: float = 100) -> List[DetailedLatencyMeasurement]:
        """اجرای تست و اندازه‌گیری تأخیرها"""
        print(f"🚀 Starting latency measurement: {num_packets} packets, interval {interval_ms} ms")
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
                    measurement = DetailedLatencyMeasurement(packet_id, t1, 0, 0, 0, 0, 0, 0, 0, 0, "MISMATCH")

            except queue.Empty:
                measurement = DetailedLatencyMeasurement(packet_id, t1, 0, 0, 0, 0, 0, 0, 0, 0, "TIMEOUT")

            self.measurements.append(measurement)
            if (packet_id + 1) % 10 == 0:
                print(f"📊 Progress: {packet_id + 1}/{num_packets}")

            if packet_id < num_packets - 1:
                time.sleep(interval_ms / 1000)

        self.running = False
        self.slave_thread.join()
        self.master_receiver_thread.join()
        print("✅ Measurement completed!")
        return self.measurements

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
        def stats(vals): return {
            'mean': np.mean(vals), 'median': np.median(vals), 'min': np.min(vals),
            'max': np.max(vals), 'std': np.std(vals),
            'p95': np.percentile(vals, 95), 'p99': np.percentile(vals, 99)
        }
        forward = stats([m.forward_delay_ms for m in ok])
        backward = stats([m.return_delay_ms for m in ok])
        rttstats = stats([m.rtt_ms for m in ok])
        jitter = [abs(ok[i].forward_delay_ms - ok[i-1].forward_delay_ms) for i in range(1, len(ok))]

        return {
            'total_packets': len(self.measurements),
            'successful_packets': len(ok),
            'lost_packets': len(self.measurements) - len(ok),
            'packet_loss_rate': ((len(self.measurements) - len(ok)) / len(self.measurements)) * 100,
            'forward': forward,
            'return': backward,
            'rtt': rttstats,
            'jitter': {'mean': np.mean(jitter) if jitter else 0, 'max': np.max(jitter) if jitter else 0}
        }
    def plot_results(self, output_prefix: str):
        """رسم نمودارهای جامع نتایج تست"""
        ok_measurements = [m for m in self.measurements if m.status == "OK"]
        
        if not ok_measurements:
            print("❌ No successful measurements to plot!")
            return

        # استخراج داده‌ها
        times = [(m.t1_master_send - self.measurements[0].t1_master_send) for m in ok_measurements]
        forward_delays = [m.forward_delay_ms for m in ok_measurements]
        return_delays = [m.return_delay_ms for m in ok_measurements]
        rtts = [m.rtt_ms for m in ok_measurements]
        asymmetries = [m.asymmetry_ms for m in ok_measurements]
        processing_times = [m.processing_time_ms for m in ok_measurements]

        # ایجاد figure با چیدمان پیشرفته
        fig = plt.figure(figsize=(20, 12))
        fig.suptitle('P900 Network Detailed Latency Analysis', fontsize=16, fontweight='bold')
        
        gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.3, wspace=0.3)

        # 1. نمودار اصلی: مقایسه Forward, Return و RTT
        ax1 = fig.add_subplot(gs[0, :])
        ax1.plot(times, forward_delays, 'b-', linewidth=1.5, alpha=0.8, label=f'Forward (Master→Slave): μ={np.mean(forward_delays):.2f}ms')
        ax1.plot(times, return_delays, 'r-', linewidth=1.5, alpha=0.8, label=f'Return (Slave→Master): μ={np.mean(return_delays):.2f}ms')
        ax1.plot(times, rtts, 'g--', linewidth=1, alpha=0.6, label=f'RTT (Total): μ={np.mean(rtts):.2f}ms')
        
        ax1.fill_between(times, forward_delays, alpha=0.2, color='blue')
        ax1.fill_between(times, return_delays, alpha=0.2, color='red')
        
        ax1.set_xlabel('Time (seconds)', fontsize=11)
        ax1.set_ylabel('Delay (ms)', fontsize=11)
        ax1.set_title('One-Way Delays and RTT Over Time', fontsize=12, fontweight='bold')
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.legend(loc='upper right', fontsize=10)
        
        # اضافه کردن خطوط میانگین
        ax1.axhline(y=np.mean(forward_delays), color='b', linestyle=':', alpha=0.5)
        ax1.axhline(y=np.mean(return_delays), color='r', linestyle=':', alpha=0.5)

        # 2. توزیع Forward Delay
        ax2 = fig.add_subplot(gs[1, 0])
        n, bins, patches = ax2.hist(forward_delays, bins=30, color='blue', alpha=0.7, edgecolor='black')
        ax2.axvline(x=np.mean(forward_delays), color='red', linestyle='--', linewidth=2, label=f'Mean: {np.mean(forward_delays):.2f}ms')
        ax2.axvline(x=np.median(forward_delays), color='green', linestyle='--', linewidth=2, label=f'Median: {np.median(forward_delays):.2f}ms')
        ax2.axvline(x=np.percentile(forward_delays, 95), color='orange', linestyle='--', linewidth=1, label=f'P95: {np.percentile(forward_delays, 95):.2f}ms')
        ax2.set_xlabel('Forward Delay (ms)')
        ax2.set_ylabel('Frequency')
        ax2.set_title('Forward Delay Distribution')
        ax2.grid(True, axis='y', alpha=0.3)
        ax2.legend(fontsize=9)

        # 3. توزیع Return Delay
        ax3 = fig.add_subplot(gs[1, 1])
        ax3.hist(return_delays, bins=30, color='red', alpha=0.7, edgecolor='black')
        ax3.axvline(x=np.mean(return_delays), color='blue', linestyle='--', linewidth=2, label=f'Mean: {np.mean(return_delays):.2f}ms')
        ax3.axvline(x=np.median(return_delays), color='green', linestyle='--', linewidth=2, label=f'Median: {np.median(return_delays):.2f}ms')
        ax3.axvline(x=np.percentile(return_delays, 95), color='orange', linestyle='--', linewidth=1, label=f'P95: {np.percentile(return_delays, 95):.2f}ms')
        ax3.set_xlabel('Return Delay (ms)')
        ax3.set_ylabel('Frequency')
        ax3.set_title('Return Delay Distribution')
        ax3.grid(True, axis='y', alpha=0.3)
        ax3.legend(fontsize=9)

        # 4. CDF مقایسه‌ای
        ax4 = fig.add_subplot(gs[1, 2])
        
        sorted_forward = np.sort(forward_delays)
        sorted_return = np.sort(return_delays)
        sorted_rtt = np.sort(rtts)
        
        cdf = np.arange(1, len(sorted_forward) + 1) / len(sorted_forward)
        
        ax4.plot(sorted_forward, cdf * 100, 'b-', linewidth=2, label='Forward Delay')
        ax4.plot(sorted_return, cdf * 100, 'r-', linewidth=2, label='Return Delay')
        ax4.plot(sorted_rtt, cdf * 100, 'g--', linewidth=2, label='RTT', alpha=0.7)
        
        # نمایش صدک‌های مهم
        for percentile in [50, 90, 95, 99]:
            ax4.axhline(y=percentile, color='gray', linestyle=':', alpha=0.3)
            ax4.text(ax4.get_xlim()[1]*0.02, percentile+1, f'{percentile}%', fontsize=8, color='gray')
        
        ax4.set_xlabel('Delay (ms)')
        ax4.set_ylabel('CDF (%)')
        ax4.set_title('Cumulative Distribution Function')
        ax4.grid(True, alpha=0.3)
        ax4.legend(loc='lower right')

        # 5. عدم تقارن (Asymmetry)
        ax5 = fig.add_subplot(gs[2, 0])
        ax5.plot(times, asymmetries, 'purple', linewidth=1, alpha=0.8)
        ax5.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax5.axhline(y=np.mean(asymmetries), color='red', linestyle='--', label=f'Mean: {np.mean(asymmetries):.2f}ms')
        ax5.fill_between(times, asymmetries, 0, where=(np.array(asymmetries) > 0), alpha=0.3, color='blue', label='Forward > Return')
        ax5.fill_between(times, asymmetries, 0, where=(np.array(asymmetries) < 0), alpha=0.3, color='red', label='Return > Forward')
        ax5.set_xlabel('Time (seconds)')
        ax5.set_ylabel('Asymmetry (ms)')
        ax5.set_title('Network Path Asymmetry (Forward - Return)')
        ax5.grid(True, alpha=0.3)
        ax5.legend(fontsize=9)

        # 6. Jitter Analysis
        ax6 = fig.add_subplot(gs[2, 1])
        
        forward_jitter = [abs(forward_delays[i] - forward_delays[i-1]) for i in range(1, len(forward_delays))]
        return_jitter = [abs(return_delays[i] - return_delays[i-1]) for i in range(1, len(return_delays))]
        jitter_times = times[1:]
        
        ax6.plot(jitter_times, forward_jitter, 'b-', linewidth=1, alpha=0.7, label=f'Forward Jitter (μ={np.mean(forward_jitter):.2f}ms)')
        ax6.plot(jitter_times, return_jitter, 'r-', linewidth=1, alpha=0.7, label=f'Return Jitter (μ={np.mean(return_jitter):.2f}ms)')
        ax6.set_xlabel('Time (seconds)')
        ax6.set_ylabel('Jitter (ms)')
        ax6.set_title('Inter-packet Delay Variation (Jitter)')
        ax6.grid(True, alpha=0.3)
        ax6.legend(fontsize=9)

        # 7. خلاصه آماری
        ax7 = fig.add_subplot(gs[2, 2])
        ax7.axis('off')
        
        stats_text = f"""📊 MEASUREMENT SUMMARY
════════════════════════════════════
📦 Packets: {len(self.measurements)} sent, {len(ok_measurements)} OK
📉 Loss Rate: {((len(self.measurements)-len(ok_measurements))/len(self.measurements)*100):.1f}%

⏱️ FORWARD DELAY (Master→Slave):
  Mean: {np.mean(forward_delays):.2f} ms
  Median: {np.median(forward_delays):.2f} ms  
  Min/Max: {np.min(forward_delays):.2f} / {np.max(forward_delays):.2f} ms
  Std Dev: {np.std(forward_delays):.2f} ms
  P95/P99: {np.percentile(forward_delays,95):.2f} / {np.percentile(forward_delays,99):.2f} ms

⏱️ RETURN DELAY (Slave→Master):
  Mean: {np.mean(return_delays):.2f} ms
  Median: {np.median(return_delays):.2f} ms
  Min/Max: {np.min(return_delays):.2f} / {np.max(return_delays):.2f} ms  
  Std Dev: {np.std(return_delays):.2f} ms
  P95/P99: {np.percentile(return_delays,95):.2f} / {np.percentile(return_delays,99):.2f} ms

🔄 RTT (Round-Trip Time):
  Mean: {np.mean(rtts):.2f} ms
  Min/Max: {np.min(rtts):.2f} / {np.max(rtts):.2f} ms

📊 ASYMMETRY:
  Mean: {np.mean(asymmetries):.2f} ms
  Std Dev: {np.std(asymmetries):.2f} ms

⚡ PROCESSING TIME (Slave):
  Mean: {np.mean(processing_times):.3f} ms"""
        
        ax7.text(0.05, 0.95, stats_text, transform=ax7.transAxes,
                fontsize=9, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.2))

        plt.tight_layout()
        
        # ذخیره نمودار
        plot_filename = f"{output_prefix}_detailed_analysis.png"
        plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
        print(f"📊 Plots saved to: {plot_filename}")
        
        # نمایش نمودار
        plt.show()

    def save_results(self, stats: Dict, output_prefix: str):
        """ذخیره نتایج در فایل‌های مختلف"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ok_measurements = [m for m in self.measurements if m.status == "OK"]
        # 1. فایل Text خلاصه
        summary_file = f"{output_prefix}_summary.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("="*70 + "\n")
            f.write("P900 NETWORK LATENCY DETAILED ANALYSIS REPORT\n")
            f.write("="*70 + "\n")
            f.write(f"Generated: {timestamp}\n")
            f.write(f"Test Configuration:\n")
            f.write(f"  Master Port: {self.local_port}\n")
            f.write(f"  Slave Port: {self.remote_port}\n")
            f.write(f"  Baudrate: {self.baudrate} bps\n")
            f.write(f"  Total Packets: {stats['total_packets']}\n")
            f.write("="*70 + "\n\n")

            f.write("OVERALL STATISTICS:\n")
            f.write("-"*40 + "\n")
            f.write(f"  Successful Packets: {stats['successful_packets']}\n")
            f.write(f"  Lost Packets: {stats['lost_packets']}\n")
            f.write(f"  Packet Loss Rate: {stats['packet_loss_rate']:.2f}%\n\n")

            if stats['successful_packets'] > 0:
                f.write("FORWARD DELAY (Master → Slave):\n")
                f.write("-"*40 + "\n")
                fd = stats['forward']
                f.write(f"  Mean: {fd['mean']:.3f} ms\n")
                f.write(f"  Median: {fd['median']:.3f} ms\n")
                f.write(f"  Min: {fd['min']:.3f} ms\n")
                f.write(f"  Max: {fd['max']:.3f} ms\n")
                f.write(f"  Std Dev: {fd['std']:.3f} ms\n")
                f.write(f"  95th Percentile: {fd['p95']:.3f} ms\n")
                f.write(f"  99th Percentile: {fd['p99']:.3f} ms\n\n")

                f.write("RETURN DELAY (Slave → Master):\n")
                f.write("-"*40 + "\n")
                rd = stats['return']
                f.write(f"  Mean: {rd['mean']:.3f} ms\n")
                f.write(f"  Median: {rd['median']:.3f} ms\n")
                f.write(f"  Min: {rd['min']:.3f} ms\n")
                f.write(f"  Max: {rd['max']:.3f} ms\n")
                f.write(f"  Std Dev: {rd['std']:.3f} ms\n")
                f.write(f"  95th Percentile: {rd['p95']:.3f} ms\n")
                f.write(f"  99th Percentile: {rd['p99']:.3f} ms\n\n")

                f.write("🔄 RTT (Round-Trip Time):\n")
                f.write("-"*40 + "\n")
                rt = stats['rtt']
                f.write(f"  Mean: {rt['mean']:.3f} ms\n")
                f.write(f"  Median: {rt['median']:.3f} ms\n")
                f.write(f"  Min: {rt['min']:.3f} ms\n")
                f.write(f"  Max: {rt['max']:.3f} ms\n")
                f.write(f"  Std Dev: {rt['std']:.3f} ms\n")
                f.write(f"  95th Percentile: {rt['p95']:.3f} ms\n")
                f.write(f"  99th Percentile: {rt['p99']:.3f} ms\n\n")

                f.write("📊 JITTER:\n")
                f.write("-"*40 + "\n")
                jit = stats['jitter']
                f.write(f"  Mean: {jit['mean']:.3f} ms\n")
                f.write(f"  Max: {jit['max']:.3f} ms\n\n")

                f.write("📈 ASYMMETRY ANALYSIS:\n")
                f.write("-"*40 + "\n")
                asym_vals = [m.asymmetry_ms for m in ok_measurements]
                if asym_vals:
                    f.write(f"  Mean Asymmetry: {np.mean(asym_vals):.3f} ms\n")
                    f.write(f"  Std Dev: {np.std(asym_vals):.3f} ms\n")
                    f.write(f"  Min: {np.min(asym_vals):.3f} ms\n")
                    f.write(f"  Max: {np.max(asym_vals):.3f} ms\n\n")

                f.write("⚡ PROCESSING TIME (Slave):\n")
                f.write("-"*40 + "\n")
                proc_vals = [m.processing_time_ms for m in ok_measurements]
                if proc_vals:
                    f.write(f"  Mean: {np.mean(proc_vals):.3f} ms\n")
                    f.write(f"  Std Dev: {np.std(proc_vals):.3f} ms\n\n")

                # Lost packets
                lost_packets = [m.packet_id for m in self.measurements if m.status != "OK"]
                if lost_packets:
                    f.write("❌ LOST/FAILED PACKETS:\n")
                    f.write("-"*40 + "\n")
                    f.write(f"  IDs: {lost_packets}\n")
                    f.write(f"  Total: {len(lost_packets)} packets\n\n")

                f.write("="*60 + "\n")
                f.write("Test completed successfully!\n")

        # JSON file
        json_file = f"{output_prefix}_results.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json_data = {
                "test_time": datetime.now().isoformat(),
                "configuration": {
                    "master_port": self.local_port,
                    "slave_port": self.remote_port,
                    "baudrate": self.baudrate
                },
                "statistics": stats,
                "measurements": [asdict(m) for m in self.measurements]
            }
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        print(f"💾 Results saved to:")
        print(f"   - Summary: {summary_file}")
        print(f"   - JSON: {json_file}")

    def disconnect(self):
        """قطع اتصال از پورت‌ها"""
        if self.local_serial and self.local_serial.is_open:
            self.local_serial.close()
            print(f"🔌 Disconnected from Master port: {self.local_port}")
        
        if self.remote_serial and self.remote_serial.is_open:
            self.remote_serial.close()
            print(f"🔌 Disconnected from Slave port: {self.remote_port}")

def main():
    """تابع اصلی برنامه"""
    # پارامترهای قابل تنظیم
    MASTER_PORT = "/dev/pts/6"   # پورت متصل به رادیو Master
    SLAVE_PORT = "/dev/pts/8"    # پورت متصل به رادیو Slave
    NUM_PACKETS = 100
    INTERVAL_MS = 100
    OUTPUT_PREFIX = f"p900_rtt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("="*60)
    print("🔬 P900 Network Detailed Latency Measurement Tool v2.0")
    print("="*60)
    print(f"Configuration:")
    print(f"  📡 Master Radio Port: {MASTER_PORT}")
    print(f"  📡 Slave Radio Port: {SLAVE_PORT}")
    print(f"  📦 Number of Packets: {NUM_PACKETS}")
    print(f"  ⏱️ Packet Interval: {INTERVAL_MS} ms")
    print(f"  💾 Output Prefix: {OUTPUT_PREFIX}")
    print("="*60)

    # ایجاد تستر
    tester = P900NetworkTesterEnhanced(MASTER_PORT, SLAVE_PORT)

    try:
        # اتصال به پورت‌ها
        if not tester.connect():
            print("❌ Failed to establish connections!")
            return

        # اجرای تست
        input("\n📌 Press Enter to start the test...")
        print("\n" + "="*60)
        
        measurements = tester.measure_latency(NUM_PACKETS, INTERVAL_MS)

        # محاسبه آمار
        stats = tester.get_statistics()

        # نمایش نتایج
        print("\n" + "="*60)
        print("📊 TEST RESULTS SUMMARY")
        print("="*60)
        
        print(f"\n📦 Packet Statistics:")
        print(f"  Total: {stats['total_packets']}")
        print(f"  Successful: {stats['successful_packets']}")
        print(f"  Lost: {stats['lost_packets']}")
        print(f"  Loss Rate: {stats['packet_loss_rate']:.1f}%")

        if stats['successful_packets'] > 0:
            print(f"\n⏱️ Forward Delay (Master→Slave):")
            print(f"  Mean: {stats['forward']['mean']:.2f} ms")
            print(f"  Min: {stats['forward']['min']:.2f} ms")
            print(f"  Max: {stats['forward']['max']:.2f} ms")
            
            print(f"\n⏱️ Return Delay (Slave→Master):")
            print(f"  Mean: {stats['return']['mean']:.2f} ms")
            print(f"  Min: {stats['return']['min']:.2f} ms")
            print(f"  Max: {stats['return']['max']:.2f} ms")
            
            print(f"\n🔄 Round-Trip Time (RTT):")
            print(f"  Mean: {stats['rtt']['mean']:.2f} ms")
            print(f"  Min: {stats['rtt']['min']:.2f} ms")
            print(f"  Max: {stats['rtt']['max']:.2f} ms")

        # ذخیره نتایج
        tester.save_results(stats, OUTPUT_PREFIX)

        # رسم نمودارها
        tester.plot_results(OUTPUT_PREFIX)

        print("\n✅ Test completed successfully!")

    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user!")
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n" + "="*60)
        tester.disconnect()
        print("="*60)

if __name__ == "__main__":
    main()
