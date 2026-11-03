import React from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {HashRouter} from 'react-router-dom';
import {VigilApp} from './app';
import './styles/tokens.css';
import './styles/base.css';
const client = new QueryClient({defaultOptions:{queries:{retry:false,refetchOnWindowFocus:false,staleTime:30_000}}});
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><HashRouter><VigilApp/></HashRouter></QueryClientProvider></React.StrictMode>);
