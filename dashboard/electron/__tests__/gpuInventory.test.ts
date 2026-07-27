// @vitest-environment node

/**
 * gpuInventory — host GPU enumeration and device-selection resolution
 * (multi-GPU support: pick which card runs the inference server).
 *
 * Pure-parser and resolver tests; the enumerate* orchestration is covered via
 * injected exec/fs fakes.
 */

import { describe, it, expect } from 'vitest';

import {
  parseNvidiaSmiList,
  parseLspciName,
  parseWindowsVideoControllers,
  parseCdiDeviceNames,
  vendorFromPciId,
  classifyLinuxPciGpu,
  listLinuxDriGpus,
  enumerateGpus,
  resolveGpuDeviceSelection,
  type GpuDevice,
} from '../gpuInventory.js';

// ─── parseNvidiaSmiList ─────────────────────────────────────────────────────

describe('parseNvidiaSmiList', () => {
  it('parses a two-GPU csv,noheader,nounits listing', () => {
    const csv = [
      '0, NVIDIA GeForce RTX 3060, 12288, GPU-1c8c5f42-aaaa-bbbb-cccc-111111111111',
      '1, NVIDIA GeForce RTX 3090, 24576, GPU-9f6dc1e3-dddd-eeee-ffff-222222222222',
    ].join('\n');
    const gpus = parseNvidiaSmiList(csv);
    expect(gpus).toHaveLength(2);
    expect(gpus[0]).toEqual({
      vendor: 'nvidia',
      kind: 'discrete',
      index: 0,
      name: 'NVIDIA GeForce RTX 3060',
      memoryMiB: 12288,
      uuid: 'GPU-1c8c5f42-aaaa-bbbb-cccc-111111111111',
    });
    expect(gpus[1].index).toBe(1);
    expect(gpus[1].name).toBe('NVIDIA GeForce RTX 3090');
  });

  it('keeps a comma inside the GPU name intact', () => {
    const csv = '0, NVIDIA Weird, Name GPU, 8192, GPU-1234';
    const gpus = parseNvidiaSmiList(csv);
    expect(gpus).toHaveLength(1);
    expect(gpus[0].name).toBe('NVIDIA Weird, Name GPU');
  });

  it('ignores blank lines and malformed rows', () => {
    const csv = '\n\nnot-a-gpu-row\n0, RTX 3090, 24576, GPU-abc\n';
    expect(parseNvidiaSmiList(csv)).toHaveLength(1);
  });

  it('returns [] for empty output', () => {
    expect(parseNvidiaSmiList('')).toEqual([]);
  });
});

// ─── vendor / lspci / windows parsers ───────────────────────────────────────

describe('vendorFromPciId', () => {
  it.each([
    ['0x10de', 'nvidia'],
    ['0x1002', 'amd'],
    ['0x8086', 'intel'],
    ['0x1af4', 'unknown'],
  ])('%s → %s', (id, vendor) => {
    expect(vendorFromPciId(id)).toBe(vendor);
  });

  it('tolerates trailing newline from sysfs', () => {
    expect(vendorFromPciId('0x1002\n')).toBe('amd');
  });
});

describe('parseLspciName', () => {
  it('extracts the device name after the class prefix', () => {
    const line =
      '0b:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 22 [Radeon RX 6700 XT] (rev c1)';
    expect(parseLspciName(line)).toBe(
      'Advanced Micro Devices, Inc. [AMD/ATI] Navi 22 [Radeon RX 6700 XT] (rev c1)',
    );
  });

  it('returns null for empty input', () => {
    expect(parseLspciName('')).toBeNull();
  });
});

describe('parseWindowsVideoControllers', () => {
  it('infers vendors from marketing names', () => {
    const out = 'NVIDIA GeForce RTX 3090\nAMD Radeon RX 6700 XT\nIntel(R) UHD Graphics 770\n';
    const gpus = parseWindowsVideoControllers(out);
    expect(gpus.map((g) => g.vendor)).toEqual(['nvidia', 'amd', 'intel']);
    expect(gpus.map((g) => g.kind)).toEqual(['discrete', 'discrete', 'integrated']);
    expect(gpus.every((g) => g.index === null && g.uuid === null)).toBe(true);
  });

  it('classifies virtual display adapters and APU graphics as non-discrete', () => {
    const out = [
      'Microsoft Remote Display Adapter',
      'Microsoft Basic Display Adapter',
      'Microsoft Hyper-V Video',
      'AMD Radeon(TM) Graphics',
      'Intel(R) Iris(R) Xe Graphics',
      'Intel(R) Arc(TM) A770 Graphics',
    ].join('\r\n');
    const gpus = parseWindowsVideoControllers(out);
    expect(gpus.map((g) => g.kind)).toEqual([
      'virtual',
      'virtual',
      'virtual',
      'integrated',
      'integrated',
      'discrete',
    ]);
  });

  it('handles CRLF line endings', () => {
    const gpus = parseWindowsVideoControllers('NVIDIA GeForce RTX 3090\r\n');
    expect(gpus).toHaveLength(1);
    expect(gpus[0].name).toBe('NVIDIA GeForce RTX 3090');
  });
});

describe('parseCdiDeviceNames', () => {
  it('extracts the gpu device suffixes from nvidia-ctk cdi list output', () => {
    const out = [
      'INFO[0000] Found 5 CDI devices',
      'nvidia.com/gpu=0',
      'nvidia.com/gpu=1',
      'nvidia.com/gpu=GPU-fae88089-bcfc-f963-7283-fc83dfaadb17',
      'nvidia.com/gpu=GPU-91fc582e-7d25-f03a-ddda-5cfb6579e4ed',
      'nvidia.com/gpu=all',
    ].join('\n');
    expect(parseCdiDeviceNames(out)).toEqual([
      '0',
      '1',
      'GPU-fae88089-bcfc-f963-7283-fc83dfaadb17',
      'GPU-91fc582e-7d25-f03a-ddda-5cfb6579e4ed',
      'all',
    ]);
  });

  it('returns [] when no gpu devices are listed', () => {
    expect(parseCdiDeviceNames('INFO[0000] Found 0 CDI devices\n')).toEqual([]);
  });
});

describe('classifyLinuxPciGpu', () => {
  const GIB = 1024 * 1024 * 1024;

  it.each([
    // Intel iGPU on host bus 00
    ['intel', '0000:00:02.0', null, 'integrated'],
    // discrete Arc behind a root port
    ['intel', '0000:03:00.0', null, 'discrete'],
    // discrete Radeon with a real VRAM pool
    ['amd', '0000:0b:00.0', 12 * GIB, 'discrete'],
    // Ryzen APU graphics: non-zero bus but tiny carve-out
    ['amd', '0000:10:00.0', 512 * 1024 * 1024, 'integrated'],
    // AMD with no amdgpu VRAM attribute: cannot prove discrete
    ['amd', '0000:0b:00.0', null, 'unknown'],
    // virtio-gpu and friends
    ['unknown', '0000:00:01.0', null, 'unknown'],
    // unparsable bus id
    ['intel', 'garbage', null, 'unknown'],
  ] as const)('%s @ %s vram=%s → %s', (vendor, busId, vram, expected) => {
    expect(classifyLinuxPciGpu(vendor, busId, vram)).toBe(expected);
  });
});

// ─── listLinuxDriGpus ───────────────────────────────────────────────────────

describe('listLinuxDriGpus', () => {
  const driDeps = (files: Record<string, string>, nodes: string[]) => ({
    readdirSync: (dir: string) => {
      if (dir !== '/sys/class/drm') throw new Error(`unexpected dir ${dir}`);
      return nodes;
    },
    readFileSync: (file: string) => {
      const content = files[file];
      if (content === undefined) throw new Error(`ENOENT ${file}`);
      return content;
    },
    realpathSync: (p: string) =>
      `/sys/devices/pci0000:00/0000:0b:00.0`.replace(/0b/, p.includes('129') ? '0c' : '0b'),
  });

  it('lists an AMD render node and skips the NVIDIA one', async () => {
    const deps = driDeps(
      {
        '/sys/class/drm/renderD128/device/vendor': '0x10de\n',
        '/sys/class/drm/renderD129/device/vendor': '0x1002\n',
        '/sys/class/drm/renderD129/device/mem_info_vram_total': `${12 * 1024 * 1024 * 1024}\n`,
      },
      ['renderD128', 'renderD129', 'card0'],
    );
    const gpus = await listLinuxDriGpus(deps);
    expect(gpus).toHaveLength(1);
    expect(gpus[0].vendor).toBe('amd');
    expect(gpus[0].name).toBe('AMD / Radeon GPU');
    expect(gpus[0].kind).toBe('discrete');
    expect(gpus[0].memoryMiB).toBe(12288);
  });

  it('classifies an APU carve-out as integrated', async () => {
    const deps = driDeps(
      {
        '/sys/class/drm/renderD129/device/vendor': '0x1002',
        '/sys/class/drm/renderD129/device/mem_info_vram_total': `${512 * 1024 * 1024}`,
      },
      ['renderD129'],
    );
    const gpus = await listLinuxDriGpus(deps);
    expect(gpus[0].kind).toBe('integrated');
  });

  it('uses lspci for the marketing name when available', async () => {
    const deps = {
      ...driDeps({ '/sys/class/drm/renderD128/device/vendor': '0x1002' }, ['renderD128']),
      exec: async (cmd: string, args: string[]) => {
        expect(cmd).toBe('lspci');
        expect(args).toEqual(['-s', '0000:0b:00.0']);
        return '0b:00.0 VGA compatible controller: AMD Navi 22 [Radeon RX 6700 XT]';
      },
    };
    const gpus = await listLinuxDriGpus(deps);
    expect(gpus[0].name).toBe('AMD Navi 22 [Radeon RX 6700 XT]');
  });

  it('returns [] when /sys/class/drm is unreadable', async () => {
    const gpus = await listLinuxDriGpus({
      readdirSync: () => {
        throw new Error('EACCES');
      },
      readFileSync: () => '',
      realpathSync: (p: string) => p,
    });
    expect(gpus).toEqual([]);
  });
});

// ─── enumerateGpus ──────────────────────────────────────────────────────────

describe('enumerateGpus', () => {
  const NVIDIA_CSV =
    '0, NVIDIA GeForce RTX 3060, 12288, GPU-aaa\n1, NVIDIA GeForce RTX 3090, 24576, GPU-bbb';

  it('returns nvidia-smi devices first, then Linux DRI devices', async () => {
    const gpus = await enumerateGpus({
      exec: async (cmd) => {
        if (cmd === 'nvidia-smi') return NVIDIA_CSV;
        throw new Error(`unexpected ${cmd}`);
      },
      platform: 'linux',
      dri: {
        readdirSync: () => ['renderD128'],
        readFileSync: () => '0x1002',
        realpathSync: () => '/sys/devices/pci0000:00/0000:0b:00.0',
      },
    });
    expect(gpus.map((g) => g.vendor)).toEqual(['nvidia', 'nvidia', 'amd']);
    expect(gpus[1].uuid).toBe('GPU-bbb');
  });

  it('survives nvidia-smi being absent', async () => {
    const gpus = await enumerateGpus({
      exec: async () => {
        throw new Error('ENOENT nvidia-smi');
      },
      platform: 'linux',
      dri: {
        readdirSync: () => ['renderD128'],
        readFileSync: () => '0x1002',
        realpathSync: () => '/sys/devices/pci0000:00/0000:0b:00.0',
      },
    });
    expect(gpus.map((g) => g.vendor)).toEqual(['amd']);
  });

  it('drops duplicate NVIDIA rows from the Windows CIM query when nvidia-smi worked', async () => {
    const gpus = await enumerateGpus({
      exec: async (cmd) => {
        if (cmd === 'nvidia-smi') return '0, NVIDIA GeForce RTX 3090, 24576, GPU-bbb';
        return 'NVIDIA GeForce RTX 3090\nAMD Radeon RX 6700 XT';
      },
      platform: 'win32',
    });
    expect(gpus.map((g) => g.vendor)).toEqual(['nvidia', 'amd']);
    expect(gpus[0].uuid).toBe('GPU-bbb');
  });

  it('keeps the CIM NVIDIA row when nvidia-smi failed (broken driver visibility)', async () => {
    const gpus = await enumerateGpus({
      exec: async (cmd) => {
        if (cmd === 'nvidia-smi') throw new Error('not found');
        return 'NVIDIA GeForce RTX 3090';
      },
      platform: 'win32',
    });
    expect(gpus).toHaveLength(1);
    expect(gpus[0].vendor).toBe('nvidia');
    expect(gpus[0].uuid).toBeNull();
  });
});

// ─── resolveGpuDeviceSelection ──────────────────────────────────────────────

describe('resolveGpuDeviceSelection', () => {
  const GPUS: GpuDevice[] = [
    {
      vendor: 'nvidia',
      kind: 'discrete',
      index: 0,
      name: 'RTX 3060',
      memoryMiB: 12288,
      uuid: 'GPU-aaa',
    },
    {
      vendor: 'nvidia',
      kind: 'discrete',
      index: 1,
      name: 'RTX 3090',
      memoryMiB: 24576,
      uuid: 'GPU-bbb',
    },
    {
      vendor: 'amd',
      kind: 'discrete',
      index: null,
      name: 'RX 6700 XT',
      memoryMiB: null,
      uuid: null,
    },
  ];

  it('auto / unset / null leave the compose variable unset', () => {
    for (const stored of ['auto', undefined, null, ''] as const) {
      const res = resolveGpuDeviceSelection(stored, GPUS);
      expect(res.composeValue).toBeNull();
      expect(res.reason).toBe('auto');
    }
  });

  it('resolves a stored UUID to its current nvidia-smi index', () => {
    const res = resolveGpuDeviceSelection('GPU-bbb', GPUS);
    expect(res.composeValue).toBe('1');
    expect(res.reason).toBe('resolved');
    expect(res.device?.name).toBe('RTX 3090');
  });

  it('falls back to compose defaults for a UUID that is no longer present', () => {
    const res = resolveGpuDeviceSelection('GPU-gone', GPUS);
    expect(res.composeValue).toBeNull();
    expect(res.reason).toBe('stale-selection');
  });

  it('never matches non-NVIDIA devices', () => {
    const res = resolveGpuDeviceSelection('GPU-aaa', [
      { vendor: 'amd', kind: 'discrete', index: 2, name: 'x', memoryMiB: null, uuid: 'GPU-aaa' },
    ]);
    expect(res.composeValue).toBeNull();
    expect(res.reason).toBe('stale-selection');
  });
});
