import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api → backend so the frontend never needs CORS in dev
// and never hard-codes a backend host.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
