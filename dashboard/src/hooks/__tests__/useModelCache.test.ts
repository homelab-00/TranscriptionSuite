import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useModelCache } from '../useModelCache';

const dockerCheck = vi.fn();
const mlxCheck = vi.fn();

beforeEach(() => {
  dockerCheck.mockReset().mockResolvedValue({ 'a/b': { exists: true, size: '1 GB' } });
  mlxCheck.mockReset().mockResolvedValue({ 'c/d': { exists: true, size: '2 GB' } });
  (window as any).electronAPI = {
    docker: { checkModelsCached: dockerCheck },
    mlx: { checkModelsCached: mlxCheck },
  };
});

afterEach(() => {
  delete (window as any).electronAPI;
});

describe('useModelCache', () => {
  it('starts empty', () => {
    const { result } = renderHook(() => useModelCache({ isRunning: false, isMetal: false }));
    expect(result.current.modelCacheStatus).toEqual({});
  });

  it('does not probe Docker while the container is stopped', () => {
    const { result } = renderHook(() => useModelCache({ isRunning: false, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b']));

    expect(dockerCheck).not.toHaveBeenCalled();
  });

  it('merges Docker results once the container is running', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b']));

    await waitFor(() => {
      expect(result.current.modelCacheStatus['a/b']).toEqual({ exists: true, size: '1 GB' });
    });
    expect(dockerCheck).toHaveBeenCalledWith(['a/b']);
  });

  // On Metal there is no container: the cache is a plain host-filesystem check
  // that works with the server stopped, and docker.container.running is
  // permanently false there (GH-136).
  it('probes MLX on Metal even when nothing is running', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: false, isMetal: true }));

    act(() => result.current.refreshCacheStatus(['c/d']));

    await waitFor(() => {
      expect(result.current.modelCacheStatus['c/d']).toEqual({ exists: true, size: '2 GB' });
    });
    expect(mlxCheck).toHaveBeenCalledWith(['c/d']);
    expect(dockerCheck).not.toHaveBeenCalled();
  });

  it('deduplicates ids and drops empty ones', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b', 'a/b', '']));

    await waitFor(() => expect(dockerCheck).toHaveBeenCalledWith(['a/b']));
  });

  it('does nothing when there is no id to check', () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus([]));

    expect(dockerCheck).not.toHaveBeenCalled();
  });

  it('merges successive probes rather than replacing them', async () => {
    const { result } = renderHook(() => useModelCache({ isRunning: true, isMetal: false }));

    act(() => result.current.refreshCacheStatus(['a/b']));
    await waitFor(() => expect(result.current.modelCacheStatus['a/b']).toBeDefined());

    dockerCheck.mockResolvedValue({ 'e/f': { exists: false } });
    act(() => result.current.refreshCacheStatus(['e/f']));

    await waitFor(() => expect(result.current.modelCacheStatus['e/f']).toBeDefined());
    expect(result.current.modelCacheStatus['a/b']).toEqual({ exists: true, size: '1 GB' });
  });
});
