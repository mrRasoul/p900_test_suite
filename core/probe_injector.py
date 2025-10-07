#!/usr/bin/env python3
"""
Probe Injection Module for P900 Testing
ماژول تزریق Probe برای تست تحت بار و اندازه‌گیری دقیق تأخیر
Version: 2.0 - High-Precision Implementation
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

# Import utilities
from utils.logger import setup_logger
from utils.config import (
    PROBE_INTERVAL_MS, 
    PROBE_PACKET_SIZE,
    PROBE_TIMEOUT_MS,
    PROBE_HISTORY_SIZE,
    DEFAULT_BAUDRATE
)

logger = setup_logger('ProbeInjector')

@dataclass
class ProbePacket:
    """ساختار داده برای هر Probe packet"""
    probe_id: int
    timestamp_sent: float
    timestamp_received: float
    timestamp_processed: float
    payload_size: int
    status: str  # 'SENT', 'RECEIVED', 'TIMEOUT', 'ERROR'
    rtt_ms: float
    forward_delay_ms: float
    return_delay_ms: float
    jitter_ms: float

@dataclass 
class ProbeStatistics:
    """آمار جامع Probe ها"""
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

class ProbeInjector:
    """
    کلاس تزریق Probe در کنار ترافیک عادی با دقت بالا
    """
    
    # Constants for probe protocol
    PROBE_MARKER = b'\xBB\x44'
    PROBE_TYPE_REQUEST = 0x10
    PROBE_TYPE_RESPONSE = 0x11
    PROBE_HEADER_SIZE = 24  # 2(marker) + 4(id) + 1(type) + 8(timestamp) + 8(reserved) + 1(checksum)
    
    def __init__(self, 
                 master_serial=None,
                 slave_serial=None,
                 interval_ms=PROBE_INTERVAL_MS,
                 packet_size=PROBE_PACKET_SIZE,  # ⚠️ باید dynamic باشه
                 timeout_ms=PROBE_TIMEOUT_MS,
                 history_size=PROBE_HISTORY_SIZE,
                 packet_size_list=None):  # ✅ اضافه کن
        """
        Args:
            master_serial: Serial connection to master radio
            slave_serial: Serial connection to slave radio  
            interval_ms: Interval between probes in milliseconds
            packet_size: Total size of probe packet in bytes
            timeout_ms: Timeout for probe response in milliseconds
            history_size: Number of recent probes to keep for analysis
            packet_size_list: لیست اندازه‌های مختلف برای تست
        """
        self.packet_size_list = packet_size_list or [packet_size]
        self.current_size_index = 0
        self.master_serial = master_serial
        self.slave_serial = slave_serial
        self.interval_ms = interval_ms
        self.packet_size = max(packet_size, self.PROBE_HEADER_SIZE + 10)
        self.timeout_ms = timeout_ms
        self.history_size = history_size
        
        # Threading control
        self.running = False
        self.injection_thread = None
        self.receiver_thread = None
        self.slave_responder_thread = None
        
        # Data structures
        self.probe_history = deque(maxlen=history_size)
        self.pending_probes = {}  # probe_id -> timestamp_sent
        self.response_queue = queue.Queue()
        self.probe_lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'total_sent': 0,
            'total_received': 0,
            'total_lost': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'last_rtt_ms': 0,
            'last_jitter_ms': 0
        }
        
        # Timing tracking
        self.last_probe_time = 0
        self.last_rtt_values = deque(maxlen=100)  # For jitter calculation
        self.probe_id_counter = 0
        
        # High precision timing
        self.use_perf_counter = True  # Use time.perf_counter for microsecond precision
        
        logger.info(f"ProbeInjector initialized:")
        logger.info(f"  Interval: {interval_ms}ms")
        logger.info(f"  Packet size: {packet_size} bytes")
        logger.info(f"  Timeout: {timeout_ms}ms")
        logger.info(f"  History size: {history_size}")

    def _get_timestamp(self) -> float:
        """Get high-precision timestamp"""
        if self.use_perf_counter:
            return time.perf_counter()
        else:
            return time.time()
    
    def _create_probe_packet(self, probe_id: int, packet_type: int, 
                           timestamp: float = None) -> bytes:
        """
        Create a probe packet with precise timestamp
        
        Packet structure:
        [Marker:2] + [ProbeID:4] + [Type:1] + [Timestamp:8] + 
        [Reserved:8] + [Checksum:1] + [Payload:N]
        """
        packet = bytearray()
        
        # Header
        packet.extend(self.PROBE_MARKER)
        packet.extend(struct.pack('<I', probe_id))
        packet.append(packet_type)
        
        # Timestamp (microsecond precision)
        if timestamp is None:
            timestamp = self._get_timestamp()
        timestamp_us = int(timestamp * 1_000_000)
        packet.extend(struct.pack('<Q', timestamp_us))
        
        # Reserved space for future use
        packet.extend(bytes(8))
        
        # Calculate checksum (simple XOR)
        checksum = 0
        for byte in packet:
            checksum ^= byte
        packet.append(checksum)
        
        # Payload (fill to desired packet size)
        payload_size = self.packet_size - len(packet)
        if payload_size > 0:
            # Create recognizable pattern
            payload = bytes([(i ^ probe_id) % 256 for i in range(payload_size)])
            packet.extend(payload)
        
        return bytes(packet)
    
    def _parse_probe_packet(self, data: bytes) -> Optional[Dict]:
        """Parse received probe packet"""
        if len(data) < self.PROBE_HEADER_SIZE:
            return None
        
        try:
            # Check marker
            if data[:2] != self.PROBE_MARKER:
                return None
            
            # Extract fields
            probe_id = struct.unpack('<I', data[2:6])[0]
            packet_type = data[6]
            timestamp_us = struct.unpack('<Q', data[7:15])[0]
            reserved = data[15:23]
            checksum = data[23]
            
            # Verify checksum
            calc_checksum = 0
            for byte in data[:23]:
                calc_checksum ^= byte
            
            if calc_checksum != checksum:
                logger.warning(f"Probe {probe_id} checksum mismatch")
                return None
            
            return {
                'probe_id': probe_id,
                'type': packet_type,
                'timestamp': timestamp_us / 1_000_000.0,
                'reserved': reserved
            }
            
        except Exception as e:
            logger.error(f"Error parsing probe packet: {e}")
            return None
    def _injection_loop(self):
        """Main loop for injecting probe packets"""
        logger.info("Probe injection loop started")
        next_probe_time = self._get_timestamp()
        
        while self.running:
            try:
                current_time = self._get_timestamp()
                
                # Check if it's time to send next probe
                if current_time >= next_probe_time:
                    # Generate probe ID
                    probe_id = self.probe_id_counter
                    self.probe_id_counter = (self.probe_id_counter + 1) % 0xFFFFFFFF
                    
                    # Create and send probe request
                    timestamp_sent = self._get_timestamp()
                    probe_packet = self._create_probe_packet(
                        probe_id, 
                        self.PROBE_TYPE_REQUEST,
                        timestamp_sent
                    )
                    
                    if self.master_serial and self.master_serial.is_open:
                        self.master_serial.write(probe_packet)
                        self.master_serial.flush()
                        
                        # Track probe
                        with self.probe_lock:
                            self.pending_probes[probe_id] = timestamp_sent
                            self.stats['total_sent'] += 1
                            self.stats['bytes_sent'] += len(probe_packet)
                        
                        logger.debug(f"Probe {probe_id} sent at {timestamp_sent:.6f}")
                    
                    # Schedule next probe
                    next_probe_time = current_time + (self.interval_ms / 1000.0)
                
                # Check for timeouts
                self._check_timeouts()
                
                # Small sleep to prevent CPU spinning
                time.sleep(0.0001)  # 100 microseconds
                
            except Exception as e:
                logger.error(f"Error in injection loop: {e}")
                time.sleep(0.001)
        
        logger.info("Probe injection loop stopped")
    
    def _receiver_loop(self):
        """Loop for receiving probe responses on master side"""
        logger.info("Probe receiver loop started")
        buffer = bytearray()
        
        while self.running:
            try:
                if self.master_serial and self.master_serial.in_waiting > 0:
                    data = self.master_serial.read(self.master_serial.in_waiting)
                    buffer.extend(data)
                    
                    # Look for probe markers
                    while len(buffer) >= self.packet_size:
                        marker_pos = buffer.find(self.PROBE_MARKER)
                        
                        if marker_pos == -1:
                            buffer = bytearray()
                            break
                        
                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]
                        
                        if len(buffer) >= self.packet_size:
                            packet_data = bytes(buffer[:self.packet_size])
                            parsed = self._parse_probe_packet(packet_data)
                            
                            if parsed and parsed['type'] == self.PROBE_TYPE_RESPONSE:
                                timestamp_received = self._get_timestamp()
                                self._process_probe_response(
                                    parsed['probe_id'],
                                    parsed['timestamp'],
                                    timestamp_received
                                )
                            
                            buffer = buffer[self.packet_size:]
                
                time.sleep(0.0001)
                
            except Exception as e:
                logger.error(f"Error in receiver loop: {e}")
                time.sleep(0.001)
        
        logger.info("Probe receiver loop stopped")
    
    def _slave_responder_loop(self):
        """Loop for responding to probes on slave side"""
        logger.info("Slave responder loop started")
        buffer = bytearray()
        
        while self.running:
            try:
                if self.slave_serial and self.slave_serial.in_waiting > 0:
                    data = self.slave_serial.read(self.slave_serial.in_waiting)
                    buffer.extend(data)
                    
                    # Look for probe requests
                    while len(buffer) >= self.packet_size:
                        marker_pos = buffer.find(self.PROBE_MARKER)
                        
                        if marker_pos == -1:
                            buffer = bytearray()
                            break
                        
                        if marker_pos > 0:
                            buffer = buffer[marker_pos:]
                        
                        if len(buffer) >= self.packet_size:
                            packet_data = bytes(buffer[:self.packet_size])
                            parsed = self._parse_probe_packet(packet_data)
                            
                            if parsed and parsed['type'] == self.PROBE_TYPE_REQUEST:
                                # Send response immediately
                                response_timestamp = self._get_timestamp()
                                response_packet = self._create_probe_packet(
                                    parsed['probe_id'],
                                    self.PROBE_TYPE_RESPONSE,
                                    parsed['timestamp']  # Include original timestamp
                                )
                                
                                self.slave_serial.write(response_packet)
                                self.slave_serial.flush()
                                
                                logger.debug(f"Probe {parsed['probe_id']} response sent")
                            
                            buffer = buffer[self.packet_size:]
                
                time.sleep(0.0001)
                
            except Exception as e:
                logger.error(f"Error in slave responder loop: {e}")
                time.sleep(0.001)
        
        logger.info("Slave responder loop stopped")
    
    def _process_probe_response(self, probe_id: int, 
                               original_timestamp: float,
                               received_timestamp: float):
        """Process received probe response"""
        with self.probe_lock:
            if probe_id in self.pending_probes:
                sent_timestamp = self.pending_probes.pop(probe_id)
                
                # Calculate RTT
                rtt_ms = (received_timestamp - sent_timestamp) * 1000
                
                # Calculate jitter
                jitter_ms = 0
                if self.last_rtt_values:
                    jitter_ms = abs(rtt_ms - self.last_rtt_values[-1])
                
                self.last_rtt_values.append(rtt_ms)
                
                # Update statistics
                self.stats['total_received'] += 1
                self.stats['bytes_received'] += self.packet_size
                self.stats['last_rtt_ms'] = rtt_ms
                self.stats['last_jitter_ms'] = jitter_ms
                
                # Create probe record
                probe_record = ProbePacket(
                    probe_id=probe_id,
                    timestamp_sent=sent_timestamp,
                    timestamp_received=received_timestamp,
                    timestamp_processed=received_timestamp,
                    payload_size=self.packet_size,
                    status='RECEIVED',
                    rtt_ms=rtt_ms,
                    forward_delay_ms=rtt_ms/2,  # Approximate
                    return_delay_ms=rtt_ms/2,   # Approximate
                    jitter_ms=jitter_ms
                )
                
                self.probe_history.append(probe_record)
                
                logger.debug(f"Probe {probe_id}: RTT={rtt_ms:.3f}ms, Jitter={jitter_ms:.3f}ms")
    
    def _check_timeouts(self):
        """Check for probe timeouts"""
        current_time = self._get_timestamp()
        timeout_threshold = self.timeout_ms / 1000.0
        
        with self.probe_lock:
            timed_out = []
            for probe_id, sent_time in self.pending_probes.items():
                if current_time - sent_time > timeout_threshold:
                    timed_out.append(probe_id)
            
            for probe_id in timed_out:
                self.pending_probes.pop(probe_id)
                self.stats['total_lost'] += 1
                
                # Record timeout
                probe_record = ProbePacket(
                    probe_id=probe_id,
                    timestamp_sent=0,
                    timestamp_received=0,
                    timestamp_processed=0,
                    payload_size=self.packet_size,
                    status='TIMEOUT',
                    rtt_ms=0,
                    forward_delay_ms=0,
                    return_delay_ms=0,
                    jitter_ms=0
                )
                self.probe_history.append(probe_record)
                
                logger.warning(f"Probe {probe_id} timed out")
    
    def start(self):
        """Start probe injection"""
        if self.running:
            logger.warning("ProbeInjector already running")
            return
        
        self.running = True
        self.probe_id_counter = 0
        
        # Start threads
        if self.master_serial:
            self.injection_thread = threading.Thread(target=self._injection_loop)
            self.injection_thread.daemon = True
            self.injection_thread.start()
            
            self.receiver_thread = threading.Thread(target=self._receiver_loop)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()
        
        if self.slave_serial:
            self.slave_responder_thread = threading.Thread(target=self._slave_responder_loop)
            self.slave_responder_thread.daemon = True
            self.slave_responder_thread.start()
        
        logger.info("ProbeInjector started")
    
    def stop(self):
        """Stop probe injection"""
        if not self.running:
            return
        
        self.running = False
        
        # Wait for threads to finish
        if self.injection_thread:
            self.injection_thread.join(timeout=1.0)
        if self.receiver_thread:
            self.receiver_thread.join(timeout=1.0)
        if self.slave_responder_thread:
            self.slave_responder_thread.join(timeout=1.0)
        
        logger.info("ProbeInjector stopped")
        logger.info(f"Final stats: Sent={self.stats['total_sent']}, "
                   f"Received={self.stats['total_received']}, "
                   f"Lost={self.stats['total_lost']}")
    
    def get_statistics(self) -> ProbeStatistics:
        """Get comprehensive probe statistics"""
        with self.probe_lock:
            received_probes = [p for p in self.probe_history if p.status == 'RECEIVED']
            
            if not received_probes:
                return ProbeStatistics(
                    total_sent=self.stats['total_sent'],
                    total_received=0,
                    total_lost=self.stats['total_lost'],
                    loss_rate=100.0 if self.stats['total_sent'] > 0 else 0,
                    avg_rtt_ms=0,
                    min_rtt_ms=0,
                    max_rtt_ms=0,
                    std_rtt_ms=0,
                    avg_jitter_ms=0,
                    max_jitter_ms=0,
                    percentile_95_ms=0,
                    percentile_99_ms=0,
                    current_rate_hz=1000.0/self.interval_ms if self.interval_ms > 0 else 0,
                    bytes_sent=self.stats['bytes_sent'],
                    bytes_received=self.stats['bytes_received']
                )
            
            # Calculate RTT statistics
            rtt_values = [p.rtt_ms for p in received_probes]
            jitter_values = [p.jitter_ms for p in received_probes if p.jitter_ms > 0]
            
            loss_rate = 0
            if self.stats['total_sent'] > 0:
                loss_rate = (self.stats['total_lost'] / self.stats['total_sent']) * 100
            
            return ProbeStatistics(
                total_sent=self.stats['total_sent'],
                total_received=self.stats['total_received'],
                total_lost=self.stats['total_lost'],
                loss_rate=loss_rate,
                avg_rtt_ms=np.mean(rtt_values),
                min_rtt_ms=np.min(rtt_values),
                max_rtt_ms=np.max(rtt_values),
                std_rtt_ms=np.std(rtt_values),
                avg_jitter_ms=np.mean(jitter_values) if jitter_values else 0,
                max_jitter_ms=np.max(jitter_values) if jitter_values else 0,
                percentile_95_ms=np.percentile(rtt_values, 95),
                percentile_99_ms=np.percentile(rtt_values, 99),
                current_rate_hz=1000.0/self.interval_ms if self.interval_ms > 0 else 0,
                bytes_sent=self.stats['bytes_sent'],
                bytes_received=self.stats['bytes_received']
            )
    
    def get_recent_probes(self, count: int = 10) -> List[ProbePacket]:
        """Get recent probe measurements"""
        with self.probe_lock:
            return list(self.probe_history)[-count:]
    
    def save_results(self, filename: str):
        """Save probe results to file"""
        with self.probe_lock:
            stats = self.get_statistics()
            recent = self.get_recent_probes(100)
            
            results = {
                'timestamp': time.time(),
                'configuration': {
                    'interval_ms': self.interval_ms,
                    'packet_size': self.packet_size,
                    'timeout_ms': self.timeout_ms
                },
                'statistics': asdict(stats),
                'recent_probes': [asdict(p) for p in recent]
            }
            
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)
            
            logger.info(f"Results saved to {filename}")
