from icdx import *
exits = [lambda a: (restore(a), a.ret()),
         lambda a: (restore(a), a.retfie())]
s = Session()
s.load(build(user_counter, exits))
s.start()
time.sleep(0.2)
print('pins after release: %02x  (bit0 DAT, bit2 CLK)' % s.pins(), ' icd_ready', s.p.icd_ready())
print('dump at first entry:')
v = s.dump()
if v:
    print('counter 0x20/21:', s.read(0x20), s.read(0x21))
s.off(); s.p.close()
