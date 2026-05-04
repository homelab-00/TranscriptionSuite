/**
 * DeleteRecordingDialog tests (Issue #104, Story 3.7).
 *
 * Covers:
 *   - AC1: dialog text mentions "NOT be deleted by default"
 *   - AC2: checkbox defaults UNCHECKED (least surprise)
 *   - AC3: confirming with checked/unchecked emits the correct flag
 *   - AC4: Delete button has aria-label="Confirm delete recording {name}"
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DeleteRecordingDialog } from '../DeleteRecordingDialog';

describe('DeleteRecordingDialog — AC3.7.AC1 explicit text', () => {
  it('warns that on-disk files are kept by default', () => {
    render(
      <DeleteRecordingDialog open recordingName="Sample" onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    expect(screen.getByText(/NOT/)).toBeInTheDocument();
    expect(screen.getByText(/will[\s\S]*be\s*deleted by default/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Also delete on-disk transcript and summary files/),
    ).toBeInTheDocument();
  });
});

describe('DeleteRecordingDialog — AC3.7.AC2 checkbox defaults unchecked', () => {
  it('checkbox is unchecked initially', () => {
    render(
      <DeleteRecordingDialog open recordingName="Sample" onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).not.toBeChecked();
  });
});

describe('DeleteRecordingDialog — AC3.7.AC2/AC3 confirmation semantics', () => {
  it('emits deleteArtifacts=false when checkbox left unchecked', () => {
    const onConfirm = vi.fn();
    render(
      <DeleteRecordingDialog
        open
        recordingName="Sample"
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Confirm delete recording Sample',
      }),
    );
    expect(onConfirm).toHaveBeenCalledWith(false);
  });

  it('emits deleteArtifacts=true when checkbox is checked', () => {
    const onConfirm = vi.fn();
    render(
      <DeleteRecordingDialog
        open
        recordingName="Sample"
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Confirm delete recording Sample',
      }),
    );
    expect(onConfirm).toHaveBeenCalledWith(true);
  });

  it('Cancel button calls onCancel without firing onConfirm', () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <DeleteRecordingDialog
        open
        recordingName="Sample"
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe('DeleteRecordingDialog — AC3.7.AC4 a11y label', () => {
  it('Delete button has descriptive aria-label including recording name', () => {
    render(
      <DeleteRecordingDialog
        open
        recordingName="Friday meeting"
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(
      screen.getByRole('button', {
        name: 'Confirm delete recording Friday meeting',
      }),
    ).toBeInTheDocument();
  });
});
