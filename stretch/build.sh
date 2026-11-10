#!/bin/sh
# Builds libstretch.so (WARP: time-stretch / pitch-shift for pads). Works on the Pi 5 (aarch64) and x86_64 Linux.
# Needs g++ and git (sudo apt install g++ git).   cd stretch && ./build.sh
set -e
cd "$(dirname "$0")"
EXT=${EXT:-ext}
get() {   # repo, folder, pinned commit
  if [ ! -d "$EXT/$2" ]; then
    mkdir -p "$EXT/$2" && cd "$EXT/$2" && git init -q && git remote add origin "$1" \
      && git fetch -q --depth 1 origin "$3" && git checkout -q FETCH_HEAD && cd - >/dev/null
  fi
}
get https://github.com/Signalsmith-Audio/signalsmith-stretch.git signalsmith-stretch a670068d9aeb64913331d5cc29337b19a457a7df
get https://github.com/Signalsmith-Audio/linear.git signalsmith-linear 146b26f91b48835d665fa0498d64d9617818d27a
g++ -std=c++17 -O3 -fPIC -shared -I"$EXT/signalsmith-stretch/include" -I"$EXT" -I"$EXT/signalsmith-stretch" -o libstretch.so stretch.cpp
echo "built $(pwd)/libstretch.so"
