export const SOLANA_ACTIVITY_CHANGED_EVENT = 'blee:solana-activity-changed';
export type SolanaActivityChangeSource = 'mesh' | 'settlement';

/**
 * Presentation-only signal emitted strictly after durable SOL state persistence.
 * It never carries transaction bytes, never owns user-visible notifications and
 * lets the settlement worker ignore its own journal writes to avoid feedback loops.
 */
export function signalSolanaActivityChanged(source: SolanaActivityChangeSource = 'mesh'): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(SOLANA_ACTIVITY_CHANGED_EVENT, { detail: { source } }));
}
