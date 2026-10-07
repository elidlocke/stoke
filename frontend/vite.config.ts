import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // One .env at the repo root for the backend and frontend; only VITE_ variables reach the browser.
  envDir: '..',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
