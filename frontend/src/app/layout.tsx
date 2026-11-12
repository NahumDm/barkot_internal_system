import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AuthProvider } from "@/features/auth/auth-provider";
import { I18nProvider } from "@/lib/i18n/context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Barkot Bar & Restaurant",
  description: "Barkot internal business operations system",
};

/**
 * The document shell, and nothing else.
 *
 * `AuthProvider` sits here rather than inside the `(app)` group because the
 * sign-in page needs it too — after a successful sign-in it must be able to
 * record the user without a second request, and an already-signed-in visitor
 * landing on `/login` has to be recognisable as such.
 *
 * The application shell and the guard live in `(app)/layout.tsx` instead. Every
 * page that reaches the application is inside that group, so a new page is
 * protected by being placed there rather than by remembering to add a check.
 */
export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <I18nProvider><AuthProvider>{children}</AuthProvider></I18nProvider>
      </body>
    </html>
  );
}
