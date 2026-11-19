from icdx import *
p = Probe(); t = Gen6(p, vdd_mv=3300, hvp=True); t.device = identify(0x2480); t.enter()
print('before erase :', ' '.join('%04X' % x for x in t.read_words(0x8000, 16)))
t.bulk_erase()
print('after erase  :', ' '.join('%04X' % x for x in t.read_words(0x8000, 16)))
w = t.read_words(0x8000, 0x400)
print('non-blank cells after erase:', sum(1 for x in w if x != 0x3FFF), ' checksum of 0x8100-0x83FF: %04X' % (sum(w[0x100:]) & 0xFFFF))
t.exit(); p.close()
