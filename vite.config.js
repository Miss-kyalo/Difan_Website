import { defineConfig, transformWithEsbuild } from 'vite';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = fileURLToPath(new URL('.', import.meta.url));
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(rootDir, 'index.html'),
        tracking: resolve(rootDir, 'tracking.html'),
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  plugins: [
    {
      name: 'shipment-tracking-jsx',
      enforce: 'pre',
      async transform(source, id) {
        if (!id.split('?')[0].endsWith('/js/shipmentTracking.js')) return null;
        return transformWithEsbuild(source, id, { loader: 'jsx' });
      },
    },
  ],
});