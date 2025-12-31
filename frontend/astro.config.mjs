import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import node from '@astrojs/node';

export default defineConfig({
  integrations: [tailwind()],
  output: 'server',
  adapter: node({
    mode: 'standalone',
  }),
  server: {
    port: 3000,
    host: true,
  },
  vite: {
    define: {
      'import.meta.env.PUBLIC_API_URL': JSON.stringify(process.env.PUBLIC_API_URL || 'http://localhost:8000'),
    },
  },
});
