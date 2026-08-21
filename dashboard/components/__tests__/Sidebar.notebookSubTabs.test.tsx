/**
 * Sidebar Notebook sub-tab navigation.
 *
 * Two behaviours are locked down here:
 *   1. The Notebook row only collapses its Search / Import strip when the
 *      user clicks it while already parked on the Notebook row. Reaching the
 *      row from another view, or from one of the sub-tabs, never collapses.
 *   2. The cyan active indicator retargets onto the selected sub-tab row,
 *      which is shorter than a primary nav row, so the pill tracks the
 *      measured row height and not just its offset.
 */

import React, { useState } from 'react';
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { Sidebar } from '../Sidebar';
import { View, NotebookTab } from '../../types';

vi.mock('../profiles/ProfileSelector', () => ({
  ProfileSelector: () => React.createElement('div', { 'data-testid': 'profile-selector' }),
}));

vi.mock('../profiles/ModelProfileSelector', () => ({
  ModelProfileSelector: () =>
    React.createElement('div', { 'data-testid': 'model-profile-selector' }),
}));

const NAV_ROW_HEIGHT_PX = 48;
const SUB_ROW_HEIGHT_PX = 36;

// jsdom reports every offset as 0, so the pill has nothing to measure. Derive
// the row height from the Tailwind height class the row actually carries.
let originalOffsetHeight: PropertyDescriptor | undefined;

beforeAll(() => {
  originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.className.includes('h-9') ? SUB_ROW_HEIGHT_PX : NAV_ROW_HEIGHT_PX;
    },
  });
});

afterAll(() => {
  if (originalOffsetHeight) {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeight);
  }
});

/** Sidebar is fully controlled, so the test owns the view + sub-tab state. */
const Harness: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.SESSION);
  const [notebookTab, setNotebookTab] = useState<NotebookTab>(NotebookTab.CALENDAR);

  return (
    <Sidebar
      currentView={currentView}
      onChangeView={setCurrentView}
      notebookTab={notebookTab}
      onChangeNotebookTab={setNotebookTab}
      onOpenSettings={() => {}}
      onOpenAbout={() => {}}
      onOpenBugReport={() => {}}
      containerRunning={false}
      containerExists={false}
      clientRunning={false}
    />
  );
};

const clickRow = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const subTabsVisible = () => screen.queryByRole('button', { name: 'Search' }) !== null;
const indicatorHeight = () => screen.getByTestId('sidebar-active-indicator').style.height;

describe('Sidebar Notebook sub-tabs', () => {
  it('reveals the sub-tabs when the Notebook row is reached from another view', () => {
    render(<Harness />);
    expect(subTabsVisible()).toBe(false);

    clickRow('Notebook');

    expect(subTabsVisible()).toBe(true);
    expect(screen.getByRole('button', { name: 'Import' })).toBeInTheDocument();
  });

  it('collapses the sub-tabs on a second click from the Notebook row itself', () => {
    render(<Harness />);

    clickRow('Notebook');
    expect(subTabsVisible()).toBe(true);

    clickRow('Notebook');
    expect(subTabsVisible()).toBe(false);
  });

  it('keeps the sub-tabs open when the Notebook row is reached from a sub-tab', () => {
    render(<Harness />);

    clickRow('Notebook');
    clickRow('Search');
    expect(subTabsVisible()).toBe(true);

    // The click that used to collapse the strip now only walks back to the
    // calendar, because the user was parked on Search rather than on Notebook.
    clickRow('Notebook');
    expect(subTabsVisible()).toBe(true);

    // And the next click, now genuinely from the Notebook row, collapses.
    clickRow('Notebook');
    expect(subTabsVisible()).toBe(false);
  });

  it('re-opens the sub-tabs after a detour through another view', () => {
    render(<Harness />);

    clickRow('Notebook');
    clickRow('Notebook');
    expect(subTabsVisible()).toBe(false);

    clickRow('Server');
    clickRow('Notebook');

    expect(subTabsVisible()).toBe(true);
  });

  it('collapses the sub-tabs when leaving the Notebook view', () => {
    render(<Harness />);

    clickRow('Notebook');
    expect(subTabsVisible()).toBe(true);

    clickRow('Logs');
    expect(subTabsVisible()).toBe(false);
  });
});

describe('Sidebar active indicator', () => {
  it('retargets onto the selected sub-tab row and back', () => {
    render(<Harness />);

    clickRow('Notebook');
    expect(indicatorHeight()).toBe(`${NAV_ROW_HEIGHT_PX}px`);

    clickRow('Search');
    expect(indicatorHeight()).toBe(`${SUB_ROW_HEIGHT_PX}px`);

    clickRow('Import');
    expect(indicatorHeight()).toBe(`${SUB_ROW_HEIGHT_PX}px`);

    clickRow('Notebook');
    expect(indicatorHeight()).toBe(`${NAV_ROW_HEIGHT_PX}px`);
  });

  it('stays on the nav row for the primary views', () => {
    render(<Harness />);

    clickRow('Server');
    expect(indicatorHeight()).toBe(`${NAV_ROW_HEIGHT_PX}px`);
  });
});
