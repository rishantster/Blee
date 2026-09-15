export const SOLANA_ACTIVITY_CHANGED_EVENT = 'blee:solana-activity-changed';

/**
 * Presentation-only signal emitted strictly after durable SOL inbox/outbox
 * persistence. It never carries transaction bytes, never settles anything and
 * never owns user-visible notifications.
 */
export function signalSolanaActivityChanged(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(SOLANA_ACTIVITY_CHANGED_EVENT));
}
