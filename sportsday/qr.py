"""Lightweight QR code generator for server-side SVG output.

The implementation intentionally covers only the functionality required by
the Sports Day console: QR Codes rendered in byte mode using version 4 with
low error correction. That envelope comfortably fits the URLs generated for
event results while keeping the implementation compact and dependency-free.
"""
from __future__ import annotations

SIZE = 33  # Version 4 modules per side
VERSION = 4
ERROR_CORRECTION_LEVEL = "L"
DATA_CODEWORDS = 64
EC_CODEWORDS = 16
TOTAL_CODEWORDS = DATA_CODEWORDS + EC_CODEWORDS

POLY = 0x11D


def _init_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= POLY
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


GF_EXP, GF_LOG = _init_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[GF_LOG[a] + GF_LOG[b]]


def _poly_mul(p: list[int], q: list[int]) -> list[int]:
    result = [0] * (len(p) + len(q) - 1)
    for i, coeff_p in enumerate(p):
        for j, coeff_q in enumerate(q):
            result[i + j] ^= _gf_mul(coeff_p, coeff_q)
    return result


def _generator_poly(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        poly = _poly_mul(poly, [1, GF_EXP[i]])
    return poly


GENERATOR = _generator_poly(EC_CODEWORDS)


def _reed_solomon_remainder(data: list[int], generator: list[int]) -> list[int]:
    remainder = [0] * (len(generator) - 1)
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor:
            for idx in range(len(generator) - 1):
                remainder[idx] ^= _gf_mul(generator[idx + 1], factor)
    return remainder


def _append_bits(buffer: list[int], value: int, length: int) -> None:
    for i in range(length - 1, -1, -1):
        buffer.append((value >> i) & 1)


def _build_base_matrix() -> tuple[list[list[int | None]], list[list[bool]]]:
    modules: list[list[int | None]] = [[None for _ in range(SIZE)] for _ in range(SIZE)]
    function_mask: list[list[bool]] = [[False for _ in range(SIZE)] for _ in range(SIZE)]

    def place_module(row: int, col: int, value: int, is_function: bool = True) -> None:
        if 0 <= row < SIZE and 0 <= col < SIZE:
            modules[row][col] = value
            if is_function:
                function_mask[row][col] = True

    def draw_finder(row: int, col: int) -> None:
        pattern = [
            [1, 1, 1, 1, 1, 1, 1],
            [1, 0, 0, 0, 0, 0, 1],
            [1, 0, 1, 1, 1, 0, 1],
            [1, 0, 1, 1, 1, 0, 1],
            [1, 0, 1, 1, 1, 0, 1],
            [1, 0, 0, 0, 0, 0, 1],
            [1, 1, 1, 1, 1, 1, 1],
        ]
        for r in range(7):
            for c in range(7):
                place_module(row + r, col + c, pattern[r][c])
        # Separator
        for r in range(-1, 8):
            for c in (-1, 7):
                place_module(row + r, col + c, 0)
        for r in (-1, 7):
            for c in range(-1, 8):
                place_module(row + r, col + c, 0)

    draw_finder(0, 0)
    draw_finder(0, SIZE - 7)
    draw_finder(SIZE - 7, 0)

    # Timing patterns
    for i in range(8, SIZE - 8):
        value = i % 2
        place_module(6, i, value)
        place_module(i, 6, value)

    # Alignment patterns (version 4 -> centres at 6 and 26)
    positions = [6, 26]
    alignment_pattern = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 1, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    for row in positions:
        for col in positions:
            if (row == 6 and col == 6) or (row == 6 and col == SIZE - 7) or (row == SIZE - 7 and col == 6):
                continue
            if modules[row][col] is not None:
                continue
            for r in range(5):
                for c in range(5):
                    place_module(row - 2 + r, col - 2 + c, alignment_pattern[r][c])

    # Dark module
    place_module(8, SIZE - 8, 1)

    return modules, function_mask


def _apply_format_information(modules: list[list[int | None]], function_mask: list[list[bool]], mask: int) -> None:
    format_data = 0b01 << 3 | mask  # Level L (01)
    generator = 0b10100110111
    bits = format_data << 10
    for i in range(14, 9, -1):
        if bits & (1 << i):
            bits ^= generator << (i - 10)
    format_bits = (format_data << 10) | bits
    format_bits ^= 0b101010000010010

    def place(row: int, col: int, bit_index: int) -> None:
        value = (format_bits >> bit_index) & 1
        modules[row][col] = value
        function_mask[row][col] = True

    # Top-left and around
    for i in range(6):
        place(8, i, i)
    place(8, 7, 6)
    place(8, 8, 7)
    place(7, 8, 8)
    for i in range(6):
        place(5 - i, 8, 9 + i)

    # Other format info areas
    for i in range(7):
        place(SIZE - 1 - i, 8, i)
    for i in range(8):
        col = SIZE - 1 - i
        if col == SIZE - 8:  # Skip dark module
            continue
        place(8, col, 8 + i)


def _data_mask(row: int, col: int, mask: int) -> int:
    if mask == 0:
        return (row + col) % 2 == 0
    raise ValueError("Unsupported mask pattern")


def make_matrix(data: str) -> list[list[int]]:
    payload = data.encode("utf-8")
    if len(payload) > DATA_CODEWORDS:
        raise ValueError("QR payload too large for version 4-L code")

    bit_buffer: list[int] = []
    _append_bits(bit_buffer, 0b0100, 4)  # Byte mode
    _append_bits(bit_buffer, len(payload), 8)
    for byte in payload:
        _append_bits(bit_buffer, byte, 8)

    capacity = DATA_CODEWORDS * 8
    terminator_len = min(4, capacity - len(bit_buffer))
    _append_bits(bit_buffer, 0, terminator_len)
    while len(bit_buffer) % 8 != 0:
        bit_buffer.append(0)

    data_bytes = []
    for i in range(0, len(bit_buffer), 8):
        byte = 0
        for bit in bit_buffer[i : i + 8]:
            byte = (byte << 1) | bit
        data_bytes.append(byte)
    pad_bytes = [0xEC, 0x11]
    pad_index = 0
    while len(data_bytes) < DATA_CODEWORDS:
        data_bytes.append(pad_bytes[pad_index % 2])
        pad_index += 1

    remainder = _reed_solomon_remainder(data_bytes, GENERATOR)
    codewords = data_bytes + remainder

    all_bits: list[int] = []
    for byte in codewords:
        for i in range(7, -1, -1):
            all_bits.append((byte >> i) & 1)

    modules, function_mask = _build_base_matrix()

    bit_index = 0
    direction = -1
    col = SIZE - 1
    row = SIZE - 1
    while col > 0:
        if col == 6:
            col -= 1
        for _ in range(SIZE):
            for offset in (0, 1):
                current_col = col - offset
                if function_mask[row][current_col]:
                    continue
                bit = all_bits[bit_index] if bit_index < len(all_bits) else 0
                bit_index += 1 if bit_index < len(all_bits) else 0
                masked = bit ^ _data_mask(row, current_col, 0)
                modules[row][current_col] = 1 if masked else 0
            row += direction
            if row < 0 or row >= SIZE:
                row -= direction
                direction *= -1
                break
        col -= 2

    _apply_format_information(modules, function_mask, mask=0)

    # Replace any remaining None with 0 for completeness
    final = [[1 if cell else 0 for cell in row] for row in modules]
    return final


def make_svg(data: str, scale: int = 5, border: int = 4) -> str:
    matrix = make_matrix(data)
    dimension = SIZE + border * 2
    pixel_size = dimension * scale
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {dimension} {dimension}" '
            f'width="{pixel_size}" height="{pixel_size}" '
            f'shape-rendering="crispEdges">'
        ),
        f'<rect width="{dimension}" height="{dimension}" fill="#ffffff"/>',
    ]
    for r, row in enumerate(matrix):
        for c, value in enumerate(row):
            if value:
                x = c + border
                y = r + border
                parts.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#000000"/>')
    parts.append("</svg>")
    return "".join(parts)
