from icdx import *
import pickle
base = pickle.load(open('cfgspace.pkl', 'rb'))[:0x200]
p = Probe(); t = Gen6(p, vdd_mv=3300, hvp=True); t.device = identify(0x2480); t.enter()
def snapshot(): return t.read_words(0x8000, 0x200)
def factory_ok(w):
    return all(w[i] == base[i] for i in range(0x200) if base[i] != 0x3FFF and i not in (4, 5, 7, 8) and i > 8) 
def probe(addrs, value=0x3FFE):
    t.write_config_space({a: value for a in addrs})
    w1 = snapshot()
    took = [a for a in addrs if w1[a - 0x8000] == value]
    t.bulk_erase()
    w2 = snapshot()
    stuck = [a for a in addrs if w2[a - 0x8000] != 0x3FFF]
    print('cells %s: write took on %d/%d, stuck after erase: %s, factory area intact: %s' % (
        ' '.join('%04X' % a for a in addrs), len(took), len(addrs), [hex(a) for a in stuck] or 'none', factory_ok(w2)))
    return took, stuck
took, stuck = probe([0x8010])
if not stuck:
    took, stuck = probe([0x8020])
if not stuck:
    took, stuck = probe([0x8040, 0x8060, 0x8080, 0x80A0, 0x80C0, 0x80E0, 0x8100])
if not stuck:
    took, stuck = probe([0x8160, 0x8180])
t.exit(); p.close()
