import asyncio
from dbus_next.aio import MessageBus
from dbus_next import BusType, Variant
from pynput.keyboard import Controller

# UUIDs for FNIRSI IR40
NOTIFY_UUID = "0000ee02-0000-1000-8000-00805f9b34fb"
WRITE_UUID  = "0000ee03-0000-1000-8000-00805f9b34fb"

# Payloads
HEARTBEAT_PAYLOAD = b'\x00\x01\x02\x01\x05\x00\x00\x00\x01'
TRIGGER_PAYLOAD = b'\x00\x07\x02\x08\x0e\x00\x00\x00\x01'

keyboard = Controller()

def parse_distance_mm(data: bytes):
    """
    Parses FNIRSI IR40 packet.
    Packet starts with 00 .. 02 01 for measurements.
    Distance is a 2-byte BIG ENDIAN integer at index 14.
    """
    if len(data) >= 17 and data[0] == 0x00 and data[2] == 0x02:
        # Index 14 and 15 contain the big-endian mm value (e.g., 05 85 -> 1413)
        # We use big-endian to correctly interpret 0x0585 as 1413
        dist_mm = int.from_bytes(data[14:16], "big")
        
        # Validation: Ignore 0 or suspicious values (like heartbeat markers)
        if dist_mm > 0:
            return dist_mm
    return None

async def select_device(bus):
    print("Scanning for Bluetooth devices...")
    root_intro = await bus.introspect('org.bluez', '/')
    root_proxy = bus.get_proxy_object('org.bluez', '/', root_intro)
    obj_manager = root_proxy.get_interface('org.freedesktop.DBus.ObjectManager')
    
    objs = await obj_manager.call_get_managed_objects()
    devices = []
    for path, interfaces in objs.items():
        if 'org.bluez.Device1' in interfaces:
            props = interfaces['org.bluez.Device1']
            alias = props.get('Alias', Variant('s', 'Unknown')).value
            address = props.get('Address', Variant('s', 'Unknown')).value
            devices.append({'alias': alias, 'address': address, 'path': path})

    if not devices:
        print("No devices found. Ensure Bluetooth is on.")
        return None

    print("\n--- Available Devices ---")
    for i, dev in enumerate(devices):
        print(f"[{i}] {dev['alias']} ({dev['address']})")
    
    try:
        choice = input("\nSelect device index: ")
        return devices[int(choice)]
    except (ValueError, IndexError):
        return None

async def heartbeat_loop(write_iface):
    """Keeps the laser awake."""
    while True:
        try:
            await write_iface.call_write_value(HEARTBEAT_PAYLOAD, {'type': Variant('s', 'command')})
            await asyncio.sleep(25)
        except:
            break

async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    selected = await select_device(bus)
    if not selected: return

    device_path = selected['path']
    device_intro = await bus.introspect('org.bluez', device_path)
    device_proxy = bus.get_proxy_object('org.bluez', device_path, device_intro)
    device_iface = device_proxy.get_interface('org.bluez.Device1')

    if not await device_iface.get_connected():
        print(f"Connecting to {selected['address']}...")
        await device_iface.call_connect()

    while not await device_iface.get_services_resolved():
        await asyncio.sleep(0.5)

    # Find GATT paths
    root_intro = await bus.introspect('org.bluez', '/')
    root_proxy = bus.get_proxy_object('org.bluez', '/', root_intro)
    obj_manager = root_proxy.get_interface('org.freedesktop.DBus.ObjectManager')
    objs = await obj_manager.call_get_managed_objects()
    
    write_path = notify_path = None
    for path, ifaces in objs.items():
        if 'org.bluez.GattCharacteristic1' in ifaces and path.startswith(device_path):
            uuid = ifaces['org.bluez.GattCharacteristic1']['UUID'].value.lower()
            if uuid == WRITE_UUID: write_path = path
            elif uuid == NOTIFY_UUID: notify_path = path

    # Notifications
    notify_intro = await bus.introspect('org.bluez', notify_path)
    notify_proxy = bus.get_proxy_object('org.bluez', notify_path, notify_intro)
    props_iface = notify_proxy.get_interface('org.freedesktop.DBus.Properties')
    notify_iface = notify_proxy.get_interface('org.bluez.GattCharacteristic1')

    def on_val_change(iface, changed, invalidated):
        if 'Value' in changed:
            raw_bytes = bytes(changed['Value'].value)
            mm = parse_distance_mm(raw_bytes)
            if mm:
                print(f">> Parsed: {mm}mm")
                keyboard.type(str(mm))

    props_iface.on_properties_changed(on_val_change)
    await notify_iface.call_start_notify()

    # Heartbeat and Trigger
    write_intro = await bus.introspect('org.bluez', write_path)
    write_proxy = bus.get_proxy_object('org.bluez', write_path, write_intro)
    write_iface = write_proxy.get_interface('org.bluez.GattCharacteristic1')

    asyncio.create_task(heartbeat_loop(write_iface))

    print("\nREADY!")
    print("- Press ENTER to trigger laser")
    print("- Reading in MM (Big Endian Fix applied)")

    while True:
        await asyncio.get_event_loop().run_in_executor(None, input, "")
        await write_iface.call_write_value(TRIGGER_PAYLOAD, {'type': Variant('s', 'command')})

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
