/*
 * asr68k.c - runs the ASR-10 ROM's own effect-parameter routines (68000 code) on the Musashi 68000 core (MIT, in
 * dsp/m68k/), so a parameter value turns into effects-chip registers exactly as on the machine.
 *
 * Memory: the user's ROM image at F80000-FBFFFF; RAM below 0x20000 (work area, the effect's data copy); high RAM at
 * FF8000-FFFFFF (the OS's variables, its entry points and the stack). The routines call the OS with "jsr $8030.w",
 * which addresses FF8030; those entry points are answered here: FF8030 writes an effects-chip register (D1 = register,
 * D2 = value), FF802A reads an instruction into FF8018, FF8036 writes it back.
 * Every other entry point just returns and is counted, so unknown calls show up instead of crashing.
 *
 * Build: dsp/build.sh
 */
#include <stdint.h>
#include <string.h>
#include "m68k/m68k.h"

#define ROM_BASE 0xF80000
#define ROM_SIZE 0x40000
#define RAM_SIZE 0x20000
#define HIRAM_BASE 0xFF8000
#define VEC 0xFF8000                     /* the OS entry points ("jsr $8030.w" sign-extends to FF8030) */
#define STOP1 0xFF8200
#define STOP2 0xFF8202
#define RTE_AT 0xFF8204
#define MAXW 512

static uint8_t rom[ROM_SIZE];
static uint8_t ram[RAM_SIZE];
static uint8_t hiram[0x8000];
static int stopped;
/* what the routines did: kind 1 = GPR write (reg, value), 2 = instruction write (addr, 48-bit), 3 = unknown call (pc) */
static int n_out;
static int out_kind[MAXW], out_reg[MAXW];
static int64_t out_val[MAXW];
static int32_t *gpr_mirror;            /* the chip's registers as the routines see them (for 0x802A reads) */
static uint64_t instr_mirror[160];

static uint8_t *ptr(unsigned a, int write) {
    a &= 0xffffff;
    if (a >= ROM_BASE && a < ROM_BASE + ROM_SIZE) return write ? NULL : &rom[a - ROM_BASE];
    if (a < RAM_SIZE) return &ram[a];
    if (a >= HIRAM_BASE) return &hiram[a - HIRAM_BASE];
    return NULL;
}
unsigned int m68k_read_memory_8(unsigned int a) { uint8_t *p = ptr(a, 0); return p ? *p : 0; }
unsigned int m68k_read_memory_16(unsigned int a) { return (m68k_read_memory_8(a) << 8) | m68k_read_memory_8(a + 1); }
unsigned int m68k_read_memory_32(unsigned int a) { return (m68k_read_memory_16(a) << 16) | m68k_read_memory_16(a + 2); }
void m68k_write_memory_8(unsigned int a, unsigned int v) { uint8_t *p = ptr(a, 1); if (p) *p = v; }
void m68k_write_memory_16(unsigned int a, unsigned int v) { m68k_write_memory_8(a, v >> 8); m68k_write_memory_8(a + 1, v); }
void m68k_write_memory_32(unsigned int a, unsigned int v) { m68k_write_memory_16(a, v >> 16); m68k_write_memory_16(a + 2, v); }
unsigned int m68k_read_disassembler_8(unsigned int a) { return m68k_read_memory_8(a); }
unsigned int m68k_read_disassembler_16(unsigned int a) { return m68k_read_memory_16(a); }
unsigned int m68k_read_disassembler_32(unsigned int a) { return m68k_read_memory_32(a); }

static void emit(int kind, int reg, int64_t v) {
    if (n_out < MAXW) { out_kind[n_out] = kind; out_reg[n_out] = reg; out_val[n_out] = v; n_out++; }
}

int asr68k_hooks;
#define RTS_STUB 0xFF8400
#define LOOP_AT 0xFF8300
static int32_t gpr_local[0xc0];

void asr68k_hook(unsigned int pc) {
    asr68k_hooks++;
    pc &= 0xffffff;
    if (pc == STOP1 || pc == STOP2) { stopped = 1; m68k_end_timeslice(); return; }
    if (pc < VEC || pc >= VEC + 0x48) return;
    if (pc == VEC + 0x1e || pc == VEC + 0x42) return;      /* real code (jmp) installed there */
    unsigned d1 = m68k_get_reg(NULL, M68K_REG_D1), d2 = m68k_get_reg(NULL, M68K_REG_D2);
    int32_t *g = gpr_mirror ? gpr_mirror : gpr_local;
    switch (pc - VEC) {
    case 0x24: {                                         /* read a chip register: D2 = its value */
        int r = d1 & 0xff; m68k_set_reg(M68K_REG_D2, r < 0xc0 ? (unsigned)g[r] : 0); break; }
    case 0x2a: {                                         /* read instruction D1 into FF8018 (6 bytes) */
        int a = d1 & 0xff; uint64_t ins = a < 160 ? instr_mirror[a] : 0;
        for (int k = 0; k < 6; k++) m68k_write_memory_8(0xFF8018 + k, (ins >> (40 - 8 * k)) & 0xff);
        break; }
    case 0x30: {                                         /* write a chip register: D1 = register, D2 = value */
        int r = d1 & 0xff; int32_t v = d2 & 0xffffff;
        if (r < 0xc0) g[r] = v;
        emit(1, r, v); break; }
    case 0x36: {                                         /* write instruction D1 from FF8018 */
        int a = d1 & 0xff; uint64_t ins = 0;
        for (int k = 0; k < 6; k++) ins = (ins << 8) | m68k_read_memory_8(0xFF8018 + k);
        if (a < 160) instr_mirror[a] = ins;
        emit(2, a, (int64_t)ins); break; }
    case 0x3c: emit(4, d1 & 0xffff, m68k_get_reg(NULL, M68K_REG_A1)); break;   /* table upload (logged) */
    default: emit(3, pc, d1); break;                     /* anything else: logged, returns */
    }
    m68k_set_reg(M68K_REG_PC, RTS_STUB);                 /* return to the caller */
}

/* ---------- host interface ---------- */
int asr68k_init(const uint8_t *image, int len, const unsigned *handlers, int n_handlers) {
    if (len != ROM_SIZE) return -1;
    memcpy(rom, image, ROM_SIZE);
    memset(ram, 0, sizeof ram); memset(hiram, 0, sizeof hiram);
    /* the OS entry points the parameter routines use (as the OS installs them at FF8000): */
    for (int a = VEC; a < VEC + 0x48; a += 2) m68k_write_memory_16(a, 0x4e75);       /* answered by asr68k_hook */
    m68k_write_memory_16(VEC + 0x1e, 0x4ef9); m68k_write_memory_32(VEC + 0x20, LOOP_AT);   /* 801E: run an action list */
    m68k_write_memory_16(VEC + 0x42, 0x4ef9); m68k_write_memory_32(VEC + 0x44, 0xFFFB7788); /* 8042: ROM modulation engine */
    for (int k = 0; k < 30; k++)                                                        /* 8048: the action routines */
        m68k_write_memory_32(VEC + 0x48 + 4 * k, k < n_handlers && handlers[k] ? handlers[k] : RTS_STUB);
    /* the action-list loop (what 801E runs): D0 = kind from (A2)+; 0 or >= 1E ends; else jsr table[kind] */
    static const uint16_t loop[] = {0x7000, 0x101a, 0x6714, 0xb07c, 0x001e, 0x6c0e, 0xe540, 0x307c, 0x8048,
                                    0x2070, 0x0000, 0x4e90, 0x60e6, 0x4e75};
    for (unsigned i = 0; i < sizeof loop / 2; i++) m68k_write_memory_16(LOOP_AT + 2 * i, loop[i]);
    m68k_write_memory_16(RTS_STUB, 0x4e75);
    m68k_write_memory_16(STOP1, 0x4e75); m68k_write_memory_16(STOP2, 0x4e75);
    for (int v = 0; v < 64; v++) m68k_write_memory_32(v * 4, RTE_AT);                 /* exceptions: to an RTE */
    m68k_write_memory_16(RTE_AT, 0x4e73);
    m68k_init();
    m68k_set_cpu_type(M68K_CPU_TYPE_68000);
    return 0;
}
void asr68k_poke(int a, const uint8_t *data, int n) { for (int i = 0; i < n; i++) m68k_write_memory_8(a + i, data[i]); }
void asr68k_peek(int a, uint8_t *data, int n) { for (int i = 0; i < n; i++) data[i] = m68k_read_memory_8(a + i); }
void asr68k_set_mirror(int32_t *gpr, const uint64_t *instr) {
    gpr_mirror = gpr;
    if (instr) memcpy(instr_mirror, instr, sizeof instr_mirror);
}

/* call a routine: regs = D0-D7, A0-A6 (15 values). Two return addresses are stacked (a routine may drop one and
   continue in inline code). Returns the number of things it did (read them with asr68k_result); the registers after the
   call are written back to regs. */
int asr68k_call(unsigned pc, unsigned *regs, int max_cycles) {
    n_out = 0; stopped = 0;
    for (int i = 0; i < 8; i++) m68k_set_reg(M68K_REG_D0 + i, regs[i]);
    for (int i = 0; i < 7; i++) m68k_set_reg(M68K_REG_A0 + i, regs[8 + i]);
    unsigned sp = 0xFFFF00;
    sp -= 4; m68k_write_memory_32(sp, STOP2);
    sp -= 4; m68k_write_memory_32(sp, STOP1);
    m68k_set_reg(M68K_REG_SR, 0x2700);
    m68k_set_reg(M68K_REG_A7, sp);
    m68k_set_reg(M68K_REG_SP, sp);
    m68k_set_reg(M68K_REG_PC, pc);
    int left = max_cycles;
    while (!stopped && left > 0) left -= m68k_execute(1000);
    for (int i = 0; i < 8; i++) regs[i] = m68k_get_reg(NULL, M68K_REG_D0 + i);
    for (int i = 0; i < 7; i++) regs[8 + i] = m68k_get_reg(NULL, M68K_REG_A0 + i);
    return stopped ? n_out : -1 - n_out;
}
void asr68k_result(int i, int *kind, int *reg, int64_t *val) { *kind = out_kind[i]; *reg = out_reg[i]; *val = out_val[i]; }
unsigned asr68k_stop_pc(void) { return m68k_get_reg(NULL, M68K_REG_PC) & 0xffffff; }
