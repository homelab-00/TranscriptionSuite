import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useState } from 'react';
import { FindReplaceTextEditor, type FindReplaceTextEditorProps } from './FindReplaceTextEditor';

type HarnessProps = Partial<FindReplaceTextEditorProps> & { initial?: string };

function Harness({ initial = '', ...props }: HarnessProps) {
  const [value, setValue] = useState(initial);
  return <FindReplaceTextEditor value={value} onChange={setValue} ariaLabel="editor" {...props} />;
}

const getEditor = () => screen.getByLabelText('editor') as HTMLTextAreaElement;

describe('FindReplaceTextEditor', () => {
  it('reveals the find control only when focused', () => {
    render(<Harness initial="hello world" />);
    expect(screen.queryByLabelText('Find and replace')).toBeNull();

    fireEvent.focusIn(getEditor());
    expect(screen.getByLabelText('Find and replace')).toBeInTheDocument();

    fireEvent.focusOut(getEditor(), { relatedTarget: null });
    expect(screen.queryByLabelText('Find and replace')).toBeNull();
  });

  it('opens the find bar on Ctrl+F', () => {
    render(<Harness initial="abc" />);
    fireEvent.keyDown(getEditor(), { key: 'f', ctrlKey: true });
    expect(screen.getByLabelText('Find')).toBeInTheDocument();
  });

  it('opens the replace row on Ctrl+H', () => {
    render(<Harness initial="abc" />);
    fireEvent.keyDown(getEditor(), { key: 'h', ctrlKey: true });
    expect(screen.getByLabelText('Find')).toBeInTheDocument();
    expect(screen.getByLabelText('Replace')).toBeInTheDocument();
  });

  it('closes the bar on Esc', () => {
    render(<Harness initial="abc" />);
    fireEvent.keyDown(getEditor(), { key: 'f', ctrlKey: true });
    expect(screen.getByLabelText('Find')).toBeInTheDocument();

    fireEvent.keyDown(getEditor(), { key: 'Escape' });
    expect(screen.queryByLabelText('Find')).toBeNull();
  });

  it('reflects edits through onChange', () => {
    render(<Harness initial="old" />);
    fireEvent.change(getEditor(), { target: { value: 'new text' } });
    expect(getEditor().value).toBe('new text');
  });

  it('replace-all rewrites the editor value', () => {
    render(<Harness initial="foo foo foo" />);
    fireEvent.keyDown(getEditor(), { key: 'h', ctrlKey: true });

    fireEvent.change(screen.getByLabelText('Find'), { target: { value: 'foo' } });
    fireEvent.change(screen.getByLabelText('Replace'), { target: { value: 'bar' } });
    fireEvent.click(screen.getByLabelText('Replace all'));

    expect(getEditor().value).toBe('bar bar bar');
  });

  it('shows the live match counter', () => {
    render(<Harness initial="a a a" />);
    fireEvent.keyDown(getEditor(), { key: 'f', ctrlKey: true });
    fireEvent.change(screen.getByLabelText('Find'), { target: { value: 'a' } });
    expect(screen.getByText('1/3')).toBeInTheDocument();
  });

  it('readOnly blocks editing and hides the control', () => {
    render(<Harness initial="locked" readOnly />);
    const ta = getEditor();
    expect(ta.readOnly).toBe(true);

    fireEvent.focusIn(ta);
    expect(screen.queryByLabelText('Find and replace')).toBeNull();
  });
});
