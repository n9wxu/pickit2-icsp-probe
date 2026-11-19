from icdx import *
p = Probe(); t = Gen6(p, vdd_mv=3300, hvp=True); t.device = identify(0x2480); t.enter()
w = t.read_words(0x8000, 0x400)
print('config space 0x8000..0x83FF, cells that are not 3FFF/0000:')
runs = [(0x8000 + i, x) for i, x in enumerate(w) if x not in (0x3FFF, 0x0000)]
print('  ' + ' '.join('%04X:%04X' % r for r in runs[:60]), '... total', len(runs))
print('  zeros:', sum(1 for x in w if x == 0), ' blanks:', sum(1 for x in w if x == 0x3FFF))
# which cells are writable?
t.write_config_space({0x8005: 0x1555, 0x800B: 0x1555, 0x800F: 0x1555})
print('after writing 1555 to 8005, 800B, 800F:', ' '.join('%04X' % x for x in t.read_words(0x8000, 16)))
t.exit(); p.close()
