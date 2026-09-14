import type { Metadata, Viewport } from 'next';
import '@fontsource-variable/plus-jakarta-sans';
import './globals.css';
import './wallet-home.css';
import './nearby-screen.css';
import './biometric-auth.css';
import './approved-wallet-ui.css';

export const metadata: Metadata = {
  title: 'Blee',
  description: 'Payments that keep moving, online or nearby.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#f5f5f2',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
