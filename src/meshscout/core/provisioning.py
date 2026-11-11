"""Multi-protocol radio provisioning engine and pure-Python SVG QR code generator.

Provides zero-external-dependency configuration synthesis for Meshtastic, MeshCore,
and Reticulum Network Stack (RNS), generating URL/CLI payloads and embedded SVG QR matrices.
"""

from __future__ import annotations

import base64
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from meshscout.core.contracts import SiteCandidate
from meshscout.core.presets import PROTOCOL_PROFILES, ProtocolProfile


class ProvisioningTarget(str, Enum):
    """Supported physical mesh radio firmware/daemon ecosystem."""

    MESHTASTIC = "meshtastic"
    MESHCORE = "meshcore"
    RETICULUM = "reticulum"


class ProvisioningPayload(BaseModel):
    """Complete provisioning bundle for a physical node deployment."""

    target: ProvisioningTarget = Field(..., description="Target protocol ecosystem")
    site_id: str = Field(..., description="Site identifier")
    channel_name: str = Field(..., description="Provisioned channel or interface name")
    frequency_mhz: float = Field(..., description="Center frequency in MHz")
    bandwidth_khz: float = Field(..., description="Channel bandwidth in kHz")
    spreading_factor: int = Field(..., description="LoRa Spreading Factor")
    raw_url_or_text: str = Field(..., description="Raw shareable configuration URL or config stanza")
    cli_commands: List[str] = Field(default_factory=list, description="Ready-to-paste CLI execution commands")
    inline_svg_qr: str = Field(..., description="Pure-Python generated inline SVG QR code")


# ==============================================================================
# Pure-Python QR Code Engine (Versions 1-10, Byte Mode, ECC Level M, ISO/IEC 18004)
# ==============================================================================

# GF(2^8) Galois Field arithmetic tables (primitive polynomial 0x11D = 285)
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x >= 256:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    """Galois Field GF(2^8) multiplication."""
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator_poly(degree: int) -> List[int]:
    """Generate Reed-Solomon generator polynomial for a given degree."""
    g = [1]
    for i in range(degree):
        next_g = [0] * (len(g) + 1)
        for j in range(len(g)):
            next_g[j] ^= g[j]
            next_g[j + 1] ^= _gf_mul(g[j], _EXP[i])
        g = next_g
    return g


def _rs_encode(data: List[int], ec_len: int) -> List[int]:
    """Compute Reed-Solomon error correction codewords for a block of data bytes."""
    gen = _rs_generator_poly(ec_len)
    remainder = [0] * ec_len
    for b in data:
        factor = b ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor != 0:
            for i in range(ec_len):
                remainder[i] ^= _gf_mul(gen[i + 1], factor)
    return remainder


# Version parameters for ECC Level M: (total_cw, ec_per_block, g1_blocks, g1_data, g2_blocks, g2_data)
_VERSION_PARAMS_M: List[Tuple[int, int, int, int, int, int]] = [
    (0, 0, 0, 0, 0, 0),        # 0 (unused)
    (26, 10, 1, 16, 0, 0),     # V1 (21x21)
    (44, 16, 1, 28, 0, 0),     # V2 (25x25)
    (70, 26, 1, 44, 0, 0),     # V3 (29x29)
    (100, 18, 2, 32, 0, 0),    # V4 (33x33)
    (134, 24, 2, 43, 0, 0),    # V5 (37x37)
    (172, 16, 4, 27, 0, 0),    # V6 (41x41)
    (196, 18, 4, 31, 0, 0),    # V7 (45x45)
    (242, 22, 2, 38, 2, 39),   # V8 (49x49)
    (292, 22, 3, 36, 2, 37),   # V9 (53x53)
    (346, 26, 4, 43, 1, 44),   # V10 (57x57)
]

# Alignment pattern center module coordinates for Versions 1-10
_ALIGNMENT_PATTERNS: List[List[int]] = [
    [],
    [],
    [6, 18],
    [6, 22],
    [6, 26],
    [6, 30],
    [6, 34],
    [6, 22, 38],
    [6, 24, 42],
    [6, 26, 46],
    [6, 28, 50],
]

# Remainder bits to append after final codeword bitstream
_REMAINDER_BITS: List[int] = [0, 0, 7, 7, 7, 7, 7, 0, 0, 0, 0]


def select_qr_version(data_byte_len: int) -> int:
    """Find the minimum QR version (1-10) capable of holding data_byte_len in Byte mode (Level M)."""
    for v in range(1, 11):
        p = _VERSION_PARAMS_M[v]
        total_data = p[2] * p[3] + p[4] * p[5]
        char_count_bits = 8 if v < 10 else 16
        header_bits = 4 + char_count_bits
        max_bytes = (total_data * 8 - header_bits) // 8
        if data_byte_len <= max_bytes:
            return v
    raise ValueError(
        f"Data length ({data_byte_len} bytes) exceeds maximum capacity for QR versions 1-10 Level M (213 bytes)"
    )


def _encode_qr_data_bits(data_bytes: bytes, version: int) -> List[int]:
    """Encode binary payload into QR bitstream with headers, padding, Reed-Solomon EC, and interleaving."""
    p = _VERSION_PARAMS_M[version]
    total_data_cw = p[2] * p[3] + p[4] * p[5]
    bits: List[int] = []

    # 1. Mode indicator: 0100 (byte mode)
    bits.extend([0, 1, 0, 0])

    # 2. Character count indicator
    char_count_bits = 8 if version < 10 else 16
    char_len = len(data_bytes)
    for i in range(char_count_bits - 1, -1, -1):
        bits.append((char_len >> i) & 1)

    # 3. Data bytes
    for b in data_bytes:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)

    # 4. Terminator (up to 4 zeroes)
    max_data_bits = total_data_cw * 8
    term_len = min(4, max_data_bits - len(bits))
    bits.extend([0] * term_len)

    # 5. Pad to multiple of 8
    if len(bits) % 8 != 0:
        bits.extend([0] * (8 - (len(bits) % 8)))

    # Convert to codeword bytes
    data_cw: List[int] = []
    for i in range(0, len(bits), 8):
        byte_val = 0
        for bit in bits[i : i + 8]:
            byte_val = (byte_val << 1) | bit
        data_cw.append(byte_val)

    # 6. Pad bytes 0xEC and 0x11
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(data_cw) < total_data_cw:
        data_cw.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    # 7. Divide into blocks and compute Reed-Solomon EC
    g1_blocks, g1_data = p[2], p[3]
    g2_blocks, g2_data = p[4], p[5]
    ec_per_block = p[1]

    blocks_data: List[List[int]] = []
    blocks_ec: List[List[int]] = []
    offset = 0

    for _ in range(g1_blocks):
        blk = data_cw[offset : offset + g1_data]
        offset += g1_data
        blocks_data.append(blk)
        blocks_ec.append(_rs_encode(blk, ec_per_block))

    for _ in range(g2_blocks):
        blk = data_cw[offset : offset + g2_data]
        offset += g2_data
        blocks_data.append(blk)
        blocks_ec.append(_rs_encode(blk, ec_per_block))

    # 8. Interleave data codewords across all blocks
    interleaved: List[int] = []
    max_data_len = max(len(b) for b in blocks_data)
    for col in range(max_data_len):
        for blk in blocks_data:
            if col < len(blk):
                interleaved.append(blk[col])

    # Interleave EC codewords across all blocks
    for col in range(ec_per_block):
        for blk in blocks_ec:
            interleaved.append(blk[col])

    # Convert to bitstream
    final_bits: List[int] = []
    for cw in interleaved:
        for i in range(7, -1, -1):
            final_bits.append((cw >> i) & 1)

    # 9. Remainder bits
    final_bits.extend([0] * _REMAINDER_BITS[version])
    return final_bits


def build_qr_matrix(content: str, force_version: Optional[int] = None) -> List[List[bool]]:
    """Build a deterministic QR boolean matrix (True = dark module, False = light)."""
    try:
        import segno
        qr = segno.make(content, version=force_version, error="m", boost_error=False, micro=False)
        return [[bool(b) for b in row] for row in qr.matrix]
    except ImportError:
        pass

    data_bytes = content.encode("utf-8")
    version = force_version if force_version is not None else select_qr_version(len(data_bytes))
    size = 17 + 4 * version
    final_bits = _encode_qr_data_bits(data_bytes, version)

    modules = [[False] * size for _ in range(size)]
    is_function = [[False] * size for _ in range(size)]

    # 1. Finder patterns and 1-module separators
    def draw_finder(ox: int, oy: int) -> None:
        for y in range(7):
            for x in range(7):
                is_function[oy + y][ox + x] = True
                modules[oy + y][ox + x] = y in (0, 6) or x in (0, 6) or (2 <= y <= 4 and 2 <= x <= 4)
        for y in range(-1, 8):
            for x in range(-1, 8):
                if y in (-1, 7) or x in (-1, 7):
                    px, py = ox + x, oy + y
                    if 0 <= px < size and 0 <= py < size:
                        is_function[py][px] = True
                        modules[py][px] = False

    draw_finder(0, 0)
    draw_finder(size - 7, 0)
    draw_finder(0, size - 7)

    # 2. Timing patterns
    for i in range(8, size - 8):
        modules[6][i] = i % 2 == 0
        is_function[6][i] = True
        modules[i][6] = i % 2 == 0
        is_function[i][6] = True

    # 3. Alignment patterns (V >= 2)
    if version >= 2:
        coords = _ALIGNMENT_PATTERNS[version]
        for cy in coords:
            for cx in coords:
                if (cy < 9 and cx < 9) or (cy < 9 and cx >= size - 9) or (cy >= size - 9 and cx < 9):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        px, py = cx + dx, cy + dy
                        is_function[py][px] = True
                        modules[py][px] = max(abs(dy), abs(dx)) == 2 or (dy == 0 and dx == 0)

    # 4. Dark module
    modules[size - 8][8] = True
    is_function[size - 8][8] = True

    # 5. Reserve Format Info modules
    for i in range(6):
        is_function[i][8] = True
    is_function[7][8] = True
    is_function[8][8] = True
    is_function[8][7] = True
    for i in range(9, 15):
        is_function[8][14 - i] = True

    for i in range(8):
        is_function[8][size - 1 - i] = True
    for i in range(8, 15):
        is_function[size - 15 + i][8] = True

    # 6. Version Info (V >= 7)
    if version >= 7:
        rem = version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vbits = (version << 12) | rem
        for i in range(18):
            bit = bool((vbits >> i) & 1)
            a = size - 11 + (i % 3)
            b = i // 3
            is_function[a][b] = True
            modules[a][b] = bit
            is_function[b][a] = True
            modules[b][a] = bit

    # 7. Zigzag data placement
    bit_idx = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vert) if upward else vert
                if not is_function[y][x]:
                    if bit_idx < len(final_bits):
                        modules[y][x] = final_bits[bit_idx] == 1
                        bit_idx += 1
                    else:
                        modules[y][x] = False
        right -= 2

    # 8. Penalty evaluation and optimal mask selection
    def compute_penalty(grid: List[List[bool]]) -> int:
        score = 0
        # N1: Horizontal and vertical runs >= 5
        for y in range(size):
            run_color = grid[y][0]
            run_len = 1
            for x in range(1, size):
                if grid[y][x] == run_color:
                    run_len += 1
                else:
                    if run_len >= 5:
                        score += 3 + (run_len - 5)
                    run_color = grid[y][x]
                    run_len = 1
            if run_len >= 5:
                score += 3 + (run_len - 5)

        for x in range(size):
            run_color = grid[0][x]
            run_len = 1
            for y in range(1, size):
                if grid[y][x] == run_color:
                    run_len += 1
                else:
                    if run_len >= 5:
                        score += 3 + (run_len - 5)
                    run_color = grid[y][x]
                    run_len = 1
            if run_len >= 5:
                score += 3 + (run_len - 5)

        # N2: 2x2 blocks of same color
        for y in range(size - 1):
            for x in range(size - 1):
                c = grid[y][x]
                if c == grid[y + 1][x] == grid[y][x + 1] == grid[y + 1][x + 1]:
                    score += 3

        # N3: Finder-like patterns (00001011101 or 10111010000)
        pattern_a = [False, False, False, False, True, False, True, True, True, False, True]
        pattern_b = [True, False, True, True, True, False, True, False, False, False, False]
        for y in range(size):
            row = grid[y]
            for x in range(size - 10):
                sub = row[x : x + 11]
                if sub == pattern_a or sub == pattern_b:
                    score += 40

        for x in range(size):
            col = [grid[y][x] for y in range(size)]
            for y in range(size - 10):
                sub = col[y : y + 11]
                if sub == pattern_a or sub == pattern_b:
                    score += 40

        # N4: Dark module ratio deviation from 50%
        dark_count = sum(row.count(True) for row in grid)
        total_modules = size * size
        ratio = (dark_count * 100) // total_modules
        k = abs(ratio - 50) // 5
        score += k * 10

        return score

    best_score = float("inf")
    best_grid: List[List[bool]] = modules

    for mask in range(8):
        masked = [row[:] for row in modules]
        for y in range(size):
            for x in range(size):
                if not is_function[y][x]:
                    inv = False
                    if mask == 0:
                        inv = (y + x) % 2 == 0
                    elif mask == 1:
                        inv = y % 2 == 0
                    elif mask == 2:
                        inv = x % 3 == 0
                    elif mask == 3:
                        inv = (y + x) % 3 == 0
                    elif mask == 4:
                        inv = (y // 2 + x // 3) % 2 == 0
                    elif mask == 5:
                        inv = ((y * x) % 2) + ((y * x) % 3) == 0
                    elif mask == 6:
                        inv = (((y * x) % 2) + ((y * x) % 3)) % 2 == 0
                    elif mask == 7:
                        inv = (((y + x) % 2) + ((y * x) % 3)) % 2 == 0
                    if inv:
                        masked[y][x] = not masked[y][x]

        # Draw format bits for Level M (0) and candidate mask
        fdata = (0 << 3) | mask
        rem = fdata
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        fbits = (fdata << 10 | rem) ^ 0x5412

        # First copy
        for i in range(6):
            masked[i][8] = bool((fbits >> i) & 1)
        masked[7][8] = bool((fbits >> 6) & 1)
        masked[8][8] = bool((fbits >> 7) & 1)
        masked[8][7] = bool((fbits >> 8) & 1)
        for i in range(9, 15):
            masked[8][14 - i] = bool((fbits >> i) & 1)

        # Second copy
        for i in range(8):
            masked[8][size - 1 - i] = bool((fbits >> i) & 1)
        for i in range(8, 15):
            masked[size - 15 + i][8] = bool((fbits >> i) & 1)
        masked[size - 8][8] = True

        pen = compute_penalty(masked)
        if pen < best_score:
            best_score = pen
            best_grid = masked

    return best_grid


def generate_qr_svg(content: str, box_size: int = 4, border: int = 4) -> str:
    """Generate a clean, self-contained SVG string with <rect> modules for dark cells."""
    matrix = build_qr_matrix(content)
    size = len(matrix)
    dim = (size + 2 * border) * box_size
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{dim}" height="{dim}" viewBox="0 0 {dim} {dim}">',
        f'  <rect width="{dim}" height="{dim}" fill="#ffffff"/>',
    ]
    for y in range(size):
        for x in range(size):
            if matrix[y][x]:
                rx = (x + border) * box_size
                ry = (y + border) * box_size
                lines.append(f'  <rect x="{rx}" y="{ry}" width="{box_size}" height="{box_size}" fill="#000000"/>')
    lines.append("</svg>")
    return "\n".join(lines)


# ==============================================================================
# Multi-Protocol Wire Encoding and Configuration Generators
# ==============================================================================

def _encode_varint(value: int) -> bytes:
    """Encode an integer into protobuf varint bytes."""
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def encode_meshtastic_channel_url(channel_name: str = "MeshScout", psk_override: Optional[str] = None) -> str:
    """Encode Meshtastic ChannelSet protobuf manually into an official `https://meshtastic.org/e/#...` URL.

    Security standard: Caller-supplied PSKs are encoded in-memory only and never logged or persisted.
    """
    if psk_override is not None:
        if isinstance(psk_override, str):
            try:
                psk_bytes = base64.b64decode(psk_override, validate=True)
            except Exception:
                psk_bytes = psk_override.encode("utf-8")
        else:
            psk_bytes = bytes(psk_override)
    else:
        # Standard Meshtastic default public channel PSK (single byte 1)
        psk_bytes = b"\x01"

    name_bytes = channel_name.encode("utf-8")

    # Sub-tag 2 (psk): wire type 2 -> (2 << 3) | 2 = 18 = 0x12
    sub2 = b"\x12" + _encode_varint(len(psk_bytes)) + psk_bytes
    # Sub-tag 3 (name): wire type 2 -> (3 << 3) | 2 = 26 = 0x1a
    sub3 = b"\x1a" + _encode_varint(len(name_bytes)) + name_bytes
    channel_settings = sub2 + sub3

    # Tag 1 (settings): wire type 2 -> (1 << 3) | 2 = 10 = 0x0a
    channel_set = b"\x0a" + _encode_varint(len(channel_settings)) + channel_settings
    b64 = base64.urlsafe_b64encode(channel_set).decode("ascii").rstrip("=")
    return f"https://meshtastic.org/e/#{b64}"


def generate_meshtastic_cli_commands(
    site: SiteCandidate,
    modem_preset: str = "LONG_FAST",
    url: Optional[str] = None,
    role: str = "REPEATER",
    region: str = "US",
) -> List[str]:
    """Generate reproducible Meshtastic CLI device provisioning commands."""
    cmds = [
        f'meshtastic --set-owner "{site.name}" --set lora.region {region} --set lora.modem_preset {modem_preset}',
        f"meshtastic --set device.role {role}",
        f"meshtastic --set-lat {site.location.lat:.6f} --set-lon {site.location.lon:.6f} --set-alt {int(site.location.elevation_m)}",
    ]
    if url:
        cmds.append(f'meshtastic --set-url "{url}"')
    return cmds


def generate_meshcore_cli_commands(
    site: SiteCandidate,
    freq_mhz: float = 915.0,
    bw_khz: float = 125.0,
    sf: int = 10,
    cr: str = "4/5",
) -> List[str]:
    """Generate standard MeshCore repeater CLI configuration commands."""
    return [
        f'meshcore-cli repeater configure --freq {freq_mhz:.1f} --bw {bw_khz:.1f} --sf {sf} --cr {cr} --name "{site.name}"'
    ]


def generate_reticulum_rnode_stanza(
    site: SiteCandidate,
    freq_mhz: float = 915.0,
    bw_khz: float = 125.0,
    sf: int = 11,
    cr: int = 5,
    tx_power_dbm: float = 22.0,
    port: str = "/dev/ttyUSB0",
) -> str:
    """Generate ready-to-paste Reticulum Network Stack (rns.conf) RNodeInterface stanza."""
    freq_hz = int(round(freq_mhz * 1_000_000))
    bw_hz = int(round(bw_khz * 1_000))
    tx_power = int(round(tx_power_dbm))
    return (
        f"[[RNode-{site.site_id}]]\n"
        f"  type = RNodeInterface\n"
        f"  interface_enabled = True\n"
        f"  port = {port}\n"
        f"  frequency = {freq_hz}\n"
        f"  bandwidth = {bw_hz}\n"
        f"  txpower = {tx_power}\n"
        f"  spreadingfactor = {sf}\n"
        f"  codingrate = {cr}"
    )


def generate_site_provisioning(
    site: SiteCandidate,
    target: ProvisioningTarget = ProvisioningTarget.MESHTASTIC,
    channel_name: str = "MeshScout",
    psk_override: Optional[str] = None,
) -> ProvisioningPayload:
    """Synthesize complete multi-protocol provisioning payload and inline SVG QR code."""
    if target == ProvisioningTarget.MESHTASTIC:
        proto = PROTOCOL_PROFILES["MESHTASTIC_LONGFAST"]
        url = encode_meshtastic_channel_url(channel_name=channel_name, psk_override=psk_override)
        cmds = generate_meshtastic_cli_commands(site=site, modem_preset="LONG_FAST", url=url)
        qr_svg = generate_qr_svg(url)
        return ProvisioningPayload(
            target=target,
            site_id=site.site_id,
            channel_name=channel_name,
            frequency_mhz=proto.frequency_mhz,
            bandwidth_khz=proto.bandwidth_khz,
            spreading_factor=proto.spreading_factor,
            raw_url_or_text=url,
            cli_commands=cmds,
            inline_svg_qr=qr_svg,
        )

    elif target == ProvisioningTarget.MESHCORE:
        proto = PROTOCOL_PROFILES["MESHCORE_STANDARD"]
        cmds = generate_meshcore_cli_commands(
            site=site,
            freq_mhz=proto.frequency_mhz,
            bw_khz=proto.bandwidth_khz,
            sf=proto.spreading_factor,
        )
        cli_text = cmds[0]
        qr_svg = generate_qr_svg(cli_text)
        return ProvisioningPayload(
            target=target,
            site_id=site.site_id,
            channel_name=channel_name,
            frequency_mhz=proto.frequency_mhz,
            bandwidth_khz=proto.bandwidth_khz,
            spreading_factor=proto.spreading_factor,
            raw_url_or_text=cli_text,
            cli_commands=cmds,
            inline_svg_qr=qr_svg,
        )

    elif target == ProvisioningTarget.RETICULUM:
        proto = PROTOCOL_PROFILES["RETICULUM_RNODE_LONG"]
        stanza = generate_reticulum_rnode_stanza(
            site=site,
            freq_mhz=proto.frequency_mhz,
            bw_khz=proto.bandwidth_khz,
            sf=proto.spreading_factor,
        )
        cmds = [
            f"# Append stanza to /etc/reticulum/rns.conf on site {site.site_id}",
            "rnsd --service",
        ]
        qr_svg = generate_qr_svg(stanza)
        return ProvisioningPayload(
            target=target,
            site_id=site.site_id,
            channel_name=channel_name,
            frequency_mhz=proto.frequency_mhz,
            bandwidth_khz=proto.bandwidth_khz,
            spreading_factor=proto.spreading_factor,
            raw_url_or_text=stanza,
            cli_commands=cmds,
            inline_svg_qr=qr_svg,
        )

    raise ValueError(f"Unsupported provisioning target: {target}")
