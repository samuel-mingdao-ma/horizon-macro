import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HORIZON | Macro Risk Observatory",
  description: "Read the cycle. Price the risk. A reproducible US macro observatory with recession risk, historical validation, and interactive bond stress tests.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
