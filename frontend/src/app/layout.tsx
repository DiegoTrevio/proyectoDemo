import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentOS",
  description: "Enterprise AI Agent Orchestration Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="font-sans antialiased bg-bg-primary text-text-primary min-h-screen">
        <div className="flex flex-col min-h-screen">
          <Header />
          <main className="flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}

function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-bg-primary/80 backdrop-blur-xl">
      <div className="max-w-[1400px] mx-auto flex items-center justify-between h-14 px-6">
        <div className="flex items-center gap-8">
          <a href="/" className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-accent-blue flex items-center justify-center">
              <span className="text-white text-sm font-bold">A</span>
            </div>
            <span className="text-[15px] font-semibold tracking-tight">AgentOS</span>
          </a>
          <nav className="hidden md:flex items-center gap-1">
            {[
              { label: "Dashboard", href: "/" },
              { label: "Tasks", href: "/" },
              { label: "Agents", href: "/" },
              { label: "Settings", href: "/" },
            ].map((item) => (
              <a
                key={item.label}
                href={item.href}
                className="px-3 py-1.5 text-[13px] text-text-secondary hover:text-text-primary rounded-md hover:bg-bg-hover transition-colors"
              >
                {item.label}
              </a>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <div className="h-7 px-2.5 rounded-md bg-bg-tertiary border border-border text-[11px] text-text-tertiary flex items-center gap-1.5 font-mono">
            <span className="text-accent-green">●</span> Online
          </div>
        </div>
      </div>
    </header>
  );
}
