"""Compact Z80 disassembler (standard x/y/z/p/q opcode decoding). dis(mem, pc) -> (text, length)"""
R = ["B", "C", "D", "E", "H", "L", "(HL)", "A"]
RP = ["BC", "DE", "HL", "SP"]
RP2 = ["BC", "DE", "HL", "AF"]
CC = ["NZ", "Z", "NC", "C", "PO", "PE", "P", "M"]
ALU = ["ADD A,", "ADC A,", "SUB ", "SBC A,", "AND ", "XOR ", "OR ", "CP "]
ROT = ["RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SRL"]
BLI = {(4, 0): "LDI", (4, 1): "CPI", (4, 2): "INI", (4, 3): "OUTI", (5, 0): "LDD", (5, 1): "CPD", (5, 2): "IND", (5, 3): "OUTD",
       (6, 0): "LDIR", (6, 1): "CPIR", (6, 2): "INIR", (6, 3): "OTIR", (7, 0): "LDDR", (7, 1): "CPDR", (7, 2): "INDR", (7, 3): "OTDR"}


def dis(m, pc):
    b = lambda k: m[(pc + k) & 0xFFFF]
    w = lambda k: b(k) | (b(k + 1) << 8)
    s8 = lambda v: v - 256 if v >= 128 else v
    op = b(0)
    if op in (0xDD, 0xFD):
        ix = "IX" if op == 0xDD else "IY"
        op2 = b(1)
        if op2 == 0xCB:
            d = s8(b(2)); o = b(3); x, y, z = o >> 6, (o >> 3) & 7, o & 7
            ref = f"({ix}{d:+d})"
            t = [f"{ROT[y]} {ref}", f"BIT {y},{ref}", f"RES {y},{ref}", f"SET {y},{ref}"][x]
            return t, 4
        t, n = dis_main(m, pc + 1, ix)
        return t, n + 1
    if op == 0xCB:
        o = b(1); x, y, z = o >> 6, (o >> 3) & 7, o & 7
        return [f"{ROT[y]} {R[z]}", f"BIT {y},{R[z]}", f"RES {y},{R[z]}", f"SET {y},{R[z]}"][x], 2
    if op == 0xED:
        o = b(1); x, y, z = o >> 6, (o >> 3) & 7, o & 7; p, q = y >> 1, y & 1
        if x == 1:
            if z == 0: return (f"IN {R[y]},(C)" if y != 6 else "IN (C)"), 2
            if z == 1: return (f"OUT (C),{R[y]}" if y != 6 else "OUT (C),0"), 2
            if z == 2: return (f"SBC HL,{RP[p]}" if q == 0 else f"ADC HL,{RP[p]}"), 2
            if z == 3: return (f"LD (0x{w(2):04X}),{RP[p]}" if q == 0 else f"LD {RP[p]},(0x{w(2):04X})"), 4
            if z == 4: return "NEG", 2
            if z == 5: return ("RETN" if y != 1 else "RETI"), 2
            if z == 6: return f"IM {[0, 0, 1, 2, 0, 0, 1, 2][y]}", 2
            return ["LD I,A", "LD R,A", "LD A,I", "LD A,R", "RRD", "RLD", "NOP", "NOP"][y], 2
        if x == 2 and (y, z) in BLI: return BLI[(y, z)], 2
        return f"DB 0xED,0x{o:02X}", 2
    return dis_main(m, pc, None)


def dis_main(m, pc, ix):
    b = lambda k: m[(pc + k) & 0xFFFF]
    w = lambda k: b(k) | (b(k + 1) << 8)
    s8 = lambda v: v - 256 if v >= 128 else v
    o = b(0); x, y, z = o >> 6, (o >> 3) & 7, o & 7; p, q = y >> 1, y & 1
    extra = 1 if ix else 0                                   # displacement byte for (IX+d)
    def r(i, off=1):
        if i == 6 and ix: return f"({ix}{s8(b(off)):+d})"
        if ix and i in (4, 5) : return (ix + ("H" if i == 4 else "L"))
        return R[i]
    def rp(i): return ix if (ix and i == 2) else RP[i]
    def rp2(i): return ix if (ix and i == 2) else RP2[i]
    if x == 0:
        if z == 0:
            if y == 0: return "NOP", 1
            if y == 1: return "EX AF,AF'", 1
            if y == 2: return f"DJNZ 0x{(pc + 2 + s8(b(1))) & 0xFFFF:04X}", 2
            if y == 3: return f"JR 0x{(pc + 2 + s8(b(1))) & 0xFFFF:04X}", 2
            return f"JR {CC[y - 4]},0x{(pc + 2 + s8(b(1))) & 0xFFFF:04X}", 2
        if z == 1: return (f"LD {rp(p)},0x{w(1):04X}", 3) if q == 0 else (f"ADD {rp(2)},{rp(p)}", 1)
        if z == 2:
            t = [("LD (BC),A", 1), ("LD A,(BC)", 1), ("LD (DE),A", 1), ("LD A,(DE)", 1),
                 (f"LD (0x{w(1):04X}),{rp(2)}", 3), (f"LD {rp(2)},(0x{w(1):04X})", 3),
                 (f"LD (0x{w(1):04X}),A", 3), (f"LD A,(0x{w(1):04X})", 3)][y]
            return t
        if z == 3: return (f"INC {rp(p)}" if q == 0 else f"DEC {rp(p)}"), 1
        if z == 4: return f"INC {r(y)}", 1 + (extra if y == 6 else 0)
        if z == 5: return f"DEC {r(y)}", 1 + (extra if y == 6 else 0)
        if z == 6:
            if y == 6 and ix: return f"LD {r(6)},0x{b(2):02X}", 3
            return f"LD {r(y)},0x{b(1):02X}", 2
        return ["RLCA", "RRCA", "RLA", "RRA", "DAA", "CPL", "SCF", "CCF"][y], 1
    if x == 1:
        if y == 6 and z == 6: return "HALT", 1
        if ix and (y == 6 or z == 6):                       # (IX+d) with plain H/L
            a = r(y) if y == 6 else R[y]; c = r(z) if z == 6 else R[z]
            return f"LD {a},{c}", 2
        return f"LD {r(y)},{r(z)}", 1 + (extra if (y == 6 or z == 6) else 0)
    if x == 2: return f"{ALU[y]}{r(z)}", 1 + (extra if z == 6 else 0)
    if z == 0: return f"RET {CC[y]}", 1
    if z == 1:
        if q == 0: return f"POP {rp2(p)}", 1
        return ["RET", "EXX", f"JP ({rp(2)})", f"LD SP,{rp(2)}"][p], 1
    if z == 2: return f"JP {CC[y]},0x{w(1):04X}", 3
    if z == 3:
        return [(f"JP 0x{w(1):04X}", 3), ("CB", 1), (f"OUT (0x{b(1):02X}),A", 2), (f"IN A,(0x{b(1):02X})", 2),
                (f"EX (SP),{rp(2)}", 1), ("EX DE,HL", 1), ("DI", 1), ("EI", 1)][y]
    if z == 4: return f"CALL {CC[y]},0x{w(1):04X}", 3
    if z == 5:
        if q == 0: return f"PUSH {rp2(p)}", 1
        return (f"CALL 0x{w(1):04X}", 3) if p == 0 else ("??", 1)
    if z == 6: return f"{ALU[y]}0x{b(1):02X}", 2
    return f"RST 0x{y * 8:02X}", 1


def trace(m, entries, limit=0x10000):
    """recursive-descent: returns {addr: (text, len)} for code reachable from entries"""
    import re
    seen, todo = {}, list(entries)
    while todo:
        pc = todo.pop()
        while pc not in seen and pc < limit:
            t, n = dis(m, pc)
            seen[pc] = (t, n)
            for tgt in re.findall(r"0x([0-9A-F]{4})", t):
                if t.startswith(("JP", "JR", "CALL", "DJNZ")) and "(" not in t: todo.append(int(tgt, 16))
            if t.startswith("RST"): todo.append(int(t.split()[1], 16))
            if t in ("RET", "RETI", "RETN") or t.startswith(("JP 0x", "JR 0x", "JP (")): break
            pc += n
    return seen
