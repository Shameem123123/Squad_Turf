"""Minimal QR Code encoder (ISO/IEC 18004) with no third-party dependencies.

Scope is deliberate: byte mode, error-correction level M, versions 1-10
(up to 213 bytes). That is plenty for a signed booking reference and means
the project needs no extra package to issue scannable tickets.

    svg(text)      -> '<svg ...>' string, ready to inline in a template
    matrix(text)   -> list of rows of bools (True = dark module)
"""
from html import escape

# (version) -> (data codewords, ec codewords per block, [(block count, data codewords per block)])
_VERSIONS = {
    1: (16, 10, [(1, 16)]),
    2: (28, 16, [(1, 28)]),
    3: (44, 26, [(1, 44)]),
    4: (64, 18, [(2, 32)]),
    5: (86, 24, [(2, 43)]),
    6: (108, 16, [(4, 27)]),
    7: (124, 18, [(4, 31)]),
    8: (154, 22, [(2, 38), (2, 39)]),
    9: (182, 22, [(3, 36), (2, 37)]),
    10: (216, 26, [(4, 43), (1, 44)]),
}
MAX_BYTES = 213


# ---------------------------------------------------------------------------
# Reed-Solomon over GF(256)
# ---------------------------------------------------------------------------

_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if not a or not b else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree):
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _mul(coef, _EXP[i])
        poly = nxt
    return poly


def _remainder(data, degree):
    gen = _generator(degree)
    rem = list(data) + [0] * degree
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j in range(1, len(gen)):
                rem[i + j] ^= _mul(gen[j], coef)
    return rem[len(data):]


# ---------------------------------------------------------------------------
# Codeword assembly
# ---------------------------------------------------------------------------

def _pick_version(n_bytes):
    for version, (data_cw, _, _) in _VERSIONS.items():
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + 8 * n_bytes <= data_cw * 8:
            return version
    raise ValueError(f"Text too long for a QR code ({n_bytes} bytes, max {MAX_BYTES}).")


def _data_codewords(payload, version):
    data_cw = _VERSIONS[version][0]
    bits = [0, 1, 0, 0]  # byte mode
    count_bits = 8 if version < 10 else 16
    bits += [(len(payload) >> i) & 1 for i in range(count_bits - 1, -1, -1)]
    for byte in payload:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    capacity = data_cw * 8
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    out = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad, i = (0xEC, 0x11), 0
    while len(out) < data_cw:
        out.append(pad[i % 2])
        i += 1
    return out


def _interleave(data, version):
    _, ec_len, groups = _VERSIONS[version]
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[pos:pos + size])
            pos += size
    ecc = [_remainder(block, ec_len) for block in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec_len):
        out += [e[i] for e in ecc]
    return out


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------

def _alignment_positions(version):
    if version == 1:
        return []
    count = version // 7 + 2
    step = (version * 4 + count * 2 + 1) // (count * 2 - 2) * 2
    size = version * 4 + 17
    return [6] + [size - 7 - i * step for i in range(count - 2, -1, -1)]


class _Grid:
    def __init__(self, version):
        self.version = version
        self.size = version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.func = [[False] * self.size for _ in range(self.size)]
        self._draw_function_patterns()

    def _set(self, x, y, dark):
        self.dark[y][x] = bool(dark)
        self.func[y][x] = True

    def _finder(self, cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.size and 0 <= y < self.size:
                    dist = max(abs(dx), abs(dy))
                    self._set(x, y, dist not in (2, 4))

    def _alignment(self, cx, cy):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self._set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    def _draw_function_patterns(self):
        size = self.size
        for i in range(size):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        self._finder(3, 3)
        self._finder(size - 4, 3)
        self._finder(3, size - 4)
        pos = _alignment_positions(self.version)
        last = len(pos) - 1
        for i, py in enumerate(pos):
            for j, px in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == last) or (i == last and j == 0):
                    continue
                self._alignment(px, py)
        self._format_bits(0)  # reserve the format areas
        self._version_bits()

    def _format_bits(self, mask):
        data = (0 << 3) | mask  # EC level M = 0b00
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1  # noqa: E731
        size = self.size
        for i in range(6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(8):
            self._set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, size - 15 + i, bit(i))
        self._set(8, size - 8, True)  # always-dark module

    def _version_bits(self):
        if self.version < 7:
            return
        rem = self.version
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = (self.version << 12) | rem
        for i in range(18):
            a, b = self.size - 11 + i % 3, i // 3
            self._set(a, b, (bits >> i) & 1)
            self._set(b, a, (bits >> i) & 1)

    def place(self, codewords):
        size, i, total = self.size, 0, len(codewords) * 8
        for right in range(size - 1, 0, -2):
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            for vert in range(size):
                y = size - 1 - vert if upward else vert
                for j in range(2):
                    x = right - j
                    if not self.func[y][x] and i < total:
                        self.dark[y][x] = bool((codewords[i >> 3] >> (7 - (i & 7))) & 1)
                        i += 1

    def apply_mask(self, mask):
        test = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.func[y][x] and test(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self):
        size, g, score = self.size, self.dark, 0
        lines = [row[:] for row in g] + [[g[y][x] for y in range(size)] for x in range(size)]
        for line in lines:  # runs of 5+ same-colour modules, and finder-like patterns
            run = 1
            for k in range(1, size):
                run = run + 1 if line[k] == line[k - 1] else 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            text = "".join("1" if v else "0" for v in line)
            score += 40 * (text.count("10111010000") + text.count("00001011101"))
        for y in range(size - 1):  # 2x2 blocks
            for x in range(size - 1):
                if g[y][x] == g[y][x + 1] == g[y + 1][x] == g[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in g)
        score += abs(dark * 20 - size * size * 10) // (size * size) * 10
        return score


_MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def matrix(text):
    """Encode `text` and return the module matrix (list of rows of bools)."""
    payload = text.encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError(f"Text too long for a QR code ({len(payload)} bytes, max {MAX_BYTES}).")
    version = _pick_version(len(payload))
    codewords = _interleave(_data_codewords(payload, version), version)
    best = None
    for mask in range(8):
        grid = _Grid(version)
        grid.place(codewords)
        grid.apply_mask(mask)
        grid._format_bits(mask)
        score = grid.penalty()
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1].dark


def svg(text, *, quiet=4, label="QR code"):
    """Return an inline SVG. Dark modules are drawn as one merged path."""
    rows = matrix(text)
    size = len(rows)
    parts = []
    for y, row in enumerate(rows):
        x = 0
        while x < size:
            if row[x]:
                start = x
                while x < size and row[x]:
                    x += 1
                parts.append(f"M{start + quiet} {y + quiet}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    full = size + quiet * 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {full} {full}" '
        f'role="img" aria-label="{escape(label)}" shape-rendering="crispEdges">'
        f'<rect width="{full}" height="{full}" fill="#fff"/>'
        f'<path d="{"".join(parts)}" fill="#000"/></svg>'
    )
