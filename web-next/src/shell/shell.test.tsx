// @vitest-environment jsdom
import React from 'react';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import userEvent from '@testing-library/user-event';
import {waitFor} from '@testing-library/react';
import {Modal} from '../components/ui';
import {AppShell} from './index';
import fixture from '../fixtures/state.json';
import type {UIState} from '../contracts';
afterEach(cleanup);
it('navigates every configured destination and labels synthetic evidence',()=>{
  const onNavigate=vi.fn();
  render(<AppShell route="home" onNavigate={onNavigate} state={fixture as UIState} theme="dark" onThemeChange={vi.fn()} onOpenVisit={vi.fn()}><p>Visit content</p></AppShell>);
  expect(screen.getByRole('main')).toHaveTextContent('Visit content');
  expect(screen.getByText('Demo data')).toBeVisible();
  expect(screen.queryByRole('button',{name:/^Clips$/})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Media library'}));
  expect(onNavigate).toHaveBeenCalledWith('media');
  expect(screen.getByRole('button',{name:'Home',current:'page'})).toBeVisible();
});
it('applies the chosen theme to portal overlays as well as the shell',()=>{
  render(<AppShell route="home" onNavigate={vi.fn()} state={fixture as UIState} theme="light" onThemeChange={vi.fn()} onOpenVisit={vi.fn()}>Evidence</AppShell>);
  expect(document.documentElement.dataset.theme).toBe('light');
});
it('returns a notification-launched visit to the stable bell after Escape',async()=>{
  function Harness(){const [visit,setVisit]=React.useState<string|null>(null);return <><AppShell route="home" onNavigate={vi.fn()} state={fixture as UIState} theme="dark" onThemeChange={vi.fn()} onOpenVisit={setVisit}>Evidence</AppShell><Modal open={visit!==null} title="Visit evidence" onClose={()=>setVisit(null)}>Cited notification evidence</Modal></>;}
  const user=userEvent.setup();render(<Harness/>);
  const bell=screen.getByRole('button',{name:/^Notifications/});
  bell.focus();await user.keyboard('{Enter}{ArrowDown}{Enter}');
  expect(await screen.findByRole('dialog',{name:'Visit evidence'})).toBeVisible();
  await user.keyboard('{Escape}');
  await waitFor(()=>expect(bell).toHaveFocus());
});
