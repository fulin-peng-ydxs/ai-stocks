import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
var dependencyPatchDirectory = fileURLToPath(new URL('./patches/', import.meta.url));
var dependencyPatchFingerprint = createHash('sha256');
var dependencyPatchFiles = readdirSync(dependencyPatchDirectory)
    .filter(function (name) { return name.endsWith('.patch'); })
    .sort();
for (var _i = 0, dependencyPatchFiles_1 = dependencyPatchFiles; _i < dependencyPatchFiles_1.length; _i++) {
    var file = dependencyPatchFiles_1[_i];
    dependencyPatchFingerprint.update(file);
    dependencyPatchFingerprint.update(readFileSync(new URL("./patches/".concat(file), import.meta.url)));
}
// 开发期把 /api 转发到 FastAPI（SDD §13.2）
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
    // Vite 的依赖预构建哈希默认不读 patch-package 内容；指纹变化时必须换新浏览器依赖 URL。
    optimizeDeps: {
        esbuildOptions: {
            define: {
                __APP_DEPENDENCY_PATCH_FINGERPRINT__: JSON.stringify(dependencyPatchFingerprint.digest('hex')),
            },
        },
    },
    server: {
        host: '0.0.0.0', // 监听所有网卡：本机 127.0.0.1 与局域网 IP 均可访问（与后端 0.0.0.0 一致）
        port: 5173,
        // Codex、编辑器等工具可能通过原子替换写文件，macOS 原生事件偶发漏报；轮询保证 HMR 稳定触发。
        watch: {
            usePolling: true,
            interval: 200,
        },
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
    // vite preview（服务构建产物）不复用 server.proxy，需单独声明，使 /api 仍转发到后端。
    preview: {
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:8000',
                changeOrigin: true,
            },
        },
    },
});
