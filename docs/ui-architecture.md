# Blee UI architecture

Blee has one React-owned application shell. Screen structure and bottom navigation live in `src/components/BleeApp.tsx`; native code provides capabilities and events but does not inject or mutate UI DOM.

## Primary screens

- Home — balance, primary actions and recent activity
- Nearby — discovered Blee peers
- Send — recipient, amount and payment review/send flow
- Activity — payment history and direction filters
- Profile — profile, wallet/network and application settings

Payment details and supporting flows are rendered from the same React shell rather than by native overlays, except for capability-specific native surfaces such as QR capture and Android permission dialogs.

## UI ownership rules

- React owns visible app navigation and product screens.
- Native plugins expose capabilities; they do not inject arbitrary controls into React screens.
- The bottom navigation must have a single owner.
- Home should remain a concise dashboard and should not inherit Activity-only controls.
- Send recipient QR scanning belongs only to the recipient field.
- Wallet addresses are canonical identifiers; display names/avatars are presentation metadata.
- Refresh should update state without destroying the unlocked session or reloading the whole WebView.

## Styling

Global styling lives in `app/globals.css`. Product UI changes should be made directly in tracked React/CSS source. Do not add source-rewrite scripts or MutationObserver-based UI patches.

## Native UX

Android-specific UX is appropriate where the platform capability is genuinely native, including Bluetooth/nearby permissions, notifications, biometrics and QR camera capture. Results return through the Capacitor bridge and are rendered by React.
