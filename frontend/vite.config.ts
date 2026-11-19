import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // 用根相对路径而不是 fileURLToPath：少一个 Node 类型依赖
    alias: { "@": "/src" },
  },
  server: {
    port: 5173,
    // 前端只调 /api，由 Vite 代理到后端，避免开发期 CORS 与硬编码主机名
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
