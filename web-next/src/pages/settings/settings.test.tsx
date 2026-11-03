// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import fixture from '../../fixtures/state.json';
import type {PageProps, UIState} from '../../contracts';
import {SettingsPage} from './index';
import {RulesPage} from '../rules';
import {BenchmarkPage} from '../benchmark';

const state=fixture as unknown as UIState;
const base=():PageProps=>({state:structuredClone(state),onOpenVisit:vi.fn(),onOpenClip:vi.fn()});
afterEach(()=>{cleanup();vi.useRealTimers();});

describe('Settings owner boundaries (FR-029, FR-044)',()=>{
  it('keeps every owner action disabled in sandbox even when callbacks are supplied',async()=>{
    const props=base();const saveToken=vi.fn(),checkIn=vi.fn(),createWindow=vi.fn();
    render(<SettingsPage {...props} ownerActions={{saveToken,checkIn,createWindow}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    expect(screen.getByText('Owner-only on the home box')).toBeVisible();
    expect(screen.getByLabelText('Owner token')).toBeDisabled();
    expect(screen.getByRole('button',{name:'Save owner token'})).toBeDisabled();
    expect(screen.getByRole('button',{name:"I'm outside"})).toBeDisabled();
    expect(screen.getByRole('button',{name:'New expected window'})).toBeDisabled();
    expect(saveToken).not.toHaveBeenCalled();expect(checkIn).not.toHaveBeenCalled();expect(createWindow).not.toHaveBeenCalled();
  });
  it('allows edge token entry before authentication, without enabling mutations',async()=>{
    const props=base();props.state.mode='edge';const saveToken=vi.fn();
    render(<SettingsPage {...props} ownerActions={{saveToken,checkIn:vi.fn()}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    await userEvent.type(screen.getByLabelText('Owner token'),'offline-test-value');
    await userEvent.click(screen.getByRole('button',{name:'Save owner token'}));
    expect(saveToken).toHaveBeenCalledWith('offline-test-value');
    expect(screen.getByLabelText('Owner token')).toHaveValue('');
    expect(screen.getByRole('button',{name:"I'm outside"})).toBeDisabled();
    expect(localStorage.getItem('vigil_owner_token')).toBeNull();
  });
  it('sends timezone-aware valid windows and the selected configured camera',async()=>{
    const props=base();props.state.mode='edge';props.state.owner.enabled=true;const createWindow=vi.fn();
    render(<SettingsPage {...props} ownerActions={{createWindow,checkIn:vi.fn()}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    await userEvent.click(screen.getByRole('button',{name:'New expected window'}));
    fireEvent.change(screen.getByLabelText('Window starts'),{target:{value:'2026-11-04T12:00'}});
    fireEvent.change(screen.getByLabelText('Window ends'),{target:{value:'2026-11-04T13:00'}});
    await userEvent.type(screen.getByLabelText('Window label'),'Delivery');
    await userEvent.selectOptions(screen.getByLabelText('Window camera'),'doorbell');
    await userEvent.click(screen.getByRole('button',{name:'Create expected window'}));
    expect(createWindow).toHaveBeenCalledOnce();
    const input=createWindow.mock.calls[0][0];
    expect(input.cameras).toEqual(['doorbell']);expect(input.label).toBe('Delivery');
    expect(input.start).toMatch(/Z$/);expect(input.end).toMatch(/Z$/);
    expect(new Date(input.end).getTime()-new Date(input.start).getTime()).toBe(3600000);
  });
  it('rejects reversed and over-twelve-hour windows without a callback',async()=>{
    const props=base();props.state.mode='edge';props.state.owner.enabled=true;const createWindow=vi.fn();
    render(<SettingsPage {...props} ownerActions={{createWindow}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    await userEvent.click(screen.getByRole('button',{name:'New expected window'}));
    fireEvent.change(screen.getByLabelText('Window starts'),{target:{value:'2026-11-04T12:00'}});
    fireEvent.change(screen.getByLabelText('Window ends'),{target:{value:'2026-11-04T11:00'}});
    await userEvent.click(screen.getByRole('button',{name:'Create expected window'}));
    expect(screen.getByRole('alert')).toHaveTextContent('after');
    fireEvent.change(screen.getByLabelText('Window ends'),{target:{value:'2026-11-05T01:00'}});
    await userEvent.click(screen.getByRole('button',{name:'Create expected window'}));
    expect(screen.getByRole('alert')).toHaveTextContent('12 hours');expect(createWindow).not.toHaveBeenCalled();
  });
  it('keeps recorded windows immutable and shows the recorded expired example',async()=>{
    const props=base();props.state.mode='edge';props.state.owner.enabled=true;const cancelWindow=vi.fn();
    render(<SettingsPage {...props} ownerActions={{cancelWindow}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    const row=screen.getByRole('article',{name:'deliveries'});
    expect(row).toHaveTextContent('Recorded example');expect(row).toHaveTextContent('Expired');
    expect(within(row).getByRole('button',{name:'Cancel window'})).toBeDisabled();expect(cancelWindow).not.toHaveBeenCalled();
  });
  it('uses real owner callbacks, pending/error props and expiry timestamps',async()=>{
    vi.setSystemTime(new Date('2026-11-03T12:00:00Z'));
    const props=base();props.state.mode='edge';props.state.owner.enabled=true;const checkIn=vi.fn();
    const view=render(<SettingsPage {...props} ownerActions={{checkIn,checkinExpiresAt:'2026-11-03T12:02:00Z'}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    expect(screen.getByText('120 s remaining')).toBeVisible();
    await userEvent.click(screen.getByRole('button',{name:"I'm outside"}));expect(checkIn).toHaveBeenCalledOnce();
    view.rerender(<SettingsPage {...props} ownerActions={{checkIn,pending:true,error:'Owner session expired'}}/>);
    expect(screen.getByRole('button',{name:"I'm outside"})).toBeDisabled();expect(screen.getByRole('alert')).toHaveTextContent('Owner session expired');
  });
  it('shows seven supplied cameras and never turns unknown telemetry into zero or online',()=>{
    render(<SettingsPage {...base()}/>);
    expect(screen.getAllByRole('article',{name:/camera$/})).toHaveLength(7);
    expect(screen.queryByText(/^Online$/)).not.toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
    expect(within(screen.getByRole('article',{name:'Front left Duo camera'})).getAllByText('Not connected')).toHaveLength(1);
  });
  it('uses the shared dialog for expected-window creation and restores its opener',async()=>{
    const props=base();props.state.mode='edge';props.state.owner.enabled=true;
    render(<SettingsPage {...props} ownerActions={{createWindow:vi.fn()}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    const opener=screen.getByRole('button',{name:'New expected window'});
    await userEvent.click(opener);expect(screen.getByRole('dialog',{name:'New expected window'})).toBeVisible();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await vi.waitFor(()=>expect(opener).toHaveFocus());
  });
  it('cancels only a mutable owner window using its actual ID',async()=>{
    const props=base();props.state.mode='edge';props.state.owner.enabled=true;
    props.state.owner.windows=[{...state.owner.windows[0],id:'mutable-id',recorded:false,state:'scheduled'}];
    const cancelWindow=vi.fn();render(<SettingsPage {...props} ownerActions={{cancelWindow}}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    await userEvent.click(screen.getByRole('button',{name:'Cancel window'}));
    expect(cancelWindow).toHaveBeenCalledWith('mutable-id');
  });
  it('preserves the recorded offset instead of relabelling window times',async()=>{
    render(<SettingsPage {...base()}/>);
    await userEvent.click(screen.getByRole('tab',{name:'Owner controls'}));
    expect(screen.getByText('Nov 2, 4:00 PM (UTC-08:00) – Nov 2, 4:45 PM (UTC-08:00)')).toBeVisible();
  });
});

describe('Rules and benchmark evidence (FR-012, FR-021, FR-022, FR-024)',()=>{
  it('renders actual rules and protected objects with icon-plus-word severity',()=>{
    render(<RulesPage {...base()}/>);
    expect(screen.getByText('Watched package removed')).toBeVisible();
    expect(screen.getByText('side gate')).toBeVisible();
    expect(screen.getAllByText('Needs attention')).toHaveLength(state.rules.length);
    expect(screen.getAllByText('Everyone except household')).toHaveLength(state.rules.length);
  });
  it('does not fake compile when no callback exists',async()=>{
    render(<RulesPage {...base()}/>);
    expect(screen.getByRole('button',{name:'Review rule draft'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Record a voice rule'})).toBeDisabled();
  });
  it('compiles trimmed text through the supplied callback and displays server notice',async()=>{
    const compile=vi.fn();render(<RulesPage {...base()} ruleActions={{compile,notice:'Recorded result shown'}}/>);
    await userEvent.type(screen.getByLabelText('Rule text'),'  Alert when a package is removed  ');
    await userEvent.click(screen.getByRole('button',{name:'Review rule draft'}));
    expect(compile).toHaveBeenCalledWith('Alert when a package is removed');
    expect(screen.getByRole('status')).toHaveTextContent('Recorded result shown');
  });
  it('requires owner context before confirming a draft and preserves its supplied role scope',()=>{
    const props=base();const confirm=vi.fn();const draft={...state.rules[0],id:'draft-real-id',state:'draft'};
    const view=render(<RulesPage {...props} ruleActions={{draft,confirm}}/>);
    expect(screen.getByRole('button',{name:'Confirm rule'})).toBeDisabled();
    props.state.mode='edge';props.state.owner.enabled=true;
    view.rerender(<RulesPage {...props} ruleActions={{draft,confirm}}/>);
    fireEvent.click(screen.getByRole('button',{name:'Confirm rule'}));expect(confirm).toHaveBeenCalledWith('draft-real-id');
  });
  it('uses consented phone fixture callbacks without requesting camera audio',async()=>{
    const transcribeFixture=vi.fn(),recordVoice=vi.fn();
    render(<RulesPage {...base()} ruleActions={{transcribeFixture,recordVoice,voiceFixtures:[{id:'consented',label:'Package rule sample',url:null}]}}/>);
    await userEvent.click(screen.getByRole('button',{name:'Package rule sample'}));expect(transcribeFixture).toHaveBeenCalledWith('consented');
    await userEvent.click(screen.getByRole('button',{name:'Record a voice rule'}));expect(recordVoice).toHaveBeenCalledOnce();
    expect(screen.getByText(/Phone microphone only/)).toBeVisible();
  });
  it('keeps benchmark empty when measured is false even if synthetic telemetry is present',()=>{
    const props=base();props.state.benchmark.metrics=[{label:'Invented test metric',value:99}];
    render(<BenchmarkPage {...props}/>);
    expect(screen.getByText('No field benchmark yet')).toBeVisible();expect(screen.queryByText('99')).not.toBeInTheDocument();
  });
  it('renders only supplied measured benchmark values and units',()=>{
    const props=base();props.state.benchmark={measured:true,note:'Measured offline fixture for rendering only',metrics:[{id:'precision',label:'Link precision',value:91,unit:'%'}]};
    render(<BenchmarkPage {...props}/>);
    expect(screen.getByText('Link precision')).toBeVisible();expect(screen.getByText('91 %')).toBeVisible();
  });
});
