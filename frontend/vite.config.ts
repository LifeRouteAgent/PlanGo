import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Vite 开发阶段把 /trip、/export 和 /health 代理到 FastAPI。
// 这样前端代码只需要调用相对路径，部署时也方便挂到同一个域名下。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: "::",
    port: 5173,
    allowedHosts: "all",
    proxy: {
      "/trip": "http://127.0.0.1:8000",
      "/export": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000"
    }
  }
});
