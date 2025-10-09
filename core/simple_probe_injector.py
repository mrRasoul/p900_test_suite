#!/usr/bin/env python3
"""
debug_serial_loopback.py - تست کامل و گام به گام Serial Loopback
"""

import serial
import time
import struct

class SerialLoopbackDebugger:
    def __init__(self, port1='/dev/ttyUSB0', port2='/dev/ttyUSB1', baudrate=57600):
        self.port1_name = port1
        self.port2_name = port2
        self.baudrate = baudrate
        self.port1 = None
        self.port2 = None
        
    def test_1_port_open(self):
        """تست 1: آیا پورت‌ها باز می‌شوند؟"""
        print("\n" + "="*60)
        print("TEST 1: Opening Serial Ports")
        print("-"*60)
        
        try:
            self.port1 = serial.Serial(
                self.port1_name, 
                baudrate=self.baudrate,
                timeout=0.5,
                write_timeout=0.5
            )
            print(f"✅ {self.port1_name} opened successfully")
            print(f"   Settings: {self.port1.baudrate} baud, "
                  f"{self.port1.bytesize} bits, "
                  f"{self.port1.parity} parity, "
                  f"{self.port1.stopbits} stop")
        except Exception as e:
            print(f"❌ Failed to open {self.port1_name}: {e}")
            return False
            
        try:
            self.port2 = serial.Serial(
                self.port2_name,
                baudrate=self.baudrate,
                timeout=0.5,
                write_timeout=0.5
            )
            print(f"✅ {self.port2_name} opened successfully")
            print(f"   Settings: {self.port2.baudrate} baud, "
                  f"{self.port2.bytesize} bits, "
                  f"{self.port2.parity} parity, "
                  f"{self.port2.stopbits} stop")
        except Exception as e:
            print(f"❌ Failed to open {self.port2_name}: {e}")
            return False
            
        # Clear buffers
        self.port1.reset_input_buffer()
        self.port1.reset_output_buffer()
        self.port2.reset_input_buffer()
        self.port2.reset_output_buffer()
        print("✅ Buffers cleared")
        
        return True
    
    def test_2_simple_byte(self):
        """تست 2: ارسال و دریافت یک بایت ساده"""
        print("\n" + "="*60)
        print("TEST 2: Simple Byte Transfer")
        print("-"*60)
        
        test_byte = b'A'
        
        # Port1 -> Port2
        print(f"Sending '{test_byte.decode()}' from {self.port1_name} to {self.port2_name}...")
        self.port1.write(test_byte)
        self.port1.flush()
        
        time.sleep(0.01)
        
        if self.port2.in_waiting > 0:
            received = self.port2.read(1)
            if received == test_byte:
                print(f"✅ Received '{received.decode()}' - PASS")
            else:
                print(f"❌ Received '{received}' instead of '{test_byte}' - FAIL")
                return False
        else:
            print(f"❌ Nothing received at {self.port2_name} - FAIL")
            print(f"   in_waiting = {self.port2.in_waiting}")
            return False
            
        # Port2 -> Port1
        print(f"\nSending '{test_byte.decode()}' from {self.port2_name} to {self.port1_name}...")
        self.port2.write(test_byte)
        self.port2.flush()
        
        time.sleep(0.01)
        
        if self.port1.in_waiting > 0:
            received = self.port1.read(1)
            if received == test_byte:
                print(f"✅ Received '{received.decode()}' - PASS")
            else:
                print(f"❌ Received '{received}' instead of '{test_byte}' - FAIL")
                return False
        else:
            print(f"❌ Nothing received at {self.port1_name} - FAIL")
            print(f"   in_waiting = {self.port1.in_waiting}")
            return False
            
        return True
    
    def test_3_echo_pattern(self):
        """تست 3: Echo Pattern - ارسال و بازگرداندن"""
        print("\n" + "="*60)
        print("TEST 3: Echo Pattern")
        print("-"*60)
        
        pattern = b"HELLO123"
        
        print(f"Sending pattern '{pattern.decode()}' from {self.port1_name}...")
        self.port1.write(pattern)
        self.port1.flush()
        
        time.sleep(0.05)
        
        # Port2 receives and echoes back
        if self.port2.in_waiting >= len(pattern):
            received = self.port2.read(len(pattern))
            print(f"Port2 received: '{received.decode()}'")
            
            # Echo back
            print(f"Port2 echoing back...")
            self.port2.write(received)
            self.port2.flush()
            
            time.sleep(0.05)
            
            # Port1 checks echo
            if self.port1.in_waiting >= len(pattern):
                echo = self.port1.read(len(pattern))
                if echo == pattern:
                    print(f"✅ Port1 received echo: '{echo.decode()}' - PASS")
                    return True
                else:
                    print(f"❌ Port1 received wrong echo: '{echo}' - FAIL")
            else:
                print(f"❌ Port1 didn't receive echo - FAIL")
                print(f"   in_waiting = {self.port1.in_waiting}")
        else:
            print(f"❌ Port2 didn't receive pattern - FAIL")
            print(f"   in_waiting = {self.port2.in_waiting}")
            
        return False
    
    def test_4_probe_format(self):
        """تست 4: Probe Packet Format مشابه کد اصلی"""
        print("\n" + "="*60)
        print("TEST 4: Probe Packet Format")
        print("-"*60)
        
        PROBE_MARKER = b'\xBB\x44'
        probe_id = 12345
        packet_type = 0x10  # REQUEST
        packet_size = 64
        
        # Create packet
        packet = bytearray()
        packet.extend(PROBE_MARKER)  # 2 bytes
        packet.extend(struct.pack('<I', probe_id))  # 4 bytes
        packet.append(packet_type)  # 1 byte
        packet.extend(struct.pack('<H', packet_size))  # 2 bytes
        
        # Checksum
        checksum = sum(packet) & 0xFF
        packet.append(checksum)  # 1 byte
        
        # Padding
        packet.extend(b'\x00' * 2)  # 2 bytes
        
        # Fill to packet_size
        remaining = packet_size - len(packet)
        packet.extend(bytes([probe_id & 0xFF] * remaining))
        
        packet = bytes(packet[:packet_size])
        
        print(f"Created probe packet: {len(packet)} bytes")
        print(f"  Marker: {packet[:2].hex()}")
        print(f"  Probe ID: {probe_id}")
        print(f"  Type: 0x{packet_type:02x}")
        print(f"  Size: {packet_size}")
        
        # Send from port1
        print(f"\nSending probe from {self.port1_name}...")
        self.port1.write(packet)
        self.port1.flush()
        
        time.sleep(0.1)
        
        # Check port2
        if self.port2.in_waiting >= packet_size:
            received = self.port2.read(packet_size)
            print(f"✅ Port2 received {len(received)} bytes")
            
            # Parse received packet
            if received[:2] == PROBE_MARKER:
                print(f"✅ Marker matched: {received[:2].hex()}")
                
                recv_id = struct.unpack('<I', received[2:6])[0]
                if recv_id == probe_id:
                    print(f"✅ Probe ID matched: {recv_id}")
                else:
                    print(f"❌ Probe ID mismatch: {recv_id} != {probe_id}")
                    
                # Create response
                response = bytearray(received)
                response[6] = 0x11  # RESPONSE type
                
                # Recalculate checksum
                checksum = sum(response[:9]) & 0xFF
                response[9] = checksum
                
                print(f"\nSending response from {self.port2_name}...")
                self.port2.write(bytes(response))
                self.port2.flush()
                
                time.sleep(0.1)
                
                # Check port1 for response
                if self.port1.in_waiting >= packet_size:
                    resp_received = self.port1.read(packet_size)
                    if resp_received[6] == 0x11:
                        print(f"✅ Response received with correct type")
                        return True
                    else:
                        print(f"❌ Response type incorrect: 0x{resp_received[6]:02x}")
                else:
                    print(f"❌ No response at {self.port1_name}")
                    print(f"   in_waiting = {self.port1.in_waiting}")
            else:
                print(f"❌ Marker mismatch: {received[:2].hex()}")
        else:
            print(f"❌ Insufficient data at {self.port2_name}")
            print(f"   Expected: {packet_size}, Got: {self.port2.in_waiting}")
            
        return False
    
    def test_5_timing_analysis(self):
        """تست 5: تحلیل زمان‌بندی"""
        print("\n" + "="*60)
        print("TEST 5: Timing Analysis")
        print("-"*60)
        
        test_sizes = [1, 10, 64, 128, 256]
        
        for size in test_sizes:
            data = bytes([i % 256 for i in range(size)])
            
            # Measure round-trip time
            start = time.perf_counter()
            
            self.port1.write(data)
            self.port1.flush()
            
            # Wait for data
            timeout = time.perf_counter() + 0.5
            while self.port2.in_waiting < size and time.perf_counter() < timeout:
                time.sleep(0.0001)
            
            if self.port2.in_waiting >= size:
                received = self.port2.read(size)
                
                # Echo back
                self.port2.write(received)
                self.port2.flush()
                
                # Wait for echo
                timeout = time.perf_counter() + 0.5
                while self.port1.in_waiting < size and time.perf_counter() < timeout:
                    time.sleep(0.0001)
                
                if self.port1.in_waiting >= size:
                    echo = self.port1.read(size)
                    end = time.perf_counter()
                    
                    rtt_ms = (end - start) * 1000
                    throughput = (size * 2) / (end - start)  # bytes per second
                    
                    print(f"  {size:3} bytes: RTT={rtt_ms:.2f}ms, "
                          f"Throughput={throughput:.0f} B/s")
                else:
                    print(f"  {size:3} bytes: Echo timeout")
            else:
                print(f"  {size:3} bytes: Receive timeout")
        
        return True
    
    def run_all_tests(self):
        """اجرای همه تست‌ها"""
        print("\n" + "="*60)
        print(" SERIAL LOOPBACK COMPLETE DIAGNOSTIC")
        print("="*60)
        print(f"Port 1: {self.port1_name}")
        print(f"Port 2: {self.port2_name}")
        print(f"Baudrate: {self.baudrate}")
        
        tests = [
            (self.test_1_port_open, "Port Opening"),
            (self.test_2_simple_byte, "Simple Byte Transfer"),
            (self.test_3_echo_pattern, "Echo Pattern"),
            (self.test_4_probe_format, "Probe Packet Format"),
            (self.test_5_timing_analysis, "Timing Analysis")
        ]
        
        results = []
        
        for test_func, test_name in tests:
            result = test_func()
            results.append((test_name, result))
            
            if not result and test_func != self.test_5_timing_analysis:
                print(f"\n⚠️ Stopping - {test_name} failed")
                break
        
        # Summary
        print("\n" + "="*60)
        print(" TEST SUMMARY")
        print("="*60)
        
        for name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  {name:25} {status}")
        
        # Diagnosis
        print("\n" + "="*60)
        print(" DIAGNOSIS")
        print("="*60)
        
        if all(r for _, r in results):
            print("✅ All tests passed - Hardware is working correctly!")
            print("\n🔍 The original ProbeInjector issue is likely:")
            print("   - Complex packet format")
            print("   - Thread timing issues")
            print("   - Buffer management problems")
        else:
            failed = [name for name, result in results if not result][0] if results else "Unknown"
            
            if failed == "Port Opening":
                print("❌ Cannot open serial ports")
                print("   - Check if ports exist: ls -la /dev/ttyUSB*")
                print("   - Check permissions: sudo chmod 666 /dev/ttyUSB*")
                print("   - Check if ports are in use: sudo lsof | grep ttyUSB")
                
            elif failed == "Simple Byte Transfer":
                print("❌ Basic communication failed")
                print("   - Check cable connection")
                print("   - Verify loopback wiring (TX1->RX2, RX1->TX2)")
                print("   - Try different baudrate")
                print("   - Check if P900 hardware is powered on")
                
            elif failed == "Echo Pattern":
                print("❌ Multi-byte transfer failed")
                print("   - Partial data loss indicates timing issues")
                print("   - Try lower baudrate (9600 or 19200)")
                print("   - Check for electrical interference")
                
            elif failed == "Probe Packet Format":
                print("❌ Probe packet format incompatible")
                print("   - The packet structure needs revision")
                print("   - Marker bytes might be filtered by hardware")
                print("   - Try simpler packet format")
                
            elif failed == "Timing Analysis":
                print("⚠️  Basic communication works but timing is poor")
                print("   - High latency detected")
                print("   - Check USB-to-Serial converter quality")
                print("   - Try direct serial connection if possible")
        
        # Close ports
        if self.port1 and self.port1.is_open:
            self.port1.close()
        if self.port2 and self.port2.is_open:
            self.port2.close()
            
        print("\n" + "="*60)
        print(" TEST COMPLETE")
        print("="*60)


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Serial Loopback Diagnostic Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test default ports
  python3 debug_serial_loopback.py
  
  # Test specific ports
  python3 debug_serial_loopback.py --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1
  
  # Test with different baudrate
  python3 debug_serial_loopback.py --baudrate 115200
  
  # Test virtual ports (socat)
  python3 debug_serial_loopback.py --port1 /dev/pts/4 --port2 /dev/pts/5
        """
    )
    
    parser.add_argument('--port1', '-p1', 
                       default='/dev/ttyUSB0',
                       help='First serial port (Master)')
    
    parser.add_argument('--port2', '-p2',
                       default='/dev/ttyUSB1', 
                       help='Second serial port (Slave)')
    
    parser.add_argument('--baudrate', '-b',
                       type=int,
                       default=57600,
                       help='Baudrate for both ports')
    
    parser.add_argument('--quick', '-q',
                       action='store_true',
                       help='Run only basic tests (skip timing analysis)')
    
    args = parser.parse_args()
    
    # Print header
    print("\n" + "="*60)
    print(" SERIAL LOOPBACK DIAGNOSTIC TOOL v1.0")
    print("="*60)
    print(f"Testing communication between:")
    print(f"  Port 1 (Master): {args.port1}")
    print(f"  Port 2 (Slave):  {args.port2}")
    print(f"  Baudrate: {args.baudrate}")
    print("="*60)
    
    # Create debugger instance
    debugger = SerialLoopbackDebugger(
        port1=args.port1,
        port2=args.port2,
        baudrate=args.baudrate
    )
    
    # Run tests
    try:
        if args.quick:
            print("\n⚡ Running quick test mode (basic tests only)...")
            
            # Run only first 3 tests
            results = []
            tests = [
                (debugger.test_1_port_open, "Port Opening"),
                (debugger.test_2_simple_byte, "Simple Byte Transfer"),
                (debugger.test_3_echo_pattern, "Echo Pattern")
            ]
            
            for test_func, test_name in tests:
                result = test_func()
                results.append((test_name, result))
                if not result:
                    print(f"\n⚠️ Stopping - {test_name} failed")
                    break
            
            # Quick summary
            print("\n" + "="*60)
            print(" QUICK TEST SUMMARY")
            print("="*60)
            for name, result in results:
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"  {name:25} {status}")
                
            if all(r for _, r in results):
                print("\n✅ Basic communication working!")
                print("   Run without --quick flag for full diagnostics")
            else:
                print("\n❌ Basic communication failed!")
                print("   Fix hardware/cable issues first")
                
        else:
            # Run all tests
            debugger.run_all_tests()
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Make sure ports are closed
        try:
            if hasattr(debugger, 'port1') and debugger.port1 and debugger.port1.is_open:
                debugger.port1.close()
            if hasattr(debugger, 'port2') and debugger.port2 and debugger.port2.is_open:
                debugger.port2.close()
        except:
            pass
    
    print("\n👋 Goodbye!\n")


if __name__ == "__main__":
    main()
