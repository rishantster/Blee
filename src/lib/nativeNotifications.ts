import { Capacitor, registerPlugin } from '@capacitor/core';

interface BleeNotificationsPlugin {
  received(options: { paymentId: string; amount: string; counterparty?: string }): Promise<void>;
  delivered(options: { paymentId: string }): Promise<void>;
}

const BleeNotifications = registerPlugin<BleeNotificationsPlugin>('BleeNotifications');

export async function notifyPaymentReceived(
  paymentId: string,
  amount: string,
  counterparty?: string,
): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  await BleeNotifications.received({ paymentId, amount, counterparty });
}

export async function notifyPaymentDelivered(paymentId: string): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  await BleeNotifications.delivered({ paymentId });
}
