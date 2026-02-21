import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { getLocale } from "next-intl/server";
import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: {
    default: "Instaroom — Your Instagram, Your 3D Room",
    template: "%s | Instaroom",
  },
  description:
    "Transform your Instagram aesthetic into a unique 3D room you can explore",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "https://instaroom.xyz",
  ),
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await getLocale();

  return (
    <html lang={locale} className="dark" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
