import asyncio
from dbus_next.aio import MessageBus
from dbus_next import BusType, Variant
from pynput.keyboard import Controller # Used to simulate typing

# Constants
DEVICE_MAC = "2A:02:01:17:3D:C1"
NOTIFY_UUID = "0000ee02-0000-1000-8000-00805f9b34fb"
WRITE_UUID  = "0000ee03-0000-1000-8000-00805f9b34fb"
WAKE_UP_PAYLOAD = b'\x00\x07\x02\x08\x0e\x00\x00\x00\x01'

# Initialize virtual keyboard
keyboard = Controller()

def parse_distance_mm(data: bytes):
    """Parses the FNIRSI IR40 packet and returns the value in millimeters."""
    # The laser sends a 17+ byte packet starting with 00 .. 02 01 for measurements
    if len(data) >= 17 and data[0] == 0x00 and data[2] == 0x02:
        # Based on your previous working logic, bytes 14-16 are the little-endian mm value
        dist_mm = int.from_bytes(data[14:17], "little")
        return dist_mm
    return None

async def main():
    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        print("Connected to system dbus")

        adapter = "hci0"
        device_path = f"/org/bluez/{adapter}/dev_{DEVICE_MAC.replace(':', '_')}"
        
        # 1. Device Discovery and Connection
        introspection = await bus.introspect('org.bluez', device_path)
        proxy_object = bus.get_proxy_object('org.bluez', device_path, introspection)
        device_interface = proxy_object.get_interface('org.bluez.Device1')
        
        if not await device_interface.get_connected():
            print(f"Connecting to {DEVICE_MAC}...")
            await asyncio.wait_for(device_interface.call_connect(), timeout=15.0)
        
        while not await device_interface.get_services_resolved():
            await asyncio.sleep(0.5)

        # 2. Find Characteristics
        obj_manager_introspection = await bus.introspect('org.bluez', '/')
        obj_manager_proxy = bus.get_proxy_object('org.bluez', '/', obj_manager_introspection)
        obj_manager = obj_manager_proxy.get_interface('org.freedesktop.DBus.ObjectManager')
        
        objs = await obj_manager.call_get_managed_objects()
        write_char = None
        notify_char = None

        for path, interfaces in objs.items():
            if 'org.bluez.GattCharacteristic1' in interfaces:
                props = interfaces['org.bluez.GattCharacteristic1']
                uuid = props['UUID'].value.lower()
                if path.startswith(device_path):
                    if uuid == WRITE_UUID:
                        write_char = path
                    elif uuid == NOTIFY_UUID:
                        notify_char = path

        if not write_char or not notify_char:
            print("Required characteristics not found. Re-pair the device.")
            return

        # 3. Setup Notification Listener (The "Paster")
        notify_intro = await bus.introspect('org.bluez', notify_char)
        notify_proxy = bus.get_proxy_object('org.bluez', notify_char, notify_intro)
        notify_interface = notify_proxy.get_interface('org.bluez.GattCharacteristic1')
        properties_interface = notify_proxy.get_interface('org.freedesktop.DBus.Properties')

        def on_properties_changed(interface_name, changed_properties, invalidated_properties):
            if 'Value' in changed_properties:
                raw_data = bytes(changed_properties['Value'].value)
                mm_val = parse_distance_mm(raw_data)
                
                if mm_val is not None:
                    # Format as string
                    val_str = str(mm_val)
                    print(f"Captured: {val_str} mm -> Typing...")
                    
                    # Simulate typing the value followed by a Tab or Enter if you prefer
                    keyboard.type(val_str)
                    # keyboard.tap(Key.enter) # Uncomment if you want it to hit Enter after typing

        properties_interface.on_properties_changed(on_properties_changed)
        await notify_interface.call_start_notify()

        # 4. Wake Up the laser
        write_intro = await bus.introspect('org.bluez', write_char)
        write_proxy = bus.get_proxy_object('org.bluez', write_char, write_intro)
        write_interface = write_proxy.get_interface('org.bluez.GattCharacteristic1')
        
        await write_interface.call_write_value(WAKE_UP_PAYLOAD, {'type': Variant('s', 'command')})
        print("Notifications active. Measurements will be typed at cursor position.")

        # Keep alive loop
        while True:
            await asyncio.sleep(1)

    except Exception as e:
        print(f"\n[!] Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
