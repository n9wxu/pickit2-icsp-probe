from icdx import *
p = Probe(); t = Gen6(p, vdd_mv=3300, hvp=True); t.device = identify(0x2480); t.enter()
w = t.read_words(0x8000, 0x1000)
t.exit(); p.close()
import pickle; pickle.dump(w, open('cfgspace.pkl', 'wb'))
def kind(x): return '.' if x == 0x3FFF else ('0' if x == 0 else '#')
print('map of 0x8000-0x8FFF, 64 words per row ( . = 3FFF, 0 = 0000, # = other )')
for row in range(0, 0x1000, 64):
    line = ''.join(kind(x) for x in w[row:row+64])
    if row < 0x400 or set(line) != {'.'}: print('%04X %s' % (0x8000 + row, line))
# mirror check
for size in (0x200, 0x400, 0x800):
    print('mirrors every %#x: %s' % (size, w[:size] == w[size:2*size]))
print('non-blank count per 0x200 block:', [sum(1 for x in w[b:b+0x200] if x != 0x3FFF) for b in range(0, 0x1000, 0x200)])
