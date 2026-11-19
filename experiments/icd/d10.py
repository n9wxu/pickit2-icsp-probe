"""D10: write-test every undocumented data address outside bank 31 in debug
mode (D9 only read them).  A register that reads zero but accepts writes
would show up here."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'host'))
from pk2probe import Probe, OP_ICD_TX, OP_ICD_RX       # noqa: E402
from icd16f1 import Debugger, CMD_READ, CMD_WRITE      # noqa: E402
import d9                                              # noqa: E402

p = Probe()
d = Debugger(p, vdd_mv=3300)
d.load(d9.test_program())
known = d9.documented()
hidden = [a for a in range(0xF80) if a not in known]
print('%d addresses' % len(hidden))
found = []
for i in range(0, len(hidden), 4):
    chunk = hidden[i:i + 4]
    p.flush()
    for a in chunk:                     # write FF, read, write 00, read
        for v in (0xFF, 0x00):
            p.queue([OP_ICD_TX, 50, 4, CMD_WRITE, a & 0xFF, a >> 8, v])
            p.queue([OP_ICD_TX, 50, 3, CMD_READ, a & 0xFF, a >> 8])
            p.queue([OP_ICD_RX, 50, 1], 1)
    r = p.flush()
    for k, a in enumerate(chunk):
        if r[2 * k] or r[2 * k + 1]:
            found.append(a)
            print('   %03X: after FF %02X, after 00 %02X' % (a, r[2 * k], r[2 * k + 1]))
            sys.stdout.flush()
print('writable undocumented addresses outside bank 31: %s' % ([hex(a) for a in found] or 'none'))
print('still halted and responsive: PC=%04X' % d.pc)
p.target_off()
p.close()
