"""
Import an MPC project into a fresh Monolith project and bounce its sequences to audio.

    python3 examples/mpc_import/import_and_bounce.py /path/to/MPC2000XL_FOLDER [out_dir]
    python3 examples/mpc_import/import_and_bounce.py /path/to/PROJECT.xpj [out_dir]      (MPC 2.x)

Writes out_dir/project (a normal Monolith project), out_dir/import_report.txt and out_dir/sequences.wav:
every imported sequence played twice, one after another, through the real engine (a listening check).
"""
import os, sys, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import engine as E
import mpc_import as M
import mpc2_import as M2

src = sys.argv[1]
out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "mpc_out")
proj = os.path.join(out, "project")
shutil.rmtree(proj, ignore_errors=True)
e = E.Engine(proj)
is2 = src.lower().endswith(".xpj") or (os.path.isdir(src) and M2.find_project(src)[1] is not None)
rep = M2.import_project(e, src) if is2 else M.import_folder(e, src)
open(os.path.join(out, "import_report.txt"), "w").write(rep.text() + "\n")
print(rep.text())
used = [i for i, sq in enumerate(e.seqs) if any(t.events for t in sq.tracks)]
if used:
    keep_song = e.song
    e.song = [[i, 2] for i in used]
    files = e.track_out(os.path.join(out, "bounce"), tracks=[], song=True, mix=True, tail=1.5)
    shutil.move(files[0], os.path.join(out, "sequences.wav"))
    shutil.rmtree(os.path.join(out, "bounce"), ignore_errors=True)
    e.song = keep_song; e.save_project()
    print("wrote", os.path.join(out, "sequences.wav"))
