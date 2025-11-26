#!/bin/bash
set -e # Exit immediately if a command fails.

echo "--- Building and installing ctranslate2 for CUDA ---"

# --- CONFIGURATION ---
# This value is taken directly from your PKGBUILD for the RTX 3060.
# Other developers may need to change this to match their GPU.
# Find architectures here: https://developer.nvidia.com/cuda-gpus
export CMAKE_CUDA_ARCHITECTURES=86
# ---------------------

CT2_DIR="deps/ctranslate2"

# Clone the repository with all its required sub-dependencies
if [ ! -d "$CT2_DIR" ]; then
  echo "Cloning ctranslate2 repository (v4.6.1) with submodules..."
  git clone --recurse-submodules --depth 1 --branch v4.6.1 https://github.com/OpenNMT/CTranslate2.git "$CT2_DIR"
else
  echo "ctranslate2 repository already exists."
fi

BUILD_DIR="${CT2_DIR}/build"

echo "Configuring the build using the complete set of flags..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Define INSTALL_DIR using an absolute path (`pwd`).
INSTALL_DIR="$(pwd)/install"

# Configure the C++ library build
# The key is adding CMAKE_BUILD_WITH_INSTALL_RPATH and CMAKE_INSTALL_RPATH.
# This ensures the compiled libraries know where to look for each other.
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_DIR" \
    -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
    -DCMAKE_INSTALL_RPATH="$INSTALL_DIR/lib" \
    -DOPENMP_RUNTIME=COMP \
    -DWITH_MKL=OFF \
    -DWITH_DNNL=OFF \
    -DWITH_OPENBLAS=ON \
    -DWITH_RUY=ON \
    -DWITH_CUDA=ON \
    -DWITH_CUDNN=ON \
    -DCUDA_DYNAMIC_LOADING=ON \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DENABLE_CPU_DISPATCH=OFF \
    -DBUILD_CLI=OFF \
    -Wno-dev

echo "Compiling ctranslate2 (this will take several minutes)..."
make -j"$(nproc)"

echo "Installing ctranslate2 library locally..."
make install

# Now we move to the python directory
cd ../python

echo "Packaging the Python wrapper into a wheel file..."

# Copy the shared library into the Python package so it's bundled in the wheel
echo "Copying libctranslate2.so into the ctranslate2 package..."
mkdir -p ctranslate2/lib
cp -v "${INSTALL_DIR}"/lib/libctranslate2.so* ctranslate2/lib/

# Patch setup.py to include .so files in package_data for Linux
echo "Patching setup.py to include shared libraries in the wheel..."
# Reset setup.py in case it was patched before
git checkout setup.py 2>/dev/null || true
# Add Linux package_data after line 53 (after the Windows block)
sed -i '53 a\    package_data["ctranslate2"] = ["lib/*.so*"]' setup.py
sed -i '53 a elif sys.platform.startswith("linux"):' setup.py

# Directly tell the compiler and linker where to find things.
export CTRANSLATE2_ROOT="${INSTALL_DIR}"
export LD_LIBRARY_PATH="${INSTALL_DIR}/lib:${LD_LIBRARY_PATH}"

# Set RPATH to $ORIGIN/lib so the extension module finds the library in the same package
# The single quotes are essential to prevent the shell from interpreting $ORIGIN.
export LDFLAGS="-Wl,-rpath,'\$ORIGIN/lib'"

# The build command now runs in an environment where the tools know exactly where to look.
python -m build --wheel --no-isolation --outdir dist .

echo "Verifying shared library is in the wheel..."
unzip -l dist/ctranslate2-*.whl | grep -i "libctranslate2.so" || echo "WARNING: libctranslate2.so not found in wheel!"

# Unset the variable so it doesn't leak into your shell session.
unset LDFLAGS

echo "--- ctranslate2 packaging complete! ---"
echo "A wheel file has been created in: ${CT2_DIR}/python/dist/"
echo "NOTE: The build was configured for GPU architecture '${CMAKE_CUDA_ARCHITECTURES}'."
