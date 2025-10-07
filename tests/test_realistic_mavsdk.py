"""
Realistic Test with MAVSDK
تست واقع‌گرایانه با ترافیک MAVLink از MAVSDK
"""
import asyncio
import threading
import time
from typing import Dict

from core.p900_tester import P900NetworkTesterEnhanced
from core.mavsdk_simulator import MAVSDKTrafficSimulator, SimulatorConfig
from utils.config import MASTER_PORT, SLAVE_PORT
from utils.logger import setup_logger

logger = setup_logger(__name__)

class RealisticTestWithMAVSDK:
    """
    تست RTT در حضور ترافیک واقعی MAVLink
    ترکیب P900 Tester با MAVSDK Simulator
    """
    
    def __init__(self, master_port: str, slave_port: str):
        self.master_port = master_port
        self.slave_port = slave_port
        
        # RTT Tester (PySerial-based)
        self.rtt_tester = P900NetworkTesterEnhanced(master_port, slave_port)
        
        # Traffic Simulator (MAVSDK-based)
        self.traffic_config = SimulatorConfig(
            system_address=f"serial://{master_port}:57600",
            telemetry_rate_hz={
                'position': 10.0,
                'attitude': 20.0,
                'battery': 1.0,
                'gps': 5.0,
                'imu': 30.0
            }
        )
        self.traffic_simulator = MAVSDKTrafficSimulator(self.traffic_config)
        
        self.results = {}
        
    async def run_test_async(self, num_packets: int = 100,
                            interval_ms: int = 100,
                            traffic_duration: float = None):
        """
        اجرای تست به صورت async
        """
        if traffic_duration is None:
            traffic_duration = (num_packets * interval_ms / 1000) + 5
        
        logger.info("="*60)
        logger.info("🚀 Starting REALISTIC TEST with MAVSDK")
        logger.info(f"📦 Packets: {num_packets}")
        logger.info(f"⏱️ Interval: {interval_ms}ms")
        logger.info(f"🌐 Traffic Duration: {traffic_duration}s")
        logger.info("="*60)
        
        # Phase 1: Baseline (بدون ترافیک)
        logger.info("\n📊 Phase 1: Baseline Test (No Traffic)")
        if self.rtt_tester.connect():
            self.rtt_tester.measure_latency(
                num_packets=min(20, num_packets),
                interval_