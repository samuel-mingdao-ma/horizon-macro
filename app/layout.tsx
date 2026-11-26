import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HORIZON | Recession Alarm Audit",
  description: "A recession alarm audit: credit-conditioned risk, the cost of false warnings, and prospective monthly forecast receipts.",
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
