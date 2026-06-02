import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const backendTarget = process.env.VITE_BACKEND_PROXY || "http://127.0.0.1:8000";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": {
                target: backendTarget,
                changeOrigin: true
            },
            "/trip": {
                target: backendTarget,
                changeOrigin: true
            },
            "/export": {
                target: backendTarget,
                changeOrigin: true
            }
        }
    },
    build: {
        outDir: "dist",
        sourcemap: true
    }
});
