import sys, time
sys.path.insert(0, sys.path[0] + "/../../host")
from pk2probe import *
p = Probe()
print('VDD/VPP now', p.voltages())
t = Gen6(p, vdd_mv=3300, hvp=False); t.device = identify(0x2480)
t.enter()
print('0x8000..0x800F:', ' '.join('%04X' % w for w in t.read_words(0x8000, 16)))
p.flush()
print('VDD during session %.2f V' % p.voltages()[0])
# try to write the debug vector
t.write_config_space({0x8004: 0x2ABC})
print('after writing 2ABC to 0x8004:', ' '.join('%04X' % w for w in t.read_words(0x8000, 16)))
t.exit()
p.close()
