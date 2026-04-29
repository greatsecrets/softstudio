import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig = {
  turbopack: {
    root: __dirname,
  },
  allowedDevOrigins: ["*.trycloudflare.com", "*.cfargotunnel.com"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND}/api/:path*` },
      { source: "/assets/:path*", destination: `${BACKEND}/assets/:path*` },
    ];
  },
};

export default nextConfig;
