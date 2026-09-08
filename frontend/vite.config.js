import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
    base: process.env.VITE_PUBLIC_BASE ?? '/',
    plugins: [react()],
    test: {
        environment: 'jsdom',
        setupFiles: './src/test/setup.js',
    },
});
