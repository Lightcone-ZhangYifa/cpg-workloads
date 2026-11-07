#!/usr/bin/env bash
set -euo pipefail
if (( $# != 4 )); then
    echo "usage: build_parsec.sh SOURCE NEW_BUILD_DIR NEW_RUNTIME_DIR CMAKE_EXECUTABLE" >&2
    exit 2
fi
src=$(realpath "$1")
build=$(realpath -m "$2")
runtime=$(realpath -m "$3")
cmake_bin=$(realpath "$4")
if [[ -e "$build" || -e "$runtime" ]]; then
    echo "build and runtime must be fresh paths" >&2
    exit 2
fi
"$cmake_bin" -S "$src" -B "$build" \
    -DCMAKE_INSTALL_PREFIX="$runtime" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
    -DCMAKE_SKIP_INSTALL_RPATH=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_HWLOC=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_PAPI=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_FLEX=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_BISON=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_AYUDAME=ON \
    -DCMAKE_DISABLE_FIND_PACKAGE_LibXml2=ON \
    -DPARSEC_DIST_WITH_MPI=OFF -DPARSEC_GPU_WITH_CUDA=OFF \
    -DPARSEC_GPU_WITH_HIP=OFF -DPARSEC_GPU_WITH_LEVEL_ZERO=OFF \
    -DPARSEC_GPU_WITH_OPENCL=OFF -DPARSEC_PROF_TAU=OFF \
    -DPARSEC_PROF_TRACE=OFF -DPARSEC_PROF_TRACE_NVTX=OFF \
    -DPARSEC_PROF_PINS=OFF \
    -DPARSEC_PROF_GRAPHER=ON -DPARSEC_WANT_HOME_CONFIG_FILES=OFF \
    -DSUPPORT_FORTRAN=OFF -DBUILD_TESTING=ON
"$cmake_bin" --build "$build" --target ex02 ex04 --parallel "${CPG_BUILD_JOBS:-1}"
mkdir -p "$runtime/examples" "$runtime/parsec"
install -m 755 "$build/examples/ex02" "$build/examples/ex04" "$runtime/examples/"
install -m 755 "$build/parsec/libparsec.so.4" "$runtime/parsec/libparsec.so.4"
install -m 644 "$src/LICENSE.txt" "$runtime/LICENSE.txt"
