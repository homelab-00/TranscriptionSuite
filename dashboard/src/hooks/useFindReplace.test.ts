import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { useFindReplace } from './useFindReplace';

function setup(initialValue: string) {
  const textarea = document.createElement('textarea');
  textarea.value = initialValue;
  document.body.appendChild(textarea);
  const textareaRef = { current: textarea };

  let value = initialValue;
  const onChange = vi.fn((next: string) => {
    value = next;
    textarea.value = next;
  });

  const view = renderHook(({ v }) => useFindReplace({ textareaRef, value: v, onChange }), {
    initialProps: { v: initialValue },
  });

  const commit = () => view.rerender({ v: value });
  return { view, textarea, onChange, commit, getValue: () => value };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('useFindReplace', () => {
  it('counts matches and defaults to case-insensitive', () => {
    const { view } = setup('Foo foo');
    act(() => view.result.current.setQuery('foo'));
    expect(view.result.current.matchCount).toBe(2);

    act(() => view.result.current.toggleCaseSensitive());
    expect(view.result.current.matchCount).toBe(1);
  });

  it('opens in the requested mode and closes', () => {
    const { view } = setup('text');
    expect(view.result.current.isOpen).toBe(false);

    act(() => view.result.current.open('replace'));
    expect(view.result.current.isOpen).toBe(true);
    expect(view.result.current.mode).toBe('replace');

    act(() => view.result.current.close());
    expect(view.result.current.isOpen).toBe(false);
  });

  it('wraps around with next()', () => {
    const { view } = setup('a a a');
    act(() => view.result.current.setQuery('a'));
    expect(view.result.current.currentIndex).toBe(0);

    act(() => view.result.current.next());
    expect(view.result.current.currentIndex).toBe(1);
    act(() => view.result.current.next());
    expect(view.result.current.currentIndex).toBe(2);
    act(() => view.result.current.next());
    expect(view.result.current.currentIndex).toBe(0); // wrap
  });

  it('wraps around with prev()', () => {
    const { view } = setup('a a a');
    act(() => view.result.current.setQuery('a'));
    act(() => view.result.current.prev());
    expect(view.result.current.currentIndex).toBe(2); // wrap backwards
  });

  it('clamps the active index when the text shrinks the match set', () => {
    const { view } = setup('a a a');
    act(() => view.result.current.setQuery('a'));
    act(() => view.result.current.next());
    act(() => view.result.current.next());
    expect(view.result.current.currentIndex).toBe(2);

    act(() => view.rerender({ v: 'a' })); // now only 1 match
    expect(view.result.current.matchCount).toBe(1);
    expect(view.result.current.currentIndex).toBe(0);
  });

  it('replaceCurrentMatch commits one replacement and recomputes', () => {
    const { view, onChange, commit } = setup('foo foo');
    act(() => view.result.current.setQuery('foo'));
    act(() => view.result.current.setReplacement('bar'));

    act(() => view.result.current.replaceCurrentMatch());
    expect(onChange).toHaveBeenCalledWith('bar foo');

    act(() => commit());
    expect(view.result.current.matchCount).toBe(1); // one 'foo' remains
  });

  it('replaceAllMatches replaces every occurrence', () => {
    const { view, onChange } = setup('foo foo foo');
    act(() => view.result.current.setQuery('foo'));
    act(() => view.result.current.setReplacement('bar'));

    act(() => view.result.current.replaceAllMatches());
    expect(onChange).toHaveBeenCalledWith('bar bar bar');
  });

  it('resets to the first match when the query changes', () => {
    const { view } = setup('a a a');
    act(() => view.result.current.setQuery('a'));
    act(() => view.result.current.next()); // index 1
    expect(view.result.current.currentIndex).toBe(1);

    act(() => view.result.current.setQuery('a a')); // new search
    expect(view.result.current.currentIndex).toBe(0);
  });

  it('moves the textarea selection onto the active match while open', () => {
    const { view, textarea } = setup('hello world');
    act(() => view.result.current.open('find'));
    act(() => view.result.current.setQuery('world'));

    expect(textarea.selectionStart).toBe(6);
    expect(textarea.selectionEnd).toBe(11);
  });

  it('advances to the next occurrence after replaceCurrentMatch', () => {
    const { view, commit } = setup('cat cat cat');
    act(() => view.result.current.setQuery('cat'));
    act(() => view.result.current.setReplacement('dog'));

    act(() => view.result.current.replaceCurrentMatch());
    act(() => commit()); // value → 'dog cat cat'

    // Two 'cat' remain; the active match resumes past the inserted 'dog'.
    expect(view.result.current.matchCount).toBe(2);
    expect(view.result.current.currentIndex).toBe(0);
  });

  it('makes forward progress when the replacement contains the query', () => {
    const { view, commit } = setup('x y x');
    act(() => view.result.current.setQuery('x'));
    act(() => view.result.current.setReplacement('xx'));

    act(() => view.result.current.replaceCurrentMatch());
    act(() => commit()); // value → 'xx y x'

    // The inserted 'xx' (offsets 0–1) must NOT become the active match;
    // the cursor anchors at offset 2, landing on the original trailing 'x'.
    expect(view.result.current.currentIndex).toBe(2);
  });
});
