import type { NextConfig } from "next";

// Static export: served by `repopilot serve` locally, or as the public demo (NEXT_PUBLIC_DEMO_MODE=1).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // Next 16 option: stops `next dev` from writing an AGENTS.md into the project.
  agentRules: false,
};

export default nextConfig;
