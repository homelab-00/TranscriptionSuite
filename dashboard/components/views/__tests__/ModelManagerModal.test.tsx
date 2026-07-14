// @vitest-environment jsdom
/**
 * ModelManagerModal - the Server-tab modal shell around ModelManagerTab.
 *
 * The central risk this task guards against: ModelManagerTab used to be
 * mounted by ModelManagerView, a route-level component that hydrated from and
 * persisted to electron-store on its own timer, independently of ServerView -
 * even though both wrote the exact same "server.*" keys. Mounting both at
 * once would have raced two writers on those keys. ModelManagerView is now
 * deleted; ModelManagerModal must drive ModelManagerTab purely from props and
 * must never itself touch electron-store. The "does not call config.set on
 * open" test below is the regression guard for that.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ModelManagerModal, type ModelManagerModalProps } from '../ModelManagerModal';

type TabProps = Omit<ModelManagerModalProps, 'isOpen' | 'onClose'>;

function baseTabProps(): TabProps {
  return {
    mainModelSelection: 'Systran/faster-whisper-large-v3',
    setMainModelSelection: vi.fn(),
    mainCustomModel: '',
    setMainCustomModel: vi.fn(),
    liveModelSelection: 'same-as-main',
    setLiveModelSelection: vi.fn(),
    liveCustomModel: '',
    setLiveCustomModel: vi.fn(),
    diarizationModelSelection: 'sortformer',
    setDiarizationModelSelection: vi.fn(),
    diarizationCustomModel: '',
    setDiarizationCustomModel: vi.fn(),
    modelCacheStatus: {},
    isRunning: false,
    refreshCacheStatus: vi.fn(),
    isMetal: false,
    runtimeProfile: 'docker',
    downloadingIds: new Set<string>(),
    hostCacheStatus: {},
    onDownload: vi.fn(),
    onRemove: vi.fn(),
  };
}

describe('ModelManagerModal', () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = undefined;
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <ModelManagerModal isOpen={false} onClose={vi.fn()} {...baseTabProps()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the manager when open', () => {
    render(<ModelManagerModal isOpen={true} onClose={vi.fn()} {...baseTabProps()} />);

    expect(screen.getByRole('dialog', { name: 'Model Manager' })).toBeTruthy();
    expect(screen.getByText('Model Manager')).toBeTruthy();
    expect(screen.getByText('Browse, download, and manage model weights.')).toBeTruthy();
  });

  it('calls onClose when the X button is clicked', () => {
    const onClose = vi.fn();
    render(<ModelManagerModal isOpen={true} onClose={onClose} {...baseTabProps()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when the overlay is clicked', () => {
    const onClose = vi.fn();
    render(<ModelManagerModal isOpen={true} onClose={onClose} {...baseTabProps()} />);

    fireEvent.click(screen.getByRole('dialog', { name: 'Model Manager' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose on Escape', () => {
    const onClose = vi.fn();
    render(<ModelManagerModal isOpen={true} onClose={onClose} {...baseTabProps()} />);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not close when a click originates inside the panel', () => {
    const onClose = vi.fn();
    render(<ModelManagerModal isOpen={true} onClose={onClose} {...baseTabProps()} />);

    fireEvent.click(screen.getByText('Model Manager'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('never writes to electron-store merely by opening (state-ownership guard)', () => {
    const configSet = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).electronAPI = {
      config: {
        get: vi.fn().mockResolvedValue(undefined),
        set: configSet,
      },
    };

    render(<ModelManagerModal isOpen={true} onClose={vi.fn()} {...baseTabProps()} />);

    // ModelManagerTab must be purely prop-driven: it may read persisted
    // custom models via config.get, but it must never call config.set on its
    // own - that would mean it (re)gained a second copy of state that writes
    // the same keys ServerView owns, exactly the bug this task removed.
    expect(configSet).not.toHaveBeenCalled();
  });
});
