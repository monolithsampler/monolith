# SP-1200 (.sp12) import - parked

Status: `sp1200_import.py` reads Rossum SP-1200 (firmware 1.04) project files, but it is **not offered in BROWSE** yet.
On the owner's four projects (COUNTRY, HAERB, MIRAGIO, MOCHECK) the imported sounds were mostly unrecognised, and
MOCHECK played pitched up. So the layout below is only partly right.

## What is believed solid
- File = 0x94E2-byte RAM snapshot + 2^19 12-bit samples (two per three bytes: high, high, low nibbles). Decoding gives
  clean audio (three HAERB sounds were confirmed by ear).
- RAM 0x6EF0-0xFFFF is file 0x0000-0x9110: sequencer. 0x6F00 = end of sequence memory, 0x6F04 = 100 segment pointers,
  segments from 0x7194: header (byte 1 beats/bar, bytes 2-3 length in ticks), then control bytes (bit 0 end, bit 1
  events follow, bits 2-7 a 64-tick wrapping clock) and events (bit 7 last, bit 6 one extra byte, low 5 bits pad;
  extra byte high nibble = level). From firmware routines 0x0A59, 0x1AC1, 0x253C.
- RAM 0x6B2C-0x6EFE is file 0x9110-0x94E2: names at 0x6B30, 32 x 4-byte records at 0x6BF0, 32 x 10-byte at 0x6C7E.

## What is probably wrong (from listening)
- Which slot / region a pad plays (assumed: 10-byte record byte 1 low 3 bits = 2.5 s slot; 4-byte record = start/end
  inside it). Sounds were unrecognised, so this mapping, the slot size, or the sample memory order is off.
- Playback rate: MOCHECK too high. The sample rate may differ per sound, or tune is stored and not applied.
- Pad numbering vs bank labels (file order D1..A8 vs the firmware writing A1 first at 0x6B30).

## What will settle it
Test saves made on the SP, one change each: one sound on A1 only; same with A1 tuned; with A1 decay changed; with the
tempo at 100; the same sound moved to B1. Diffing them pins down pad -> sound, tune, decay and tempo.
Firmware disassembly tools: `tools/z80dis.py` (a small x/y/z/p/q decoder) traced from the vectors at 0x004D.
