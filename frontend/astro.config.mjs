import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import node from '@astrojs/node';

export default defineConfig({
  integrations: [tailwind()],
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  server: {
    port: parseInt(process.env.PORT || '4321'),
    host: true,
  },
});
