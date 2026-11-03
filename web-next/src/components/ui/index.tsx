import React, {forwardRef, type ReactNode, type ButtonHTMLAttributes, type HTMLAttributes} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import {Slot} from '@radix-ui/react-slot';
import {cva, type VariantProps} from 'class-variance-authority';
import {clsx, type ClassValue} from 'clsx';
import {twMerge} from 'tailwind-merge';
import {Check, CircleHelp, CircleAlert, AlertTriangle, Camera as CameraIcon, Play, X, VideoOff} from 'lucide-react';
import type {Camera, Clip, Verdict} from '../../contracts';
import './ui.css';

export function cn(...inputs:ClassValue[]) {return twMerge(clsx(inputs));}
const buttonVariants=cva('v-button', {variants:{variant:{default:'v-button-primary',secondary:'v-button-secondary',ghost:'v-button-ghost',outline:'v-button-outline'},size:{default:'v-button-default',icon:'v-button-icon',sm:'v-button-sm'}},defaultVariants:{variant:'default',size:'default'}});
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {asChild?:boolean}
export const Button=forwardRef<HTMLButtonElement,ButtonProps>(({className,variant,size,asChild=false,type='button',...props},ref)=>{
  const Comp=asChild?Slot:'button';
  return <Comp data-slot="button" ref={ref} type={type} className={cn(buttonVariants({variant,size}),className)} {...props}/>;
});
Button.displayName='Button';
export function Card({title,actions,className,children,...props}:Omit<HTMLAttributes<HTMLElement>,'title'>&{title?:ReactNode;actions?:ReactNode}) {
  return <section data-slot="card" className={cn('v-card',className)} {...props}>{(title||actions)&&<header className="v-card-heading">{title&&<h2>{title}</h2>}{actions}</header>}{children}</section>;
}
export function Chip({children,tone='default',className}: {children:ReactNode;tone?:'default'|'success'|'danger'|'warning'|'unknown';className?:string}) {return <span className={cn('v-chip',`v-tone-${tone}`,className)}>{children}</span>;}
const verdicts={normal:{label:'Normal',icon:Check,tone:'success'},noteworthy:{label:'Noteworthy',icon:CircleAlert,tone:'warning'},needs_attention:{label:'Needs attention',icon:AlertTriangle,tone:'danger'},cant_confirm:{label:"Can't confirm",icon:CircleHelp,tone:'unknown'}} as const;
export function VerdictBadge({verdict,label,className}: {verdict:Verdict;label?:string;className?:string}) {const item=verdicts[verdict];const Icon=item.icon;return <span className={cn('v-verdict',`v-tone-${item.tone}`,className)}><Icon aria-hidden="true"/><span>{label||item.label}</span></span>;}
export function Tabs({items,value,onChange,label,className,children}: {items:{id:string;label:string}[];value:string;onChange:(id:string)=>void;label:string;className?:string;children?:ReactNode}) {return <TabsPrimitive.Root value={value} onValueChange={onChange} className={cn('v-tabs',className)}><TabsPrimitive.List aria-label={label} className="v-tab-list">{items.map(item=><TabsPrimitive.Trigger key={item.id} value={item.id} className="v-tab">{item.label}</TabsPrimitive.Trigger>)}</TabsPrimitive.List>{children!==undefined&&<TabsPrimitive.Content value={value} className="v-tab-panel">{children}</TabsPrimitive.Content>}</TabsPrimitive.Root>;}
export function EmptyState({title,description,action,className}: {title:string;description?:ReactNode;action?:ReactNode;className?:string}) {return <div className={cn('v-empty',className)}><CircleHelp aria-hidden="true"/><h3>{title}</h3>{description&&<p>{description}</p>}{action}</div>;}
export function Modal({open,title,onClose,children,description}: {open:boolean;title:string;onClose:()=>void;children:ReactNode;description?:string}) {return <Dialog.Root open={open} onOpenChange={value=>{if(!value)onClose();}}><Dialog.Portal><Dialog.Overlay className="v-dialog-overlay"/><Dialog.Content className="v-dialog-content" aria-describedby={description?undefined:undefined}><header className="v-dialog-heading"><Dialog.Title>{title}</Dialog.Title><Dialog.Close asChild><Button variant="ghost" size="icon" aria-label={`Close ${title}`}><X/></Button></Dialog.Close></header>{description?<Dialog.Description>{description}</Dialog.Description>:<Dialog.Description className="v-sr-only">Evidence and details</Dialog.Description>}<div className="v-dialog-body">{children}</div></Dialog.Content></Dialog.Portal></Dialog.Root>;}
export function VideoTile({camera,clip,onOpen}: {camera:Camera;clip?:Clip;onOpen?:(id:string)=>void}) {const url=clip?.clip_url||camera.clip_url;const thumb=clip?.thumbnail_url||camera.thumbnail_url;return <article className="v-video-tile"><div className="v-media-frame">{thumb?<img src={thumb} alt={`${camera.name} clip frame`}/>:<CameraIcon aria-hidden="true"/>}{url&&onOpen?<Button variant="secondary" className="v-media-open" aria-label={`Open ${camera.name} clip`} onClick={()=>onOpen(clip?.id||camera.id)}><Play aria-hidden="true"/>Open clip</Button>:<span className="v-media-empty">No clip available</span>}</div><div className="v-video-caption"><strong>{camera.name}</strong><span>{clip?.source_label||camera.source_label}</span></div></article>;}
export function ClipCard({clip,onOpen}: {clip:Clip;onOpen:(id:string)=>void}) {return <button type="button" className="v-clip-card" onClick={()=>onOpen(clip.id)}><div className="v-media-frame">{clip.thumbnail_url?<img src={clip.thumbnail_url} alt=""/>:<VideoOff aria-hidden="true"/>}<span className="v-clip-clock">{clip.clock}</span>{!clip.clip_url&&<span className="v-media-empty">Media unavailable</span>}</div><div className="v-clip-caption"><VerdictBadge verdict={clip.verdict}/><strong>{clip.title}</strong><span>{clip.source_label}</span></div></button>;}
