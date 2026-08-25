#!/usr/bin/env python3
"""wrap-macbinary.py — wrap a fork-ful file into MacBinary II for hand transfer.

    wrap-macbinary.py <file with forks> <out.bin>

Reads the data fork, the resource fork (via ../..namedfork/rsrc) and the FinderInfo
xattr (type, creator, Finder flags), and emits a correct MacBinary II container with a
valid CRC-16 so StuffIt Expander accepts it.

⚠ NOT the same as `usb2-ehci/rom/wrap_macbinary.py`, which is DEAD for Mac OS ROMs
because it fabricates a small resource fork of its own and thereby discards the real one
(taking the ~185 KB System Enabler with it). This one carries the REAL resource fork
through, which is the whole point when the payload we care about lives in the fork.
"""
import os, struct, subprocess, sys


def crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def finder_info(path):
    try:
        out = subprocess.run(['xattr', '-px', 'com.apple.FinderInfo', path],
                             capture_output=True, text=True, check=True).stdout
        return bytes(int(x, 16) for x in out.split())
    except Exception:
        return b'\0' * 32


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]

    data = open(src, 'rb').read()
    try:
        rsrc = open(src + '/..namedfork/rsrc', 'rb').read()
    except OSError:
        rsrc = b''
    fi = finder_info(src)
    name = os.path.basename(src).encode('mac-roman')[:63]

    h = bytearray(128)
    h[0] = 0
    h[1] = len(name)
    h[2:2 + len(name)] = name
    h[65:69] = fi[0:4] or b'????'          # type
    h[69:73] = fi[4:8] or b'????'          # creator
    h[73] = fi[8] if len(fi) > 8 else 0    # Finder flags, high byte
    h[74] = 0
    struct.pack_into('>I', h, 83, len(data))
    struct.pack_into('>I', h, 87, len(rsrc))
    h[101] = fi[9] if len(fi) > 9 else 0   # Finder flags, low byte
    h[122] = 129                           # written by MacBinary II
    h[123] = 129                           # minimum version to read
    struct.pack_into('>H', h, 124, crc16(bytes(h[0:124])))

    pad = lambda b: b + b'\0' * ((-len(b)) % 128)
    out = bytes(h) + pad(data) + pad(rsrc)
    open(dst, 'wb').write(out)

    print('%s -> %s' % (src, dst))
    print('  name %r  type %r  creator %r' % (name.decode('mac-roman'),
                                              bytes(h[65:69]).decode('mac-roman'),
                                              bytes(h[69:73]).decode('mac-roman')))
    print('  data fork %d, resource fork %d, container %d bytes, CRC 0x%04X'
          % (len(data), len(rsrc), len(out), struct.unpack_from('>H', h, 124)[0]))


if __name__ == '__main__':
    main()
