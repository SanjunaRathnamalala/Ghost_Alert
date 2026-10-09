"""
Binary LoRa packet format (design topic 2a). Little-endian.

Header (7 bytes): version+type (1) | node radio ID (2) | boot number (2) | counter (2)
Body: depends on type (below)
Seal (4 bytes): at the end. Zeros in the prototype (decision 1.3).

The encoder is here too, so the tests, the fake gateway and the simulator
all use exactly the same layout as the decoder.
"""
import struct
from dataclasses import dataclass

VERSION = 1
SEAL_LEN = 4
HEADER = struct.Struct("<BHHH")

BOOT, HEARTBEAT, BURST, PIR_EVENT, PIR_HEARTBEAT = 1, 2, 3, 4, 5

# type -> (name, body struct, body field names)
BODIES = {
    BOOT: ("boot", struct.Struct("<BBB"),
           ("firmware_version", "reset_reason", "node_type")),
    HEARTBEAT: ("heartbeat", struct.Struct("<hhh5HHhB"),
                ("accel_x", "accel_y", "accel_z",
                 "m0", "m1", "m2", "m3", "m4",
                 "battery_mv", "temp_c10", "flags")),
    BURST: ("burst", struct.Struct("<hhhHBB"),
            ("accel_x", "accel_y", "accel_z", "peak_change_mg", "duration_s", "flags")),
    PIR_EVENT: ("pir_event", struct.Struct("<BHB"),
                ("triggers", "battery_mv", "flags")),
    PIR_HEARTBEAT: ("pir_heartbeat", struct.Struct("<HHB"),
                    ("triggers", "battery_mv", "flags")),
}

# Flag bits (1 byte)
FLAG_SOIL_ERROR = 0x01
FLAG_ACCEL_ERROR = 0x02
FLAG_BATTERY_LOW = 0x04

NODE_TYPE_CODES = {1: "landslide", 2: "wildlife"}
RESET_REASONS = {1: "power on", 2: "reset pin", 4: "brown-out (low voltage)", 8: "watchdog (crash)"}


class PacketError(ValueError):
    pass


@dataclass
class Packet:
    version: int
    msg_type: int
    kind: str
    radio_id: int
    boot: int
    counter: int
    body: dict
    seal: bytes

    @property
    def moisture_raw(self):
        return [self.body[f"m{i}"] for i in range(5)] if self.msg_type == HEARTBEAT else []


def packet_size(msg_type: int) -> int:
    return HEADER.size + BODIES[msg_type][1].size + SEAL_LEN


def decode(data: bytes) -> Packet:
    if len(data) < HEADER.size + SEAL_LEN:
        raise PacketError(f"packet too short ({len(data)} bytes)")
    ver_type, radio_id, boot, counter = HEADER.unpack_from(data, 0)
    version, msg_type = ver_type >> 4, ver_type & 0x0F
    if version != VERSION:
        raise PacketError(f"unsupported packet version {version}")
    if msg_type not in BODIES:
        raise PacketError(f"unknown message type {msg_type}")
    if radio_id == 0:
        raise PacketError("radio ID 0 is not allowed")
    name, body_struct, names = BODIES[msg_type]
    expected = packet_size(msg_type)
    if len(data) != expected:
        raise PacketError(f"{name} packet must be {expected} bytes, got {len(data)}")
    values = body_struct.unpack_from(data, HEADER.size)
    seal = bytes(data[-SEAL_LEN:])
    return Packet(version, msg_type, name, radio_id, boot, counter, dict(zip(names, values)), seal)


def decode_hex(payload_hex: str) -> Packet:
    try:
        data = bytes.fromhex(payload_hex)
    except ValueError as exc:
        raise PacketError("payload_hex is not valid hex") from exc
    return decode(data)


def encode(msg_type: int, radio_id: int, boot: int, counter: int, seal: bytes = b"\x00" * SEAL_LEN, **body) -> bytes:
    """Build a packet. Used by tests, the fake gateway and the simulator."""
    _, body_struct, names = BODIES[msg_type]
    missing = [n for n in names if n not in body]
    if missing:
        raise PacketError(f"missing body fields: {missing}")
    header = HEADER.pack((VERSION << 4) | msg_type, radio_id, boot, counter)
    return header + body_struct.pack(*(body[n] for n in names)) + seal
