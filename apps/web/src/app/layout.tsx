import "./globals.css";
import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import { MockProvider } from "@/components/MockProvider";

export const metadata: Metadata = {
  title: "ThirdEye · operator console",
  description:
    "Vision models run inside this browser. Frames never leave your home network.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="bg-maroon-950">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=JetBrains+Mono:wght@400;500;600&display=swap"
        />
      </head>
      <body className="min-h-screen bg-maroon-950 text-cream-50 antialiased">
        <MockProvider>
          <Nav />
          <main className="relative mx-auto max-w-[1280px] px-7 pb-24 pt-8">
            {children}
          </main>
        </MockProvider>
      </body>
    </html>
  );
}
