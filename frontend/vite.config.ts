import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  // https in development too: Stripe only redirects back to https URLs after the Stripe App is installed. The
  // certificate is self-signed, so the browser asks once to trust it.
  plugins: [react(), basicSsl()],
  // One .env at the repo root for the backend and frontend; only VITE_ variables reach the browser.
  envDir: '..',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
