import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";

// System font stack to avoid fetching Google Fonts at build (avoids SSL/certificate issues behind proxies)
const fontClass = "font-sans";

export const metadata: Metadata = {
  title: "Insider Dashboard",
  description: "SEC Form 4 insider trading data: top insiders, holdings, activity, transactions",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={fontClass}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
