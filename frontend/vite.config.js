import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
// 开发期把 /api 转发到 FastAPI（SDD §13.2）
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    server: {
        host: '0.0.0.0', // 监听所有网卡：本机 127.0.0.1 与局域网 IP 均可访问（与后端 0.0.0.0 一致）
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: 'dist',
    },
});
