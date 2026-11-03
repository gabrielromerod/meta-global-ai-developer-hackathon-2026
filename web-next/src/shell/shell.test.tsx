// @vitest-environment jsdom
import React from 'react';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import {AppShell} from './index';
import fixture from '../fixtures/state.json';
import type {UIState} from '../contracts';
afterEach(cleanup);
it('navigates every configured destination and labels synthetic evidence',()=>{
  const onNavigate=vi.fn();
  render(<AppShell route="home" onNavigate={onNavigate} state={fixture as UIState} theme="dark" onThemeChange={vi.fn()} onOpenVisit={vi.fn()}><p>Visit content</p></AppShell>);
  expect(screen.getByRole('main')).toHaveTextContent('Visit content');
  expect(screen.getByText('Demo data')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Media library'}));
  expect(onNavigate).toHaveBeenCalledWith('media');
  expect(screen.getByRole('button',{name:'Home',current:'page'})).toBeVisible();
});
