import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // static export -> served by the FastAPI backend (single deployable unit)
  output: "export",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
