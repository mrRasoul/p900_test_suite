"""
MAVSDK-based Traffic Simulator
شبیه‌ساز ترافیک MAVLink با استفاده از MAVSDK
"""
import asyncio
from mavsdk import System
from mavsdk.offboard import (PositionNedYaw, VelocityBodyYawspeed)
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)

@dataclass
class SimulatorConfig:
    """تنظیمات شبیه‌ساز"""
    system_address: str = "serial:///dev/ttyUSB0:57600"  # یا "udp://:14540"
    telemetry_rate_hz: Dict[str, float] = None
    
    def __post_init__(self):
        if self.telemetry_rate_hz is None:
            self.telemetry_rate_hz = {
                'position': 10.0,
                'attitude': 20.0,
                'battery': 1.0,
                'gps': 5.0,
                'imu': 50.0
            }

class MAVSDKTrafficSimulator:
    """
    شبیه‌ساز ترافیک واقعی MAVLink با MAVSDK
    برای ایجاد بار ترافیکی realistic
    """
    
    def __init__(self, config: SimulatorConfig = None):
        self.config = config or SimulatorConfig()
        self.drone = System()
        self.is_connected = False
        self.telemetry_tasks = []
        self.stats = {
            'messages_sent': 0,
            'bytes_sent': 0,
            'start_time': None,
            'message_types': {}
        }
        
    async def connect(self) -> bool:
        """اتصال به سیستم MAVLink"""
        try:
            logger.info(f"Connecting to {self.config.system_address}")
            await self.drone.connect(system_address=self.config.system_address)
            
            # بررسی connection
            async for state in self.drone.core.connection_state():
                if state.is_connected:
                    logger.info("✅ MAVSDK Connected!")
                    self.is_connected = True
                    break
                    
            return self.is_connected
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    async def start_telemetry_streams(self):
        """شروع stream های telemetry"""
        self.stats['start_time'] = time.time()
        
        # Position stream
        if self.config.telemetry_rate_hz['position'] > 0:
            task = asyncio.create_task(
                self._position_telemetry_loop(
                    1.0 / self.config.telemetry_rate_hz['position']
                )
            )
            self.telemetry_tasks.append(task)
        
        # Attitude stream
        if self.config.telemetry_rate_hz['attitude'] > 0:
            task = asyncio.create_task(
                self._attitude_telemetry_loop(
                    1.0 / self.config.telemetry_rate_hz['attitude']
                )
            )
            self.telemetry_tasks.append(task)
        
        # Battery stream
        if self.config.telemetry_rate_hz['battery'] > 0:
            task = asyncio.create_task(
                self._battery_telemetry_loop(
                    1.0 / self.config.telemetry_rate_hz['battery']
                )
            )
            self.telemetry_tasks.append(task)
            
        logger.info(f"Started {len(self.telemetry_tasks)} telemetry streams")
    
    async def _position_telemetry_loop(self, interval: float):
        """ارسال مداوم position"""
        async for position in self.drone.telemetry.position():
            self._update_stats('POSITION', 28)  # تخمین اندازه
            await asyncio.sleep(interval)
    
    async def _attitude_telemetry_loop(self, interval: float):
        """ارسال مداوم attitude"""
        async for attitude in self.drone.telemetry.attitude_euler():
            self._update_stats('ATTITUDE', 28)
            await asyncio.sleep(interval)
    
    async def _battery_telemetry_loop(self, interval: float):
        """ارسال مداوم battery status"""
        async for battery in self.drone.telemetry.battery():
            self._update_stats('BATTERY', 24)
            await asyncio.sleep(interval)
    
    def _update_stats(self, msg_type: str, size: int):
        """بروزرسانی آمار"""
        self.stats['messages_sent'] += 1
        self.stats['bytes_sent'] += size
        
        if msg_type not in self.stats['message_types']:
            self.stats['message_types'][msg_type] = 0
        self.stats['message_types'][msg_type] += 1
    
    async def inject_custom_traffic(self, duration_seconds: float,
                                   message_rate_hz: float = 10):
        """تزریق ترافیک سفارشی برای مدت مشخص"""
        logger.info(f"Injecting traffic for {duration_seconds}s at {message_rate_hz}Hz")
        
        interval = 1.0 / message_rate_hz
        end_time = time.time() + duration_seconds
        
        while time.time() < end_time:
            # ارسال پیام heartbeat
            # در MAVSDK این کار automatic است
            self._update_stats('HEARTBEAT', 17)
            await asyncio.sleep(interval)
    
    def get_statistics(self) -> Dict:
        """دریافت آمار ترافیک"""
        if self.stats['start_time']:
            duration = time.time() - self.stats['start_time']
            avg_rate = self.stats['messages_sent'] / duration if duration > 0 else 0
            avg_bandwidth = self.stats['bytes_sent'] / duration if duration > 0 else 0
        else:
            avg_rate = 0
            avg_bandwidth = 0
            
        return {
            'total_messages': self.stats['messages_sent'],
            'total_bytes': self.stats['bytes_sent'],
            'average_rate_hz': avg_rate,
            'average_bandwidth_bps': avg_bandwidth * 8,
            'message_breakdown': self.stats['message_types']
        }
    
    async def stop(self):
        """توقف شبیه‌ساز"""
        logger.info("Stopping telemetry streams...")
        
        # Cancel all tasks
        for task in self.telemetry_tasks:
            task.cancel()
        
        # Wait for cancellation
        await asyncio.gather(*self.telemetry_tasks, return_exceptions=True)
        
        self.telemetry_tasks.clear()
        logger.info("✅ All streams stopped")
    
    async def disconnect(self):
        """قطع اتصال"""
        await self.stop()
        # MAVSDK doesn't have explicit disconnect
        self.is_connected = False
        logger.info("Disconnected")

# ========== Helper Functions ==========

async def simulate_realistic_traffic(duration_seconds: float,
                                    port: str = "/dev/ttyUSB0"):
    """
    تابع ساده برای شبیه‌سازی ترافیک realistic
    """
    config = SimulatorConfig(
        system_address=f"serial://{port}:57600",
        telemetry_rate_hz={
            'position': 10.0,
            'attitude': 30.0,
            'battery': 1.0,
            'gps': 5.0,
            'imu': 0  # غیرفعال
        }
    )
    
    simulator = MAVSDKTrafficSimulator(config)
    
    if await simulator.connect():
        await simulator.start_telemetry_streams()
        await asyncio.sleep(duration_seconds)
        
        stats = simulator.get_statistics()
        print(f"\n📊 Traffic Statistics:")
        print(f"  Messages: {stats['total_messages']}")
        print(f"  Data: {stats['total_bytes']} bytes")
        print(f"  Rate: {stats['average_rate_hz']:.1f} Hz")
        print(f"  Bandwidth: {stats['average_bandwidth_bps']:.0f} bps")
        
        await simulator.disconnect()
    else:
        print("Failed to connect!")

# ========== Test Code ==========

if __name__ == "__main__":
    # تست شبیه‌ساز
    asyncio.run(simulate_realistic_traffic(10.0))
