import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.blee.payments',
  appName: 'Blee',
  webDir: 'out',
  android: {
    backgroundColor: '#f4f4f2',
    allowMixedContent: false,
  },
};

export default config;
