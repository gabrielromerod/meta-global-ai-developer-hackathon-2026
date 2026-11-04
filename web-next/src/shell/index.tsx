import React, {useEffect, useRef, useState, type ReactNode} from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Tooltip from '@radix-ui/react-tooltip';
import {House, ShieldAlert, Images, MessagesSquare, ShieldCheck, ChartNoAxesColumnIncreasing, Settings2, Bell, Moon, Sun, Menu, Camera, ChevronRight} from 'lucide-react';
import type {UIState, Route, Notification} from '../contracts';
import {Button, Chip, Modal, VerdictBadge, cn} from '../components/ui';
import './shell.css';

const destinations=[{id:'home',label:'Home',icon:House},{id:'attention',label:'Attention',icon:ShieldAlert},{id:'media',label:'Media library',icon:Images},{id:'messages',label:'Messages',icon:MessagesSquare},{id:'rules',label:'Protection',icon:ShieldCheck},{id:'benchmark',label:'Benchmark',icon:ChartNoAxesColumnIncreasing},{id:'settings',label:'Settings',icon:Settings2}] as const;
export interface AppShellProps {title?:string;route:Route;onNavigate:(id:Route)=>void;state:UIState;theme:'dark'|'light';onThemeChange:(theme:'dark'|'light')=>void;onOpenVisit:(id:string)=>void;chatSlot?:ReactNode;children:ReactNode}

function Navigation({route,onNavigate,mobile=false}: {route:Route;onNavigate:(id:Route)=>void;mobile?:boolean}) {return <nav aria-label={mobile?'Mobile navigation':'Main navigation'} className={cn('v-navigation',mobile&&'v-navigation-mobile')}>{destinations.map(({id,label,icon:Icon})=><Tooltip.Root key={id}><Tooltip.Trigger asChild><button type="button" className={cn('v-nav-item',route===id&&'is-active',id==='settings'&&'v-nav-settings')} aria-current={route===id?'page':undefined} aria-label={label} onClick={()=>onNavigate(id)}><Icon aria-hidden="true"/><span>{label}</span></button></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content side="right" className="v-nav-tooltip">{label}</Tooltip.Content></Tooltip.Portal></Tooltip.Root>)}</nav>;}
export function Sidebar({route,onNavigate}: Pick<AppShellProps,'route'|'onNavigate'>&{household:UIState['household']}) {return <aside className="v-sidebar"><div className="v-brand" aria-label="Vigil"><span>Vigil</span></div><Navigation route={route} onNavigate={onNavigate}/></aside>;}
export function NotificationBell({items,onOpenVisit,onOpenAttention}: {items:Notification[];onOpenVisit:(id:string)=>void;onOpenAttention:()=>void}) {
  const triggerRef=useRef<HTMLButtonElement>(null);
  const pendingVisit=useRef<string|null>(null);
  const unread=items.filter(item=>item.unread).length;
  return <DropdownMenu.Root>
    <DropdownMenu.Trigger asChild>
      <Button ref={triggerRef} variant="ghost" size="icon" className="v-notification-trigger" aria-label={unread?`Notifications, ${unread} unread`:'Notifications'}>
        <Bell aria-hidden="true"/>{unread>0&&<span className="v-unread-badge" aria-hidden="true">{unread}</span>}
      </Button>
    </DropdownMenu.Trigger>
    <DropdownMenu.Portal>
      <DropdownMenu.Content align="end" className="v-notifications" onCloseAutoFocus={event=>{
        const visitId=pendingVisit.current;
        if(visitId===null)return;
        pendingVisit.current=null;
        // The selected menu item unmounts. Open the dialog only after Radix closes
        // the menu, so the dialog records its stable bell trigger as the opener.
        event.preventDefault();
        triggerRef.current?.focus();
        onOpenVisit(visitId);
      }}>
        <DropdownMenu.Label className="v-notification-heading">Notifications<span>{unread} unread</span></DropdownMenu.Label>
        <div className="v-notification-scroll">
          {items.length?items.map(item=><DropdownMenu.Item key={item.id} className="v-notification-item" onSelect={()=>{pendingVisit.current=item.visit_id;}}>
            {item.thumbnail_url?<img src={item.thumbnail_url} alt=""/>:<span className="v-notification-thumb"><Camera aria-hidden="true"/></span>}
            <div className="v-notification-copy"><VerdictBadge verdict={item.verdict}/><p>{item.story}</p><time>{item.clock}</time></div>
            {item.unread&&<span className="v-unread-dot" aria-label="Unread"/>}
          </DropdownMenu.Item>):<p className="v-notification-empty">No notifications yet</p>}
        </div>
        <DropdownMenu.Separator className="v-notification-separator"/>
        <DropdownMenu.Item className="v-notification-all" onSelect={onOpenAttention}>Open Attention<ChevronRight aria-hidden="true"/></DropdownMenu.Item>
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  </DropdownMenu.Root>;
}
export function AppShell({title:customTitle,route,onNavigate,state,theme,onThemeChange,onOpenVisit,chatSlot,children}:AppShellProps) {const [menuOpen,setMenuOpen]=useState(false);useEffect(()=>{const previous=document.documentElement.dataset.theme;document.documentElement.dataset.theme=theme;return()=>{if(previous)document.documentElement.dataset.theme=previous;else delete document.documentElement.dataset.theme;};},[theme]);const title=customTitle||destinations.find(item=>item.id===route)?.label||'Home';return <Tooltip.Provider><div className="v-app-shell" data-theme={theme}><Sidebar route={route} onNavigate={onNavigate} household={state.household}/><div className="v-workspace"><header className="v-topbar"><Button variant="ghost" size="icon" className="v-mobile-menu" aria-label="Open navigation" onClick={()=>setMenuOpen(true)}><Menu aria-hidden="true"/></Button><div className="v-page-title"><span className="v-page-context">{state.household.name}</span><h1>{title}</h1></div><div className="v-topbar-actions">{state.evidence.kind==='fixture'&&<Chip>{state.evidence.label}</Chip>}<Button variant="ghost" size="icon" aria-label={`Use ${theme==='dark'?'light':'dark'} theme`} onClick={()=>onThemeChange(theme==='dark'?'light':'dark')}>{theme==='dark'?<Sun aria-hidden="true"/>:<Moon aria-hidden="true"/>}</Button><NotificationBell items={state.notifications} onOpenVisit={onOpenVisit} onOpenAttention={()=>onNavigate('attention')}/></div></header><main id="main-content" className="v-main" aria-label={title}>{children}</main></div>{chatSlot}<Modal open={menuOpen} title="Navigation" onClose={()=>setMenuOpen(false)}><Navigation route={route} onNavigate={id=>{onNavigate(id);setMenuOpen(false);}} mobile/></Modal></div></Tooltip.Provider>;}
