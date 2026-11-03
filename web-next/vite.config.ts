import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({plugins:[react(),tailwindcss()],base:'/next/',server:{proxy:{'/api':'http://127.0.0.1:8000','/media':'http://127.0.0.1:8000'}},build:{sourcemap:true}});
