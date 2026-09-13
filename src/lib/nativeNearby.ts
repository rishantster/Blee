import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';

export type TransportPeer = { id: string; rssi?: number };
export type PacketEvent = { peerId: string; data: string };

interface BleeNearbyPlugin {
  startMesh(): Promise<{ started: boolean }>;
  stopMesh(): Promise<void>;
  send(options: { data: string }): Promise<{ recipients: number }>;
  getPeers(): Promise<{ peers: TransportPeer[] }>;
  addListener(eventName: 'peerSeen', listener: (event: TransportPeer) => void): Promise<PluginListenerHandle>;
  addListener(eventName: 'packet', listener: (event: PacketEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: 'state', listener: (event: { state: string }) => void): Promise<PluginListenerHandle>;
}

const BleeNearby = registerPlugin<BleeNearbyPlugin>('BleeNearby');

export function nativeNearbyAvailable(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.isPluginAvailable('BleeNearby');
}

export function nativePlatform(): string {
  return Capacitor.getPlatform();
}

export { BleeNearby };
