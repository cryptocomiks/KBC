import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, API calls are proxied to the FastAPI backend.
// In production (Vercel / Docker) the API is served on the same origin under /api.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
  build: {
    chunkSizeWarningLimit: 1500,
  },
});
