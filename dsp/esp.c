/*
 * esp.c - an emulation of the Ensoniq ES5510 "ESP" effects processor, the chip that runs the ASR-10's effects.
 *
 * Written for Monolith from how the chip is documented to behave (instruction format, three-stage pipeline, 24-bit
 * registers, 48-bit multiply-accumulate, 16-bit delay memory). The behaviour follows the description in MAME's
 * es5510.cpp (BSD-3-Clause, Christian Brunschen), which is the reference for the details below; this is our own code.
 *
 * The chip runs a program of up to 160 48-bit instructions once per audio sample. Each instruction does an ALU
 * operation, a multiply(-accumulate) and a memory cycle at the same time; results land one instruction later, and a
 * memory read arrives two instructions later. Its program and registers are loaded by the host (here: asrfx.py).
 *
 * Build: dsp/build.sh  (cc -O2 -shared -fPIC -o libesp.so esp.c)
 */
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#define F_N   0x80
#define F_C   0x40
#define F_V   0x20
#define F_LT  0x10
#define F_Z   0x08
#define F_NOT 0x04
#define F_MASK (F_N | F_C | F_V | F_LT | F_Z)

enum { SD_REG = 1, SD_DELAY = 2, SD_BOTH = 3 };
enum { CYC_READ = 0, CYC_WRITE = 1, CYC_DUMP = 2 };
enum { ACC_DELAY = 0, ACC_TABLE_A = 1, ACC_TABLE_B = 2, ACC_IO = 3 };

#define DRAM_BITS 20
#define DRAM_SIZE (1 << DRAM_BITS)

/* operand select: alu source, alu destination, mac source, mac destination */
static const uint8_t SEL[16][4] = {
    {1, 1, 1, 1}, {1, 1, 1, 2}, {1, 1, 1, 3}, {1, 1, 2, 1}, {1, 1, 2, 3}, {1, 2, 1, 1}, {1, 2, 2, 1}, {1, 3, 1, 1},
    {1, 3, 2, 1}, {2, 1, 1, 1}, {2, 1, 1, 2}, {2, 1, 1, 3}, {2, 1, 2, 1}, {2, 1, 2, 3}, {2, 3, 1, 1}, {2, 3, 2, 1}};
/* memory control: cycle, access */
static const uint8_t RAMC[8][2] = {{CYC_READ, ACC_DELAY}, {CYC_WRITE, ACC_DELAY}, {CYC_READ, ACC_TABLE_A},
                                   {CYC_WRITE, ACC_TABLE_A}, {CYC_READ, ACC_TABLE_B}, {CYC_DUMP, ACC_DELAY},
                                   {CYC_READ, ACC_IO}, {CYC_WRITE, ACC_IO}};
static const uint8_t NARG[16] = {2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 0};

typedef struct { int cycle, io; uint32_t addr; } ramcyc_t;

typedef struct {
    int32_t gpr[0xc0];
    uint64_t instr[160];
    int16_t ser[8];                       /* index = register - 234: SER0R, SER0L, SER1R, SER1L, SER2R, SER2L, SER3R, SER3L */
    int64_t machl; int mac_overflow;
    int32_t dil;
    int32_t memsiz, memmask, memincrement, memshift, dlength, abase, bbase, dbase, sigreg, mulshift;
    uint8_t ccr, cmr;
    int16_t dol[2]; int dol_count;
    struct { uint8_t a_reg, b_reg, op, src, dst; int32_t a, b; int write, update_ccr; } alu;
    struct { uint8_t c_reg, d_reg, src, dst, acc; int32_t c, d; int write; } mac;
    ramcyc_t ram, ram_p, ram_pp;
    int16_t *dram;
} esp_t;

static inline int32_t sext24(int32_t v) { return (int32_t)((uint32_t)v << 8) >> 8; }
static inline int64_t sext48(int64_t v) { return (int64_t)((uint64_t)v << 16) >> 16; }

static inline uint8_t flag(uint8_t ccr, uint8_t f, int on) { return on ? (ccr | f) : (ccr & ~f); }

static int32_t add24(int32_t a, int32_t b, uint8_t *fl) {
    int32_t as = a & 0x800000, bs = b & 0x800000, r = a + b, rs = r & 0x800000;
    int ov = (as == bs) && (as != rs), neg = rs != 0;
    *fl = flag(*fl, F_C, (r & 0x1000000) != 0);
    *fl = flag(*fl, F_N, neg);
    *fl = flag(*fl, F_Z, (r & 0xffffff) == 0);
    *fl = flag(*fl, F_V, ov);
    *fl = flag(*fl, F_LT, (ov && !neg) || (!ov && neg));
    return r & 0xffffff;
}
static int32_t saturate(int32_t v, uint8_t *fl, int neg) {
    if (*fl & F_V) { *fl = flag(*fl, F_N, neg); *fl &= ~F_Z; return neg ? 0x800000 : 0x7fffff; }
    return v;
}
static inline int32_t negate24(int32_t v) { return ((v ^ 0xffffff) + 1) & 0xffffff; }
static int32_t asl24(int32_t v, int sh, uint8_t *fl) {
    int32_t s = v & 0xffffff;
    int carry = (s >> (24 - sh)) & 1;
    int64_t shifted = (int64_t)sext24(s) << sh;
    int ov = shifted > 0x7fffff || shifted < -0x800000;
    int32_t r = ov ? (shifted < 0 ? 0x800000 : 0x7fffff) : (int32_t)(shifted & 0xffffff);
    *fl = flag(*fl, F_C, carry); *fl = flag(*fl, F_V, ov);
    *fl = flag(*fl, F_N, (r & 0x800000) != 0); *fl = flag(*fl, F_Z, (r & 0xffffff) == 0);
    return r;
}

static int32_t alu_op(int op, int32_t a, int32_t b, uint8_t *fl) {
    int32_t t;
    switch (op) {
    case 0x0: t = add24(a, b, fl); return saturate(t, fl, (a & 0x800000) != 0);
    case 0x1: t = add24(a, negate24(b), fl); return saturate(t, fl, (a & 0x800000) != 0);
    case 0x2: return add24(a, b, fl);
    case 0x3: return add24(a, negate24(b), fl);
    case 0x4: add24(a, negate24(b), fl); return a;
    case 0x5: a &= b; *fl = flag(*fl, F_N, (a & 0x800000) != 0); *fl = flag(*fl, F_Z, a == 0); return a;
    case 0x6: a |= b; *fl = flag(*fl, F_N, (a & 0x800000) != 0); *fl = flag(*fl, F_Z, a == 0); return a;
    case 0x7: a ^= b; *fl = flag(*fl, F_N, (a & 0x800000) != 0); *fl = flag(*fl, F_Z, a == 0); return a;
    case 0x8: { *fl &= ~F_N; int neg = (b & 0x800000) != 0; *fl = flag(*fl, F_C, neg);
                int32_t r = neg ? (0xffffff ^ b) : b; *fl = flag(*fl, F_Z, (r & 0xffffff) == 0); return r; }
    case 0x9: return b;
    case 0xa: return asl24(b, 2, fl);
    case 0xb: return asl24(b, 8, fl);
    case 0xc: *fl &= ~F_N; *fl = flag(*fl, F_C, (b & 0x800000) != 0); return (b << 15) & 0x7fffff;
    case 0xd: return add24(0x7fffff, negate24(b), fl);
    case 0xe: *fl = flag(*fl, F_N, (b & 0x800000) != 0); *fl = flag(*fl, F_C, b & 1); return (b >> 1) | (b & 0x800000);
    default: return 0;
    }
}

static int32_t read_reg(esp_t *e, uint8_t r) {
    if (r < 0xc0) return e->gpr[r];
    switch (r) {
    case 234: case 235: case 236: case 237: case 238: case 239: case 240: case 241: return (int32_t)e->ser[r - 234] << 8;
    case 242: return e->mac_overflow ? (e->machl < 0 ? 0 : 0xffffff) : (int32_t)(e->machl & 0xffffff);
    case 243: return e->mac_overflow ? (e->machl < 0 ? 0x800000 : 0x7fffff) : (int32_t)((e->machl >> 24) & 0xffffff);
    case 244: return e->dil << 8;
    case 245: return e->dlength;
    case 246: return e->abase;
    case 247: return e->bbase;
    case 248: return e->dbase;
    case 249: return e->sigreg;
    case 250: return e->ccr << 16;
    case 251: return e->cmr << 16;
    case 252: return 0xffffff;
    case 253: return 0x800000;
    case 254: return 0x7fffff;
    case 255: return 0;
    default: return 0;
    }
}

static int low_ones(int32_t x) { int n = 0; while (x & 1) { n++; x >>= 1; } return n; }

static void write_reg(esp_t *e, uint8_t r, int32_t v) {
    v &= 0xffffff;
    if (r < 0xc0) { e->gpr[r] = v; return; }
    switch (r) {
    case 234: case 235: case 236: case 237: case 238: case 239: case 240: case 241: e->ser[r - 234] = (int16_t)((v >> 8) & 0xffff); break;
    case 242: e->machl = sext48((e->machl & ((int64_t)0xffffff << 24)) | v); break;
    case 243: e->machl = sext48((e->machl & 0xffffff) | ((int64_t)v << 24)); e->mac_overflow = 0; break;
    case 244: e->memshift = low_ones(v); e->memsiz = 0xffffff >> (24 - e->memshift);
              e->memmask = 0xffffff & ~e->memsiz; e->memincrement = 1 << e->memshift; e->dbase &= e->memmask; break;
    case 245: e->dlength = v; break;
    case 246: e->abase = v; break;
    case 247: e->bbase = v; break;
    case 248: e->dbase = v; break;
    case 249: e->sigreg = v; e->mulshift = (v >> 22) & 1 ? 1 : 2; break;
    case 250: e->ccr = (v >> 16) & F_MASK; break;
    case 251: e->cmr = (v >> 16) & (F_MASK | F_NOT); break;
    default: break;
    }
}

static void to_dol(esp_t *e, int32_t v) {
    int16_t d = (int16_t)(((uint32_t)v >> 8) & 0xffff);
    if (e->dol_count >= 2) { e->dol[0] = e->dol[1]; e->dol[1] = d; }
    else e->dol[e->dol_count++] = d;
}

/* ---------- host interface ---------- */
esp_t *esp_new(void) {
    esp_t *e = calloc(1, sizeof(esp_t));
    e->dram = calloc(DRAM_SIZE, sizeof(int16_t));
    e->memsiz = 0xffffff; e->memmask = 0; e->memincrement = 0x1000000; e->memshift = 24; e->mulshift = 2;
    return e;
}
void esp_free(esp_t *e) { if (e) { free(e->dram); free(e); } }
void esp_reset(esp_t *e) {                       /* clears registers, program, pipeline and delay memory */
    int16_t *d = e->dram;
    memset(e, 0, sizeof(esp_t)); e->dram = d; memset(d, 0, DRAM_SIZE * sizeof(int16_t));
    e->memsiz = 0xffffff; e->memmask = 0; e->memincrement = 0x1000000; e->memshift = 24; e->mulshift = 2;
}
void esp_clear_dram(esp_t *e) { memset(e->dram, 0, DRAM_SIZE * sizeof(int16_t)); }
/* the host writing the delay / table memory (DADR / DOL): one 16-bit word at a word address */
void esp_write_dram(esp_t *e, int addr, int value) { e->dram[addr & (DRAM_SIZE - 1)] = (int16_t)value; }
int esp_read_dram(esp_t *e, int addr) { return e->dram[addr & (DRAM_SIZE - 1)]; }
void esp_set_instr(esp_t *e, int a, uint64_t ins) { if (a >= 0 && a < 160) e->instr[a] = ins & 0xffffffffffffULL; }
uint64_t esp_get_instr(esp_t *e, int a) { return (a >= 0 && a < 160) ? e->instr[a] : 0; }
void esp_write_reg(esp_t *e, int r, int32_t v) { write_reg(e, (uint8_t)r, v); }
int32_t esp_read_reg(esp_t *e, int r) { return read_reg(e, (uint8_t)r) & 0xffffff; }
/* the whole chip state the host can read: registers 0-BF and the 160 instructions */
void esp_snapshot(esp_t *e, int32_t *gpr, uint64_t *instr) {
    for (int r = 0; r < 0xc0; r++) gpr[r] = read_reg(e, (uint8_t)r) & 0xffffff;
    memcpy(instr, e->instr, 160 * sizeof(uint64_t));
}

static uint32_t ram_address(esp_t *e, int access, int32_t off) {
    switch (access) {
    case ACC_DELAY: return (uint32_t)((((e->dbase + off) % (e->dlength + e->memincrement)) & e->memmask) >> e->memshift);
    case ACC_TABLE_A: return (uint32_t)(((e->abase + off) & e->memmask) >> e->memshift);
    case ACC_TABLE_B: return (uint32_t)(((e->bbase + off) & e->memmask) >> e->memshift);
    default: return (uint32_t)(off & 0xfffff0);
    }
}

/* run the program once (one sample): from instruction 0 until the END instruction has started */
static void run_sample(esp_t *e) {
    int pc = 0;
    for (;;) {
        e->ram_pp = e->ram_p; e->ram_p = e->ram;
        uint64_t ins = e->instr[pc];
        if (e->ram_pp.cycle != CYC_WRITE)                                        /* memory read N-2 arrives */
            e->dil = e->ram_pp.io ? 0 : e->dram[e->ram_pp.addr & (DRAM_SIZE - 1)];
        int rc = (ins >> 3) & 7;
        e->ram.cycle = RAMC[rc][0]; e->ram.io = RAMC[rc][1] == ACC_IO;
        e->ram.addr = ram_address(e, RAMC[rc][1], e->gpr[pc]);
        const uint8_t *sel = SEL[(ins >> 8) & 15];
        int skippable = (ins >> 7) & 1, skip = 0;
        if (e->mac.write) {                                                       /* multiplier result N-1 */
            int64_t p = ((int64_t)sext24(e->mac.c) * (int64_t)sext24(e->mac.d)) * (e->mulshift == 1 ? 2 : 4);
            int64_t res = e->mac.acc ? p + e->machl : p;
            e->mac_overflow = res < -((int64_t)1 << 47) || res >= ((int64_t)1 << 47);
            e->machl = res;
            int32_t t = e->mac_overflow ? (res < 0 ? 0x800000 : 0x7fffff) : (int32_t)(((uint64_t)res >> 24) & 0xffffff);
            if (e->mac.dst & SD_REG) write_reg(e, e->mac.c_reg, t);
            if (e->mac.dst & SD_DELAY) to_dol(e, t);
        }
        e->mac.c_reg = (ins >> 32) & 0xff; e->mac.d_reg = (ins >> 40) & 0xff;          /* multiplier N starts */
        e->mac.src = sel[2]; e->mac.dst = sel[3]; e->mac.acc = (ins >> 6) & 1;
        e->mac.c = e->mac.src == SD_REG ? read_reg(e, e->mac.c_reg) : e->dil << 8;
        e->mac.d = read_reg(e, e->mac.d_reg);
        if (e->alu.write) {                                                       /* ALU result N-1 */
            uint8_t fl = e->ccr;
            int32_t r = alu_op(e->alu.op, e->alu.a, e->alu.b, &fl);
            if (e->alu.op != 4) {
                if (e->alu.dst & SD_REG) write_reg(e, e->alu.a_reg, r);
                if (e->alu.dst & SD_DELAY) to_dol(e, r);
            }
            if (e->alu.update_ccr) e->ccr = fl;
        }
        /* the skip test for N sees the flags and the condition mask as ALU N-1 left them: the ROM's programs write
           CMR in the instruction just before a skippable one (MAME tests before that write lands) */
        if (skippable) { skip = (e->ccr & e->cmr & F_MASK) != 0; if (e->cmr & F_NOT) skip = !skip; }
        e->mac.write = !skip;
        e->alu.a_reg = (ins >> 16) & 0xff; e->alu.b_reg = (ins >> 24) & 0xff;      /* ALU N starts */
        e->alu.op = (ins >> 12) & 15; e->alu.src = sel[0]; e->alu.dst = sel[1];
        e->alu.write = !skip || e->alu.op == 4;
        e->alu.update_ccr = !skippable || e->alu.op == 4;
        int end = e->alu.op == 15;
        if (end) {
            e->dbase -= e->memincrement;
            if (e->dbase < 0) e->dbase = e->dlength;
        } else if (NARG[e->alu.op] == 1) {
            e->alu.b = e->alu.src == SD_REG ? read_reg(e, e->alu.b_reg) : e->dil << 8;
        } else {
            e->alu.a = e->alu.src == SD_REG ? read_reg(e, e->alu.a_reg) : e->dil << 8;
            e->alu.b = read_reg(e, e->alu.b_reg);
        }
        if (e->ram_p.cycle != CYC_READ) {                                         /* memory write N-1 */
            if (e->ram_p.cycle == CYC_WRITE && !e->ram_p.io) e->dram[e->ram_p.addr & (DRAM_SIZE - 1)] = e->dol[0];
            e->dol[0] = e->dol[1];
            if (e->dol_count > 0) e->dol_count--;
        }
        if (end || ++pc >= 160) break;
    }
}

/* process n samples. in: n x 8 serial input values (int16, in register order SER0R..SER3L), written only where
   in_mask has the bit (1 << (reg - 234)); out: n x 8 serial values read back after each sample. */
void esp_process(esp_t *e, int n, const int16_t *in, int in_mask, int16_t *out) {
    for (int i = 0; i < n; i++) {
        for (int k = 0; k < 8; k++) if (in_mask & (1 << k)) e->ser[k] = in[i * 8 + k];
        run_sample(e);
        for (int k = 0; k < 8; k++) out[i * 8 + k] = e->ser[k];
    }
}
