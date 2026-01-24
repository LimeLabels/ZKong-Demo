// vite.config.ts
import { defineConfig } from "file:///Users/jaygadhia/Desktop/ESL%20Systems/ZKong-Demo/external-tool/node_modules/vite/dist/node/index.js";
import react from "file:///Users/jaygadhia/Desktop/ESL%20Systems/ZKong-Demo/external-tool/node_modules/@vitejs/plugin-react/dist/index.js";
var vite_config_default = defineConfig({
  plugins: [react()],
  server: {
    port: parseInt(process.env.PORT || "3000"),
    host: true,
    strictPort: true,
    // Proxy API calls to backend
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false
      },
      "/external": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false
      }
    }
  },
  preview: {
    port: parseInt(process.env.PORT || "3000"),
    host: true,
    strictPort: true,
    allowedHosts: [
      "external-time-based-tool-production.up.railway.app",
      ".railway.app",
      "localhost"
    ],
    proxy: {
      "/api": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false
      },
      "/external": {
        target: process.env.BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
        secure: false
      }
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvVXNlcnMvamF5Z2FkaGlhL0Rlc2t0b3AvRVNMIFN5c3RlbXMvWktvbmctRGVtby9leHRlcm5hbC10b29sXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCIvVXNlcnMvamF5Z2FkaGlhL0Rlc2t0b3AvRVNMIFN5c3RlbXMvWktvbmctRGVtby9leHRlcm5hbC10b29sL3ZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9Vc2Vycy9qYXlnYWRoaWEvRGVza3RvcC9FU0wlMjBTeXN0ZW1zL1pLb25nLURlbW8vZXh0ZXJuYWwtdG9vbC92aXRlLmNvbmZpZy50c1wiO2ltcG9ydCB7IGRlZmluZUNvbmZpZyB9IGZyb20gXCJ2aXRlXCI7XG5pbXBvcnQgcmVhY3QgZnJvbSBcIkB2aXRlanMvcGx1Z2luLXJlYWN0XCI7XG5cbi8vIGh0dHBzOi8vdml0ZWpzLmRldi9jb25maWcvXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbcmVhY3QoKV0sXG4gIHNlcnZlcjoge1xuICAgIHBvcnQ6IHBhcnNlSW50KHByb2Nlc3MuZW52LlBPUlQgfHwgXCIzMDAwXCIpLFxuICAgIGhvc3Q6IHRydWUsXG4gICAgc3RyaWN0UG9ydDogdHJ1ZSxcbiAgICAvLyBQcm94eSBBUEkgY2FsbHMgdG8gYmFja2VuZFxuICAgIHByb3h5OiB7XG4gICAgICBcIi9hcGlcIjoge1xuICAgICAgICB0YXJnZXQ6IHByb2Nlc3MuZW52LkJBQ0tFTkRfVVJMIHx8IFwiaHR0cDovL2xvY2FsaG9zdDo4MDAwXCIsXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZSxcbiAgICAgICAgc2VjdXJlOiBmYWxzZSxcbiAgICAgIH0sXG4gICAgICBcIi9leHRlcm5hbFwiOiB7XG4gICAgICAgIHRhcmdldDogcHJvY2Vzcy5lbnYuQkFDS0VORF9VUkwgfHwgXCJodHRwOi8vbG9jYWxob3N0OjgwMDBcIixcbiAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxuICAgICAgICBzZWN1cmU6IGZhbHNlLFxuICAgICAgfSxcbiAgICB9LFxuICB9LFxuICBwcmV2aWV3OiB7XG4gICAgcG9ydDogcGFyc2VJbnQocHJvY2Vzcy5lbnYuUE9SVCB8fCBcIjMwMDBcIiksXG4gICAgaG9zdDogdHJ1ZSxcbiAgICBzdHJpY3RQb3J0OiB0cnVlLFxuICAgIGFsbG93ZWRIb3N0czogW1xuICAgICAgXCJleHRlcm5hbC10aW1lLWJhc2VkLXRvb2wtcHJvZHVjdGlvbi51cC5yYWlsd2F5LmFwcFwiLFxuICAgICAgXCIucmFpbHdheS5hcHBcIixcbiAgICAgIFwibG9jYWxob3N0XCIsXG4gICAgXSxcbiAgICBwcm94eToge1xuICAgICAgXCIvYXBpXCI6IHtcbiAgICAgICAgdGFyZ2V0OiBwcm9jZXNzLmVudi5CQUNLRU5EX1VSTCB8fCBcImh0dHA6Ly9sb2NhbGhvc3Q6ODAwMFwiLFxuICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXG4gICAgICAgIHNlY3VyZTogZmFsc2UsXG4gICAgICB9LFxuICAgICAgXCIvZXh0ZXJuYWxcIjoge1xuICAgICAgICB0YXJnZXQ6IHByb2Nlc3MuZW52LkJBQ0tFTkRfVVJMIHx8IFwiaHR0cDovL2xvY2FsaG9zdDo4MDAwXCIsXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZSxcbiAgICAgICAgc2VjdXJlOiBmYWxzZSxcbiAgICAgIH0sXG4gICAgfSxcbiAgfSxcbn0pO1xuXG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQTJXLFNBQVMsb0JBQW9CO0FBQ3hZLE9BQU8sV0FBVztBQUdsQixJQUFPLHNCQUFRLGFBQWE7QUFBQSxFQUMxQixTQUFTLENBQUMsTUFBTSxDQUFDO0FBQUEsRUFDakIsUUFBUTtBQUFBLElBQ04sTUFBTSxTQUFTLFFBQVEsSUFBSSxRQUFRLE1BQU07QUFBQSxJQUN6QyxNQUFNO0FBQUEsSUFDTixZQUFZO0FBQUE7QUFBQSxJQUVaLE9BQU87QUFBQSxNQUNMLFFBQVE7QUFBQSxRQUNOLFFBQVEsUUFBUSxJQUFJLGVBQWU7QUFBQSxRQUNuQyxjQUFjO0FBQUEsUUFDZCxRQUFRO0FBQUEsTUFDVjtBQUFBLE1BQ0EsYUFBYTtBQUFBLFFBQ1gsUUFBUSxRQUFRLElBQUksZUFBZTtBQUFBLFFBQ25DLGNBQWM7QUFBQSxRQUNkLFFBQVE7QUFBQSxNQUNWO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFBQSxFQUNBLFNBQVM7QUFBQSxJQUNQLE1BQU0sU0FBUyxRQUFRLElBQUksUUFBUSxNQUFNO0FBQUEsSUFDekMsTUFBTTtBQUFBLElBQ04sWUFBWTtBQUFBLElBQ1osY0FBYztBQUFBLE1BQ1o7QUFBQSxNQUNBO0FBQUEsTUFDQTtBQUFBLElBQ0Y7QUFBQSxJQUNBLE9BQU87QUFBQSxNQUNMLFFBQVE7QUFBQSxRQUNOLFFBQVEsUUFBUSxJQUFJLGVBQWU7QUFBQSxRQUNuQyxjQUFjO0FBQUEsUUFDZCxRQUFRO0FBQUEsTUFDVjtBQUFBLE1BQ0EsYUFBYTtBQUFBLFFBQ1gsUUFBUSxRQUFRLElBQUksZUFBZTtBQUFBLFFBQ25DLGNBQWM7QUFBQSxRQUNkLFFBQVE7QUFBQSxNQUNWO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFDRixDQUFDOyIsCiAgIm5hbWVzIjogW10KfQo=
