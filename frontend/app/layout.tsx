import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Softstudio",
  description: "Self-hosted image and video generation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
