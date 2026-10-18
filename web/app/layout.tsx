import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RepoPilot — private, history-aware code review",
  description:
    "RepoPilot reads your repository's history on open models you run yourself, greys out mechanical edits and points at the lines that need a human.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
