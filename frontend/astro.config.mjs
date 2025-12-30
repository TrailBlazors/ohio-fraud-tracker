// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  // Output static HTML by default (can deploy anywhere)
  output: 'static',
  
  // Development server settings
  server: {
    port: 3000,
    host: true
  },
  
  // Build settings
  build: {
    // Generate clean URLs (/grants instead of /grants.html)
    format: 'directory'
  }
});
