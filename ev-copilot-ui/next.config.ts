import path from "node:path";

import type { NextConfig } from "next";

// This app is self-contained: pin the workspace root to this folder so file tracing and
// Turbopack never pick up lockfiles from parent directories.
const projectRoot = path.resolve(__dirname);

// Standalone output produces a self-contained server (server.js + minimal node_modules)
// that the Dockerfile copies into the runtime image (App Runner, port 8000).
const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: projectRoot,
  turbopack: { root: projectRoot },
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
