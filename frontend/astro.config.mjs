import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import node from '@astrojs/node';
import vercel from '@astrojs/vercel';

// Use Vercel adapter in production, Node adapter for local dev
const isVercel = process.env.VERCEL === '1';

export default defineConfig({
  integrations: [tailwind()],
  output: 'server',
  adapter: isVercel ? vercel() : node({ mode: 'standalone' }),
  server: {
    port: 4321,
    host: true,
  },
});
