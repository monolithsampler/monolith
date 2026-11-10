#!/bin/sh
# Builds vst3host.so (used by fx.py when the pedalboard package is not installed).
# Works on the Pi 5 (aarch64) and on x86_64 Linux.  Needs g++, git and libx11-dev (sudo apt install g++ git libx11-dev).
#   cd vst3host && ./build.sh
set -e
cd "$(dirname "$0")"
SDK=${SDK:-sdk}
if [ ! -d "$SDK/public.sdk" ]; then
  mkdir -p "$SDK"
  git clone --depth 1 https://github.com/steinbergmedia/vst3_base.git "$SDK/base"
  git clone --depth 1 https://github.com/steinbergmedia/vst3_pluginterfaces.git "$SDK/pluginterfaces"
  git clone --depth 1 https://github.com/steinbergmedia/vst3_public_sdk.git "$SDK/public.sdk"
fi
H=$SDK/public.sdk/source/vst/hosting
SRC="vst3host.cpp
 $H/module.cpp $H/module_linux.cpp $H/hostclasses.cpp $H/pluginterfacesupport.cpp $H/plugprovider.cpp
 $H/parameterchanges.cpp $H/processdata.cpp $H/eventlist.cpp $H/connectionproxy.cpp
 $SDK/public.sdk/source/vst/utility/stringconvert.cpp $SDK/public.sdk/source/vst/vstinitiids.cpp
 $SDK/public.sdk/source/common/memorystream.cpp $SDK/public.sdk/source/common/commonstringconvert.cpp $SDK/public.sdk/source/common/commoniids.cpp $SDK/public.sdk/source/common/threadchecker_linux.cpp
 $SDK/pluginterfaces/base/funknown.cpp $SDK/pluginterfaces/base/coreiids.cpp $SDK/pluginterfaces/base/ustring.cpp
 $SDK/pluginterfaces/base/conststringtable.cpp
 $SDK/base/source/fobject.cpp $SDK/base/source/fstring.cpp $SDK/base/source/updatehandler.cpp $SDK/base/source/fdebug.cpp
 $SDK/base/source/baseiids.cpp $SDK/base/source/fbuffer.cpp $SDK/base/thread/source/flock.cpp"
g++ -std=c++17 -O2 -fPIC -shared -DRELEASE=1 -I"$SDK" -o vst3host.so $SRC -lX11 -ldl -lpthread -lstdc++fs
echo "built $(pwd)/vst3host.so"
