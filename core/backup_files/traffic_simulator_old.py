#!/usr/bin/env python3
"""
MAVLink Traffic Simulator Module - Fully Optimized Version
شبیه ساز ترافیک MAVLink با کنترل دقیق نرخ ارسال و عملکرد بالا
"""

import time
import serial
import logging
import threading
import collections
from typing import Optional, Dict, Any, Tuple, List
from packet_generator import PacketGenerator
from mavlink_profile import MAVLinkProfile

logger = logging.getLogger(__name__)

class TrafficSimulator:
    """
    High-performance traffic simulator with precise rate control
    """
    
    def __init__(self, serial_port: Optional[serial.Serial] = None,
                 target_bandwidth: float = 2373.0,
                 write_lock: Optional[threading.Lock] = None):
        """
        Initialize traffic simulator with optimizations
        
        Args:
            serial_port: Serial port for sending traffic
            target_bandwidth: Target bandwidth in bytes/second
            write_lock: Shared write lock for serial access
        """
        self.serial_port = serial_port
        self.target_bandwidth = target_bandwidth
        self.write_lock = write_lock or threading.Lock()
        self.running = False
        
        # Packet generation setup
        self.profile = MAVLinkProfile()
        self.packet_generator = PacketGenerator(self.profile)
        
        # Packet pool for performance
        self.packet_pool = []
        self.pool_size = 1000
        self.pool_index = 0
        
        # Enhanced Token Bucket with burst capability
        self.bucket_capacity = target_bandwidth * 1.5  # 50% burst allowance
        self.tokens = self.bucket_capacity
        self.last_token_update = time.perf_counter()
        
        # Timing and batching parameters
        self.min_packet_interval = 0.0001  # 100μs minimum
        self.batch_size = 1  # Will be calculated based on rate
        self.max_batch_size = 20
        self.iteration_rate = 100  # 100 iterations per second (10ms each)
        
        # Statistics tracking
        self.stats = {
            'packets_sent': 0,
            'bytes_sent': 0,
            'start_time': None,
            'errors': 0,
            'rate_limited_count': 0,
            'burst_count': 0,
            'write_conflicts': 0,
            'actual_rates': [],
            'pool_regenerations': 0,
            'batch_sends': 0,
            'avg_batch_size': 0
        }
        self.stats_lock = threading.Lock()
        
        # Calculate optimal parameters
        self._calculate_timing_params()
        
        # Pre-generate initial packet pool
        self._regenerate_packet_pool()
        
    def _calculate_timing_params(self):
        """Calculate timing parameters based on target bandwidth"""
        self.avg_packet_size = self.profile.statistics.get('mean_size', 34.69)
        self.packets_per_second = self.target_bandwidth / self.avg_packet_size
        self.avg_packet_interval = 1.0 / self.packets_per_second if self.packets_per_second > 0 else 0.1
        
        # Determine optimal batch size based on rate
        if self.packets_per_second > 500:
            self.batch_size = min(self.max_batch_size, int(self.packets_per_second / 50))
        elif self.packets_per_second > 100:
            self.batch_size = min(10, int(self.packets_per_second / 20))
        elif self.packets_per_second > 50:
            self.batch_size = 5
        else:
            self.batch_size = 1
            
        # Adjust iteration rate for very high bandwidths
        if self.target_bandwidth > 50000:  # > 50KB/s
            self.iteration_rate = 200  # 5ms iterations
        elif self.target_bandwidth > 10000:  # > 10KB/s
            self.iteration_rate = 100  # 10ms iterations
        else:
            self.iteration_rate = 50  # 20ms iterations
            
        logger.info(f"Timing params: {self.packets_per_second:.2f} pps, "
                   f"interval: {self.avg_packet_interval*1000:.2f}ms, "
                   f"batch size: {self.batch_size}, "
                   f"iteration rate: {self.iteration_rate} Hz")
    
    def _regenerate_packet_pool(self):
        """Pre-generate diverse packets for better performance"""
        self.packet_pool.clear()
        
        # Generate packets with realistic size distribution
        sizes = self.profile.get_packet_sizes(self.pool_size, mode='realistic')
        
        for size in sizes:
            try:
                data = self.packet_generator.generate_mavlink_traffic(size)
                self.packet_pool.append(data)
            except Exception as e:
                logger.error(f"Error generating packet: {e}")
                # Add a default packet if generation fails
                self.packet_pool.append(b'\xfe\x00\x00\x00\x00\x00\x00\x00')
                
        self.pool_index = 0
        
        with self.stats_lock:
            self.stats['pool_regenerations'] += 1
            
        logger.debug(f"Generated packet pool with {len(self.packet_pool)} packets, "
                    f"avg size: {sum(len(p) for p in self.packet_pool)/len(self.packet_pool):.1f} bytes")
    
    def _get_next_packet(self) -> bytes:
        """Get next packet from pool with circular indexing"""
        if not self.packet_pool:
            self._regenerate_packet_pool()
            
        packet = self.packet_pool[self.pool_index]
        self.pool_index = (self.pool_index + 1) % len(self.packet_pool)
        
        # Regenerate pool occasionally for variety (in background)
        if self.pool_index == 0 and self.stats['packets_sent'] > 10000:
            # Reset counter to avoid too frequent regeneration
            with self.stats_lock:
                if self.stats['packets_sent'] % 10000 == 0:
                    threading.Thread(target=self._regenerate_packet_pool, daemon=True).start()
                    
        return packet
    
    def _update_tokens(self) -> float:
        """Update token bucket with high precision timing"""
        now = time.perf_counter()
        elapsed = now - self.last_token_update
        
        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.target_bandwidth
        self.tokens = min(self.tokens + tokens_to_add, self.bucket_capacity)
        
        self.last_token_update = now
        return self.tokens
    
    def _consume_tokens(self, amount: int) -> bool:
        """Try to consume tokens from bucket"""
        available = self._update_tokens()
        
        if available >= amount:
            self.tokens -= amount
            
            # Track burst usage
            if available > self.bucket_capacity * 0.9:
                with self.stats_lock:
                    self.stats['burst_count'] += 1
                    
            return True
            
        return False
    
    def _precise_sleep(self, duration: float):
        """High precision sleep implementation"""
        if duration <= 0:
            return
            
        if duration < 0.002:  # Less than 2ms
            # Use busy wait for very short durations
            target_time = time.perf_counter() + duration
            while time.perf_counter() < target_time:
                pass
        else:
            # Use regular sleep for longer durations
            # Compensate for typical OS sleep overshoot
            time.sleep(duration * 0.95)
    
    def _send_batch(self, packets: List[bytes]) -> int:
        """Send multiple packets in a single write operation"""
        if not packets:
            return 0
            
        total_bytes = sum(len(p) for p in packets)
        
        # Try non-blocking acquire first
        acquired = self.write_lock.acquire(blocking=False)
        
        if not acquired:
            with self.stats_lock:
                self.stats['write_conflicts'] += 1
            
            # Brief wait and retry
            acquired = self.write_lock.acquire(timeout=0.005)
            
        if not acquired:
            logger.debug("Failed to acquire write lock")
            return 0
            
        try:
            # Combine packets for single write
            combined_data = b''.join(packets)
            
            # Perform write operation
            bytes_written = self.serial_port.write(combined_data)
            
            # Update statistics
            with self.stats_lock:
                self.stats['packets_sent'] += len(packets)
                self.stats['bytes_sent'] += bytes_written
                self.stats['batch_sends'] += 1
                
                # Update average batch size
                current_avg = self.stats['avg_batch_size']
                self.stats['avg_batch_size'] = (
                    (current_avg * (self.stats['batch_sends'] - 1) + len(packets)) / 
                    self.stats['batch_sends']
                )
                
            # Log progress periodically
            if self.stats['packets_sent'] % 1000 == 0:
                self._log_progress()
                
            return bytes_written
            
        except serial.SerialTimeoutException:
            logger.warning("Serial write timeout")
            with self.stats_lock:
                self.stats['errors'] += 1
            return 0
            
        except Exception as e:
            logger.error(f"Error sending batch: {e}")
            with self.stats_lock:
                self.stats['errors'] += 1
            return 0
            
        finally:
            self.write_lock.release()
    
    def _run_loop(self):
        """Main traffic generation loop with optimizations"""
        
        # Initialize timing
        second_start = time.perf_counter()
        iteration_start = time.perf_counter()
        bytes_this_second = 0
        packets_this_second = 0
        
        # Calculate targets
        iteration_period = 1.0 / self.iteration_rate
        bytes_per_iteration = self.target_bandwidth / self.iteration_rate
        
        # Batch accumulator
        batch = []
        batch_bytes = 0
        
        while self.running:
            now = time.perf_counter()
            
            # Check for second boundary (statistics)
            if now - second_start >= 1.0:
                with self.stats_lock:
                    actual_rate = bytes_this_second
                    accuracy = (actual_rate / self.target_bandwidth * 100) if self.target_bandwidth > 0 else 0
                    
                    self.stats['actual_rates'].append({
                        'time': second_start,
                        'bytes': bytes_this_second,
                        'packets': packets_this_second,
                        'rate': actual_rate,
                        'accuracy': accuracy
                    })
                    
                    # Keep only last 60 seconds of rate history
                    if len(self.stats['actual_rates']) > 60:
                        self.stats['actual_rates'] = self.stats['actual_rates'][-60:]
                    
                    # Log if significantly off target
                    if abs(accuracy - 100) > 10 and bytes_this_second > 0:
                        logger.debug(f"Rate: {actual_rate:.0f} B/s ({accuracy:.1f}% of target)")
                
                # Reset counters
                bytes_this_second = 0
                packets_this_second = 0
                second_start = now
            
            # Build batch for this iteration
            target_batch_bytes = min(bytes_per_iteration, self.target_bandwidth * 0.1)  # Max 100ms worth
            
            while batch_bytes < target_batch_bytes and len(batch) < self.batch_size:
                # Get next packet
                packet = self._get_next_packet()
                packet_size = len(packet)
                
                # Check token availability
                if self._consume_tokens(packet_size):
                    batch.append(packet)
                    batch_bytes += packet_size
                else:
                    # Rate limited
                    with self.stats_lock:
                        self.stats['rate_limited_count'] += 1
                    
                    # Wait for tokens to refill
                    wait_time = packet_size / self.target_bandwidth if self.target_bandwidth > 0 else 0.01
                    self._precise_sleep(min(wait_time, 0.01))
                    break
            
            # Send batch if ready
            if batch:
                bytes_sent = self._send_batch(batch)
                
                if bytes_sent > 0:
                    bytes_this_second += bytes_sent
                    packets_this_second += len(batch)
                
                # Clear batch
                batch.clear()
                batch_bytes = 0
            
            # Calculate time until next iteration
            iteration_elapsed = time.perf_counter() - iteration_start
            sleep_time = iteration_period - iteration_elapsed
            
            if sleep_time > 0:
                self._precise_sleep(sleep_time)
                iteration_start = time.perf_counter()
            elif sleep_time < -iteration_period:
                # We're falling way behind, reset timing
                iteration_start = time.perf_counter()
            else:
                # Just update the start time
                iteration_start += iteration_period
    
    def start(self):
        """Start traffic generation"""
        if not self.serial_port:
            logger.error("No serial port configured")
            return False
            
        if hasattr(self.serial_port, 'is_open') and not self.serial_port.is_open:
            try:
                self.serial_port.open()
            except Exception as e:
                logger.error(f"Failed to open serial port: {e}")
                return False
                
        self.running = True
        
        # Reset statistics
        with self.stats_lock:
            self.stats.update({
                'start_time': time.perf_counter(),
                'packets_sent': 0,
                'bytes_sent': 0,
                'errors': 0,
                'rate_limited_count': 0,
                'burst_count': 0,
                'write_conflicts': 0,
                'actual_rates': [],
                'pool_regenerations': 0,
                'batch_sends': 0,
                'avg_batch_size': 0
            })
        
        # Reset token bucket
        self.tokens = self.bucket_capacity
        self.last_token_update = time.perf_counter()
        
        logger.info(f"Traffic generation started (target: {self.target_bandwidth:.0f} B/s)")
        
        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("Traffic generation interrupted by user")
        except Exception as e:
            logger.error(f"Error in traffic loop: {e}", exc_info=True)
        finally:
            self.running = False
            self._print_stats()
            
        return True
    
    def stop(self):
        """Stop traffic generation"""
        logger.info("Stopping traffic generation...")
        self.running = False
    
    def adjust_rate(self, new_bandwidth: float):
        """Dynamically adjust target bandwidth"""
        old_bandwidth = self.target_bandwidth
        self.target_bandwidth = new_bandwidth
        self.bucket_capacity = new_bandwidth * 1.5
        self._calculate_timing_params()
        logger.info(f"Bandwidth adjusted from {old_bandwidth} -> {new_bandwidth} B/s")

    def get_stats(self) -> Dict[str, Any]:
        """Return current simulation statistics"""
        with self.stats_lock:
            s = self.stats.copy()
        if s['start_time']:
            elapsed = time.perf_counter() - s['start_time']
            s['elapsed_time'] = elapsed
            s['actual_bandwidth'] = s['bytes_sent'] / elapsed if elapsed > 0 else 0
        return s

    def _log_progress(self):
        """Log progress at packet milestones"""
        with self.stats_lock:
            elapsed = time.perf_counter() - self.stats['start_time']
            rate = self.stats['bytes_sent'] / elapsed if elapsed > 0 else 0
            logger.info(f"Progress: {self.stats['packets_sent']} pkts, {rate:.2f} B/s")

    def _print_stats(self):
        """Print simulation statistics to stdout"""
        s = self.get_stats()
        print("\n" + "="*60)
        print("Traffic Generation Stats (Optimized Version):")
        for k, v in s.items():
            if k != 'actual_rates':
                print(f"{k}: {v:.3f}" if isinstance(v, float) else f"{k}: {v}")
        if s['actual_rates']:
            print(f"Last actual rate: {s['actual_rates'][-1]}")

def create_simulator(port_name: Optional[str] = None,
                    baudrate: int = 57600,
                    target_bandwidth: float = 2373.0,
                    write_lock: Optional[threading.Lock] = None) -> TrafficSimulator:
    """Factory function to create a simulator instance"""
    sp = None
    if port_name:
        try:
            sp = serial.Serial(port=port_name, baudrate=baudrate, timeout=0.05, write_timeout=0.05)
            logger.info(f"Serial port {port_name} opened at {baudrate} baud")
        except Exception as e:
            logger.error(f"Failed to open {port_name}: {e}")
    return TrafficSimulator(sp, target_bandwidth, write_lock)

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    port = sys.argv[1] if len(sys.argv) > 1 else None
    sim = create_simulator(port_name=port)
    if not port:
        # Using dummy serial for testing without hardware
        sim.serial_port = type('DummySerial', (), {
            'is_open': True,
            'write': lambda self, data: len(data)
        })()
    t = threading.Thread(target=sim.start)
    t.start()
    try:
        time.sleep(5)
    except KeyboardInterrupt:
        pass
    sim.stop()
    t.join()
    print(sim.get_stats())
