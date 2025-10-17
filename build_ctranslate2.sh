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
  echo "Cloning ctranslate2 repository (v4.6.0) with submodules..."
  git clone --recurse-submodules --depth 1 --branch v4.6.0 https://github.com/OpenNMT/CTranslate2.git "$CT2_DIR"
else
  echo "ctranslate2 repository already exists."
fi

BUILD_DIR="${CT2_DIR}/build"
echo "Configuring the build using the complete set of flags..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# This cmake command is a direct adaptation of your working PKGBUILD.
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
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

cd ../python

echo "Installing the Python wrapper with build isolation disabled..."
# THE FIX IS HERE: --no-build-isolation tells uv to use the main environment
uv pip install . --no-build-isolation

echo "--- ctranslate2 installation complete! ---"
echo "NOTE: The build was configured for GPU architecture '${CMAKE_CUDA_ARCHITECTURES}'."
echo "If you have a different GPU, please edit this script and run it again."