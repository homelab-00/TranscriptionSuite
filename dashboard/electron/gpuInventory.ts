/**
 * GPU inventory — enumerates the discrete GPUs visible on the host so the
 * dashboard can offer a device picker when more than one card could run the
 * inference server (multi-GPU feature).
 *
 * Three sources, all best-effort (a failure in any of them must never break
 * `checkGpu()`; callers get an empty/partial list instead):
 *   - NVIDIA (all platforms): `nvidia-smi --query-gpu=index,name,memory.total,uuid`
 *     — the only source that yields a stable UUID and a device index. The
 *     index is nvidia-smi/PCI-bus order, which is also the order the NVIDIA
 *     container toolkit uses for `device_ids` and CDI names (`nvidia.com/gpu=N`),
 *     so it can be handed to docker-compose as-is. Note this deliberately is
 *     NOT the CUDA runtime order (CUDA defaults to FASTEST_FIRST) — selection
 *     is persisted by UUID and resolved to an index at server-start time.
 *   - Linux non-NVIDIA (AMD/Intel): /sys/class/drm/renderD* vendor ids, with
 *     an optional `lspci` lookup for the marketing name. These devices carry
 *     no index/UUID — they exist so the UI can (a) tell a mixed
 *     NVIDIA+AMD system apart from an NVIDIA-only one and (b) label the
 *     Vulkan runtime with the actual card name.
 *   - Windows non-NVIDIA: `Get-CimInstance Win32_VideoController` names.
 */

export type GpuVendor = 'nvidia' | 'amd' | 'intel' | 'unknown';

/**
 * Coarse device class. Only 'discrete' devices count as a usable second GPU
 * for runtime gating: integrated GPUs (iGPU on an NVIDIA desktop, Optimus
 * laptops) and virtual display adapters (RDP, Hyper-V, DisplayLink, virtio)
 * must NOT unlock the Vulkan runtimes on NVIDIA hosts, otherwise the
 * "NVIDIA detected" lockout would be defeated on most machines.
 */
export type GpuKind = 'discrete' | 'integrated' | 'virtual' | 'unknown';

export interface GpuDevice {
  vendor: GpuVendor;
  kind: GpuKind;
  /** nvidia-smi index (PCI-bus order). null for devices nvidia-smi cannot see. */
  index: number | null;
  name: string;
  /** Total VRAM in MiB. null when the source does not report memory. */
  memoryMiB: number | null;
  /** Stable NVIDIA UUID ("GPU-..."). null for non-NVIDIA devices. */
  uuid: string | null;
}

/** Subprocess runner signature — matches dockerManager's internal `exec`. */
export type ExecFn = (
  cmd: string,
  args: string[],
  opts?: { timeoutMs?: number },
) => Promise<string>;

/**
 * Parse `nvidia-smi --query-gpu=index,name,memory.total,uuid --format=csv,noheader,nounits`.
 *
 * Example line: `0, NVIDIA GeForce RTX 3090, 24576, GPU-9f6dc1e3-...`
 * The name is the only field that could theoretically contain a comma, so the
 * parser takes index from the front, uuid + memory from the back, and joins
 * whatever remains as the name.
 */
export function parseNvidiaSmiList(csv: string): GpuDevice[] {
  const devices: GpuDevice[] = [];
  for (const rawLine of csv.split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;
    const parts = line.split(',').map((p) => p.trim());
    if (parts.length < 4) continue;
    const index = Number.parseInt(parts[0], 10);
    const uuid = parts[parts.length - 1];
    const memory = Number.parseInt(parts[parts.length - 2], 10);
    const name = parts.slice(1, parts.length - 2).join(', ');
    if (!Number.isInteger(index) || !uuid.startsWith('GPU-') || !name) continue;
    devices.push({
      vendor: 'nvidia',
      kind: 'discrete',
      index,
      name,
      memoryMiB: Number.isFinite(memory) ? memory : null,
      uuid,
    });
  }
  return devices;
}

/** PCI vendor id (contents of the render node sysfs "vendor" file) → vendor. */
export function vendorFromPciId(pciVendorId: string): GpuVendor {
  switch (pciVendorId.trim().toLowerCase()) {
    case '0x10de':
      return 'nvidia';
    case '0x1002':
      return 'amd';
    case '0x8086':
      return 'intel';
    default:
      return 'unknown';
  }
}

/**
 * Extract the device name from a single-line `lspci -s <bus>` output, e.g.
 * `0b:00.0 VGA compatible controller: AMD/ATI Navi 22 [Radeon RX 6700 XT] (rev c1)`.
 * The first ": " separates the class prefix from the name (the ":" inside the
 * bus id has no trailing space, so it does not split).
 */
export function parseLspciName(line: string): string | null {
  const name = line.split(': ').slice(1).join(': ').trim();
  return name || null;
}

const FALLBACK_NAME: Record<GpuVendor, string> = {
  nvidia: 'NVIDIA GPU',
  amd: 'AMD / Radeon GPU',
  intel: 'Intel GPU',
  unknown: 'Unknown GPU',
};

interface DriDeps {
  readdirSync: (dir: string) => string[];
  readFileSync: (file: string) => string;
  realpathSync: (p: string) => string;
  exec?: ExecFn;
}

/**
 * Enumerate Linux DRI render nodes (/sys/class/drm/renderD*) with their PCI
 * vendor. NVIDIA nodes are skipped — nvidia-smi is the authoritative (and
 * richer) source for those; a render node for an NVIDIA card that nvidia-smi
 * cannot see means the proprietary driver is absent, and CUDA is unusable on
 * it anyway. Never throws; returns [] on any error.
 */
export async function listLinuxDriGpus(deps: DriDeps): Promise<GpuDevice[]> {
  let nodes: string[];
  try {
    nodes = deps.readdirSync('/sys/class/drm').filter((n) => /^renderD\d+$/.test(n));
  } catch {
    return [];
  }
  const devices: GpuDevice[] = [];
  for (const node of nodes) {
    try {
      const deviceDir = `/sys/class/drm/${node}/device`;
      const vendor = vendorFromPciId(deps.readFileSync(`${deviceDir}/vendor`));
      if (vendor === 'nvidia') continue;
      // realpath of the device dir ends in the PCI address ("0000:0b:00.0").
      let busId = '';
      try {
        busId = deps.realpathSync(deviceDir).split('/').pop() ?? '';
      } catch {
        // sysfs symlink unreadable — classification degrades to 'unknown'
      }
      // amdgpu exposes dedicated VRAM in bytes; used both for display and to
      // tell a discrete Radeon (large dedicated VRAM) from an APU carve-out.
      let vramBytes: number | null = null;
      try {
        const parsed = Number.parseInt(deps.readFileSync(`${deviceDir}/mem_info_vram_total`), 10);
        vramBytes = Number.isFinite(parsed) && parsed > 0 ? parsed : null;
      } catch {
        // not an amdgpu device or attribute missing
      }
      let name: string | null = null;
      if (deps.exec && busId) {
        try {
          const lspciOut = await deps.exec('lspci', ['-s', busId], { timeoutMs: 5_000 });
          name = parseLspciName(lspciOut.split('\n')[0] ?? '');
        } catch {
          // lspci missing or failed — fall back to the vendor label below
        }
      }
      devices.push({
        vendor,
        kind: classifyLinuxPciGpu(vendor, busId, vramBytes),
        index: null,
        name: name ?? FALLBACK_NAME[vendor],
        memoryMiB: vramBytes !== null ? Math.round(vramBytes / (1024 * 1024)) : null,
        uuid: null,
      });
    } catch {
      // unreadable node — skip it
    }
  }
  return devices;
}

/** Discrete AMD cards worth routing inference to have at least this much dedicated VRAM. */
const DISCRETE_VRAM_THRESHOLD_BYTES = 3 * 1024 * 1024 * 1024;

/**
 * Classify a Linux PCI GPU as integrated vs discrete. Intel iGPUs always live
 * on host bus 00 ("0000:00:02.0") while discrete Arc cards sit behind a PCIe
 * root port on a non-zero bus. AMD APU graphics can appear on a non-zero bus
 * too (internal bridge on Ryzen APUs), so AMD additionally requires a
 * discrete-sized dedicated VRAM pool (amdgpu mem_info_vram_total) — an APU
 * carve-out is far below the threshold. Unknown vendors (virtio-gpu and
 * friends) and unclassifiable devices never count as a usable second GPU.
 */
export function classifyLinuxPciGpu(
  vendor: GpuVendor,
  busId: string,
  vramBytes: number | null,
): GpuKind {
  if (vendor === 'unknown') return 'unknown';
  if (!/^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$/i.test(busId)) return 'unknown';
  if (/^[0-9a-f]{4}:00:/i.test(busId)) return 'integrated';
  if (vendor === 'amd') {
    if (vramBytes === null) return 'unknown';
    return vramBytes >= DISCRETE_VRAM_THRESHOLD_BYTES ? 'discrete' : 'integrated';
  }
  return 'discrete';
}

/**
 * Parse the newline-separated names from
 * `Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name`.
 * Vendor and kind are inferred from the marketing name: Win32_VideoController
 * also lists virtual display adapters (RDP, Hyper-V, DisplayLink, Parsec) and
 * integrated GPUs, which must not read as a usable second card.
 */
export function parseWindowsVideoControllers(output: string): GpuDevice[] {
  const devices: GpuDevice[] = [];
  for (const rawLine of output.split('\n')) {
    const name = rawLine.trim();
    if (!name) continue;
    let vendor: GpuVendor = 'unknown';
    if (/nvidia|geforce|quadro/i.test(name)) vendor = 'nvidia';
    else if (/\bamd\b|radeon|firepro/i.test(name)) vendor = 'amd';
    else if (/intel|\barc\b|iris|\buhd\b/i.test(name)) vendor = 'intel';
    let kind: GpuKind;
    if (
      /microsoft|hyper-v|remote|virtual|displaylink|parsec|spacedesk|vmware|virtualbox|qxl/i.test(
        name,
      )
    ) {
      kind = 'virtual';
    } else if (
      /\biris\b|\buhd\b|\bhd graphics\b|radeon\(tm\)|\bvega \d+\b|\bradeon graphics\b/i.test(name)
    ) {
      kind = 'integrated';
    } else {
      kind = vendor === 'unknown' ? 'unknown' : 'discrete';
    }
    devices.push({ vendor, kind, index: null, name, memoryMiB: null, uuid: null });
  }
  return devices;
}

/**
 * Parse `nvidia-ctk cdi list` output into the suffixes of the registered
 * `nvidia.com/gpu=<suffix>` device names (indices, UUIDs, "all"). Used to
 * validate that a CDI grant for a specific card can actually resolve before
 * handing it to docker compose — the CDI registry is a static file that can
 * lag behind the live nvidia-smi view of the hardware.
 */
export function parseCdiDeviceNames(output: string): string[] {
  const names: string[] = [];
  for (const rawLine of output.split('\n')) {
    const match = rawLine.trim().match(/^nvidia\.com\/gpu=(\S+)$/);
    if (match) names.push(match[1]);
  }
  return names;
}

export interface EnumerateDeps {
  exec: ExecFn;
  platform: NodeJS.Platform;
  dri?: Omit<DriDeps, 'exec'>;
}

/**
 * Run nvidia-smi enumeration. Throws when nvidia-smi is missing/failing.
 * No explicit timeout: the caller default (120s in dockerManager) matches the
 * pre-existing probe budget — cold nvidia-smi on multi-GPU boxes without
 * persistence mode can take tens of seconds, and this gates Start Server.
 */
export async function enumerateNvidiaGpus(exec: ExecFn): Promise<GpuDevice[]> {
  const out = await exec('nvidia-smi', [
    '--query-gpu=index,name,memory.total,uuid',
    '--format=csv,noheader,nounits',
  ]);
  return parseNvidiaSmiList(out);
}

/**
 * Full best-effort host GPU inventory: NVIDIA first (nvidia-smi order), then
 * non-NVIDIA devices. Never throws.
 */
export async function enumerateGpus(deps: EnumerateDeps): Promise<GpuDevice[]> {
  let nvidia: GpuDevice[] = [];
  try {
    nvidia = await enumerateNvidiaGpus(deps.exec);
  } catch {
    // nvidia-smi absent — NVIDIA presence is reported by checkGpu() separately
  }

  let others: GpuDevice[] = [];
  if (deps.platform === 'linux' && deps.dri) {
    others = await listLinuxDriGpus({ ...deps.dri, exec: deps.exec });
  } else if (deps.platform === 'win32') {
    try {
      const out = await deps.exec(
        'powershell.exe',
        [
          '-NoProfile',
          '-Command',
          'Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name',
        ],
        { timeoutMs: 15_000 },
      );
      // nvidia-smi already covers NVIDIA cards with richer data; only keep a
      // CIM NVIDIA row when nvidia-smi itself found nothing (broken driver).
      others = parseWindowsVideoControllers(out).filter(
        (d) => d.vendor !== 'nvidia' || nvidia.length === 0,
      );
    } catch {
      // PowerShell unavailable — leave others empty
    }
  }

  return [...nvidia, ...others];
}

export type GpuSelectionReason = 'auto' | 'resolved' | 'stale-selection';

export interface GpuDeviceResolution {
  /**
   * Value for the GPU_DEVICE compose variable (an nvidia-smi index as a
   * string), or null to leave the variable unset so each compose overlay
   * falls back to its own default (legacy: device 0, CDI/Podman: all).
   */
  composeValue: string | null;
  reason: GpuSelectionReason;
  device?: GpuDevice;
}

/**
 * Resolve the persisted `server.gpuDevice` value (either 'auto' or an NVIDIA
 * GPU UUID) against a fresh inventory. A UUID that no longer matches any
 * present card (card removed, driver down) resolves to the compose defaults
 * instead of failing the server start.
 */
export function resolveGpuDeviceSelection(
  stored: string | undefined | null,
  gpus: GpuDevice[],
): GpuDeviceResolution {
  if (!stored || stored === 'auto') {
    return { composeValue: null, reason: 'auto' };
  }
  const device = gpus.find((g) => g.vendor === 'nvidia' && g.uuid === stored && g.index !== null);
  if (device) {
    return { composeValue: String(device.index), reason: 'resolved', device };
  }
  return { composeValue: null, reason: 'stale-selection' };
}
