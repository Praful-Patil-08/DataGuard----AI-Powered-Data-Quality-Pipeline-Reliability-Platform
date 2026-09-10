import "./globals.css";
import { Navbar } from "@/components/Navbar";

export const metadata = {
  title: "DataGuard | AI-Powered Data Reliability Platform",
  description: "Detect schema drift, prevent pipeline failures, and reason over data quality with AI.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100 min-h-screen flex flex-col antialiased">
        <Navbar />
        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
        <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500">
          DataGuard Reliability Platform • Engineered with Next.js, FastAPI & OpenAI
        </footer>
      </body>
    </html>
  );
}
