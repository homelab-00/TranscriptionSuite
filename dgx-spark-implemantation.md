# DGX Spark Implementation Plan (Linux ARM64 + NVIDIA Blackwell GB10)

## Goal
Integrate DGX Spark as an additive platform in the existing multi-platform TranscriptionSuite setup without breaking:
- Windows CPU/CUDA Docker workflows
- macOS Apple Silicon Metal bare-metal workflow
- Linux x86_64 CUDA Docker workflow
- Existing Vulkan sidecar workflows

## Constraints
- Keep current defaults unchanged for non-DGX platforms.
- Avoid introducing a new runtime profile (high blast radius in UI/state/test matrix).
- Reuse existing GPU runtime profile and compose layering model.
- Preserve durability and startup invariants.

## Design Summary
1. Keep runtime profile model unchanged (`gpu`, `cpu`, `vulkan`, `vulkan-wsl2`, `metal`).
2. Add a DGX-specific compose overlay: `server/docker/docker-compose.dgx-spark.yml`.
3. Parameterize server Docker build with:
   - `BASE_IMAGE` (default `ubuntu:24.04`)
   - `UV_PYTHON_BIN` (default `/usr/bin/python3.13`)
4. Add a DGX bootstrap mode (`BOOTSTRAP_USE_SYSTEM_TORCH=true`) to reuse NGC-provided torch/torchaudio from base image and skip reinstall into runtime venv.
5. Route Linux ARM64 + GPU image pulls to a dedicated repo:
   - `ghcr.io/homelab-00/transcriptionsuite-server-dgx-spark`
6. Keep all existing behavior byte-compatible when DGX mode is not enabled.

## Step-by-Step Tasks

### Phase 1: Docker Build/Compose Plumbing
1. Update `server/docker/Dockerfile`:
   - Add `ARG BASE_IMAGE=ubuntu:24.04` and use `FROM ${BASE_IMAGE}`.
   - Add `ARG UV_PYTHON_BIN=/usr/bin/python3.13` and export as env.
2. Update `server/docker/docker-compose.yml`:
   - Pass through new build args (`BASE_IMAGE`, `UV_PYTHON_BIN`).
   - Pass through env vars (`UV_PYTHON_BIN`, `BOOTSTRAP_USE_SYSTEM_TORCH`).
   - Document DGX compose overlay usage.
3. Create `server/docker/docker-compose.dgx-spark.yml`:
   - Set `BASE_IMAGE=nvcr.io/nvidia/pytorch:25.09-py3`.
   - Set `UV_PYTHON_BIN=/opt/conda/bin/python`.
   - Default `BOOTSTRAP_USE_SYSTEM_TORCH=true`.

### Phase 2: Bootstrap Compatibility Mode
1. Update `server/docker/bootstrap_runtime.py`:
   - Read bootstrap interpreter from `UV_PYTHON_BIN`.
   - In DGX mode, run `uv sync` with:
     - `--no-install-package torch`
     - `--no-install-package torchaudio`
   - In DGX mode, pre-create runtime venv with `--system-site-packages`.
   - Include DGX mode flag in fingerprinting input to avoid marker mismatches.
2. Update `server/docker/docker-entrypoint.sh`:
   - Use `UV_PYTHON_BIN` for pre-bootstrap Python scripts.

### Phase 3: Dashboard/Electron Integration
1. Update `dashboard/electron/dockerManager.ts`:
   - Add DGX image repo constant.
   - Add Linux ARM64 host detection helper.
   - Resolve repo to DGX repo for `runtimeProfile === 'gpu'` on Linux ARM64.
   - Add DGX compose overlay in `composeFileArgs()` for Linux ARM64 GPU.
   - Map GHCR token 401 to `not-published` for DGX repo as first-push private-package case.

### Phase 4: Build/Release Tooling
1. Update `build/docker-build-push.sh`:
   - Add `--variant dgx-spark`.
   - Default DGX Spark mode to local-only (no push) due very large base image.
   - Add explicit push opt-in (`--push`) and local-only override (`--local-only`).
   - Push to DGX repo.
   - Pass `BASE_IMAGE` and `UV_PYTHON_BIN` build args.

### Phase 5: Tests and Validation
1. Update/extend unit tests:
   - `dashboard/electron/__tests__/composeFileArgs.test.ts`
   - `dashboard/electron/__tests__/dockerManagerLegacyGpu.test.ts`
2. Run targeted tests:
   - Dashboard electron unit tests for compose/repo logic.
3. Run full relevant suite for regression confidence:
   - Dashboard test/typecheck as available.
4. Optional platform smoke checks:
   - Linux x86_64 GPU stack unchanged.
   - Linux ARM64 GPU stack includes DGX overlay and repo resolution.

## Risk Register
- Python ABI mismatch between NGC base and project constraints.
- Base-image torch compatibility with project dependencies at runtime.
- GHCR package visibility defaults (`Private`) causing false-negative tag listing.

## Rollback Plan
- Remove DGX overlay from compose command to revert to default Linux GPU path.
- Unset `BOOTSTRAP_USE_SYSTEM_TORCH` to return to default uv torch install behavior.
- Revert image repo routing to default repo if DGX repo is not available.

---

# Full-Featured Delegation Prompt (for another coding agent/repository)

Use this prompt verbatim:

```text
Task: Add DGX Spark platform support (Linux ARM64 + NVIDIA Blackwell GB10 sm_121) to an existing multi-platform transcription/diarization project without breaking existing platforms.

Context:
- Existing platforms:
  - Windows CPU/CUDA via Docker
  - macOS Apple Silicon via bare-metal MLX
  - Linux x86_64 CUDA via Docker
- Existing container stack uses layered compose overlays and a unified server Dockerfile.
- Current base image is ubuntu:24.04 and runtime dependencies are bootstrapped at container start into a venv.

Primary objective:
Introduce DGX Spark support as an additive path that reuses existing GPU runtime profile semantics, while adding architecture-aware Docker/build/runtime behavior.

Hard requirements:
1) Keep defaults unchanged for all non-DGX users.
2) Do NOT add a new runtime profile unless absolutely required.
3) Add a DGX-specific compose overlay file that can be explicitly composed.
4) Parameterize Dockerfile base image and bootstrap interpreter path.
5) Support using NVIDIA NGC PyTorch base image on DGX Spark.
6) Add bootstrap mode to reuse system torch/torchaudio from base image and skip reinstall in app venv.
7) Add Linux ARM64 + GPU image-repo routing to a dedicated DGX image repo.
8) Update build/push script with a DGX variant.
9) DGX variant must default to local-only builds, with GHCR push as explicit opt-in.
9) Add/adjust tests for compose selection and repo resolution.
10) Update deployment docs with DGX run instructions.

Implementation details to include:
- Dockerfile args:
  - BASE_IMAGE (default ubuntu:24.04)
  - UV_PYTHON_BIN (default /usr/bin/python3.13)
- Compose overlay example:
  - docker-compose.dgx-spark.yml
  - BASE_IMAGE=nvcr.io/nvidia/pytorch:25.09-py3
  - UV_PYTHON_BIN=/opt/conda/bin/python
  - BOOTSTRAP_USE_SYSTEM_TORCH=true
- Bootstrap behavior:
  - uv sync uses UV_PYTHON_BIN
  - if BOOTSTRAP_USE_SYSTEM_TORCH=true:
    - create venv with --system-site-packages
    - add --no-install-package torch --no-install-package torchaudio
    - include mode flag in bootstrap fingerprinting
- Dashboard/backend runtime resolver behavior:
  - If runtimeProfile == 'gpu' and host is Linux ARM64, use DGX repo
- GHCR tag-list behavior:
  - token 401 for DGX repo should map to not-published state (first push private)

Validation checklist:
- Unit tests for compose args pass.
- Unit tests for repo resolution pass.
- Existing non-DGX tests continue to pass.
- Compose stack for Linux x86_64 unchanged.
- DGX stack includes DGX overlay only when Linux ARM64 + GPU profile.

Deliverables:
1) Code changes.
2) Test results with command outputs summarized.
3) Risk notes (any unresolved ABI/runtime assumptions).
4) Rollback instructions.
```
