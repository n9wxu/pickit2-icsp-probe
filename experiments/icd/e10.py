from icdx import *
import pickle
base = pickle.load(open('cfgspace.pkl', 'rb'))[:0x200]
p = Probe(); t = Gen6(p, vdd_mv=3300, hvp=True); t.device = identify(0x2480); t.enter()
rows = [0x8020, 0x8040, 0x8060, 0x8080, 0x80A0, 0x80C0, 0x80E0, 0x8100, 0x8160, 0x8180]
def row_erase(a):
    t._seek(a); p.queue([OP_G6_CMD, Gen6.ERASE_ROW]); p.delay_ms(6); p.flush()
for r in rows:
    # first and last cell of the row, one bit cleared in each
    t.write_config_space({r: 0x3FFE, r + 31: 0x3FFD})
    got = t.read_words(r, 32)
    took = got[0] == 0x3FFE and got[31] == 0x3FFD
    row_erase(r)
    clean = all(x == 0x3FFF for x in t.read_words(r, 32))
    print('row %04X: write %s, row erase %s' % (r, 'ok' if took else 'FAILED %04X %04X' % (got[0], got[31]), 'ok' if clean else 'FAILED'))
    if not clean: break
w = t.read_words(0x8000, 0x200)
diff = [(0x8000 + i, base[i], w[i]) for i in range(0x200) if w[i] != base[i] and i not in (7, 8)]
print('differences from the original map (ignoring config words):', diff or 'none')
t.exit(); p.close()
