import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forwards API calls from the dev server to the FastAPI backend.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
