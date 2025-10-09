#!/usr/bin/env python3
"""
MAVLink Traffic Simulator Module - Enhanced Version
شبیه ساز ترافیک MAVLink با کنترل دقیق نرخ ارسال و هماهنگ سازی با ProbeInjector
"""

import time
import serial
import logging
import threading
from typing import Optional, Dict, Any, Tuple
from packet_generator import PacketGenerator
from mavlink_profile import MAVLinkProfile

logger = logging.getLogger(__name__)

class TrafficSimulator:
    def __init__(self, serial_port: Optional[serial.Serial] = None,
                 target_bandwidth: float = 2373.0,
                 write_lock: Optional[threading.Lock] = None):
        self.serial_port = serial_port
        self.target_bandwidth = target_bandwidth
        self.write_lock = write_lock or threading.Lock()
        self.running = False

        self.profile = MAVLinkProfile()
        self.packet_generator = PacketGenerator(self.profile)

        self.bucket_capacity = target_bandwidth
        self.tokens = self.bucket_capacity
        self.last_token_update = time.time()
        self.min_packet_interval = 0.001
        self.burst_allowance = 1.2

        self.stats = {
            'packets_sent': 0,
            'bytes_sent': 0,
            'start_time': None,
            'errors': 0,
            'rate_limited_count': 0,
            'burst_count': 0,
            'write_conflicts': 0,
            'actual_rates': []
        }
        self.stats_lock = threading.Lock()
        self._calculate_timing_params()

    def _calculate_timing_params(self):
        self.avg_packet_size = self.profile.statistics.get('mean_size', 34.69)
        self.packets_per_second = self.target_bandwidth / self.avg_packet_size
        self.avg_packet_interval = 1.0 / self.packets_per_second if self.packets_per_second > 0 else 0.1
        logger.info(f"Timing: {self.packets_per_second:.2f} pps, interval: {self.avg_packet_interval*1000:.2f}ms")

    def _update_tokens(self) -> float:
        now = time.time()
        elapsed = now - self.last_token_update
        self.tokens = min(self.tokens + elapsed * self.target_bandwidth,
                          self.bucket_capacity * self.burst_allowance)
        self.last_token_update = now
        return self.tokens

    def _consume_tokens(self, amount: int) -> bool:
        available = self._update_tokens()
        if available >= amount:
            self.tokens -= amount
            if available > self.bucket_capacity:
                with self.stats_lock:
                    self.stats['burst_count'] += 1
            return True
        return False

    def start(self):
        if not self.serial_port or (hasattr(self.serial_port, 'is_open') and not self.serial_port.is_open):
            try:
                self.serial_port.open() if hasattr(self.serial_port, 'open') else None
            except Exception as e:
                logger.error(f"Unable to open serial port: {e}")
                return False
        self.running = True
        self.stats.update({'start_time': time.time(),
                           'packets_sent': 0, 'bytes_sent': 0, 'errors': 0,
                           'rate_limited_count': 0, 'burst_count': 0,
                           'write_conflicts': 0, 'actual_rates': []})
        self.tokens = self.bucket_capacity
        self.last_token_update = time.time()
        logger.info("Traffic generation started")
        try:
            self._run_loop()
        finally:
            self.running = False
            self._print_stats()
        return True

    def _run_loop(self):
        second_start = time.time()
        bytes_this_sec = 0
        pkts_this_sec = 0
        last_send_time = time.time()
        consecutive_rl = 0

        while self.running:
            now = time.time()
            if now - second_start >= 1.0:
                with self.stats_lock:
                    self.stats['actual_rates'].append({
                        'time': second_start,
                        'bytes': bytes_this_sec,
                        'packets': pkts_this_sec,
                        'rate': bytes_this_sec,
                        'accuracy': (bytes_this_sec / self.target_bandwidth * 100) if self.target_bandwidth else 0
                    })
                bytes_this_sec, pkts_this_sec = 0, 0
                second_start = now
                consecutive_rl = 0

            pkt_info = self._prepare_packet()
            if pkt_info:
                pkt_size, pkt_data = pkt_info
                if self._consume_tokens(pkt_size):
                    if self._send_packet_safe(pkt_data):
                        bytes_this_sec += pkt_size
                        pkts_this_sec += 1
                        delay = max(self.min_packet_interval, pkt_size / self.target_bandwidth)
                        delta = now - last_send_time
                        if delta < delay:
                            time.sleep(delay - delta)
                        last_send_time = time.time()
                        consecutive_rl = 0
                else:
                    with self.stats_lock:
                        self.stats['rate_limited_count'] += 1
                    consecutive_rl += 1
                    time.sleep(min(pkt_size / self.target_bandwidth, 0.01))
            else:
                time.sleep(0.01)

    def _prepare_packet(self) -> Optional[Tuple[int, bytes]]:
        try:
            size = self.profile.get_packet_sizes(1, mode='realistic')[0]
            data = self.packet_generator.generate_mavlink_traffic(size)
            return len(data), data
        except Exception as e:
            logger.error(f"Error preparing packet: {e}")
            return None

    def _send_packet_safe(self, data: bytes) -> bool:
        acquired = self.write_lock.acquire(blocking=False)
        if not acquired:
            with self.stats_lock:
                self.stats['write_conflicts'] += 1
            acquired = self.write_lock.acquire(timeout=0.01)
        if not acquired:
            return False
        try:
            bytes_written = self.serial_port.write(data)
            with self.stats_lock:
                self.stats['packets_sent'] += 1
                self.stats['bytes_sent'] += bytes_written
            if self.stats['packets_sent'] % 1000 == 0:
                self._log_progress()
            return True
        except Exception as e:
            logger.error(f"Error sending packet: {e}")
            with self.stats_lock:
                self.stats['errors'] += 1
            return False
        finally:
            self.write_lock.release()

    def adjust_rate(self, new_bw: float):
        self.target_bandwidth = new_bw
        self.bucket_capacity = new_bw
        self._calculate_timing_params()
        logger.info(f"Bandwidth adjusted to {new_bw} B/s")

    def get_stats(self) -> Dict[str, Any]:
        with self.stats_lock:
            s = self.stats.copy()
        if s['start_time']:
            elapsed = time.time() - s['start_time']
            s['elapsed_time'] = elapsed
            s['actual_bandwidth'] = s['bytes_sent'] / elapsed if elapsed else 0
        return s

    def stop(self):
        self.running = False

    def _log_progress(self):
        with self.stats_lock:
            elapsed = time.time() - self.stats['start_time']
            rate = self.stats['bytes_sent'] / elapsed if elapsed else 0
            logger.info(f"Progress: {self.stats['packets_sent']} pkts, {rate:.2f} B/s")

    def _print_stats(self):
        s = self.get_stats()
        print("\n" + "="*60)
        print("Traffic Generation Stats:")
        for k, v in s.items():
            if k != 'actual_rates':
                print(f"{k}: {v}")

def create_simulator(port_name: Optional[str] = None,
                    baudrate: int = 57600,
                    target_bandwidth: float = 2373.0,
                    write_lock: Optional[threading.Lock] = None) -> TrafficSimulator:
    sp = None
    if port_name:
        try:
            sp = serial.Serial(port=port_name, baudrate=baudrate, timeout=0.1)
            logger.info(f"Serial port {port_name} opened at {baudrate} baud")
        except Exception as e:
            logger.error(f"Failed to open {port_name}: {e}")
    return TrafficSimulator(sp, target_bandwidth, write_lock)

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    port = sys.argv[1] if len(sys.argv) > 1 else None
    sim = create_simulator(port_name=port)
    if not port:
        sim.serial_port = type('DummySerial', (), {'is_open': True, 'write': lambda self, data: len(data)})()
    t = threading.Thread(target=sim.start)
    t.start()
    try:
        time.sleep(5)
    except KeyboardInterrupt:
        pass
    sim.stop()
    t.join()
    print(sim.get_stats())
