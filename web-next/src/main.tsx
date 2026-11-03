import React from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import './styles/tokens.css';
import './styles/base.css';
const client = new QueryClient();
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><main><h1>Vigil</h1><p>The React preview is being assembled.</p></main></QueryClientProvider></React.StrictMode>);
