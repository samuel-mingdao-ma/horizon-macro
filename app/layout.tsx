import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HORIZON | Macro Risk Research",
  description: "A self-updating macro research desk: early-warning audits, conditional credit triggers, rates stress tests and prospective forecast receipts.",
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
