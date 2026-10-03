import { defineConfig, transformWithEsbuild } from 'vite';

export default defineConfig({
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