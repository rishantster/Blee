# Blee architecture

## Application layer

Blee is a Next.js/React application exported as static web assets and hosted inside Capacitor on Android.

Primary source areas:

- `src/components/BleeApp.tsx` — primary product screens and navigation
- `src/components/BleeRuntime.tsx` — runtime bridge into the app shell
- `src/hooks/useBlee.ts` — application/runtime state and native event integration
- `src/lib/payments.ts` — payment orchestration
- `src/lib/atomicSigning.ts` — transaction authorization/signing helpers
- `src/lib/networkConfig.ts` — settlement network configuration
- `src/lib/persistence.ts` — web/native persistence helpers

## Native Android layer

The Android project is tracked directly under `android/`.

Important native components include:

- `MainActivity` — Capacitor activity and native plugin registration
- `BleeMeshService` — nearby transport service
- `BleeMeshDb` — durable local SQLite-backed mesh/payment state
- `BleeMeshPlugin` — Capacitor bridge for mesh/native operations
- `BleeStorePlugin` — native wallet/application storage bridge
- `BleeQrScannerPlugin` — native QR scanner bridge
- `BleeBiometricPlugin` — biometric bridge

Nearby communication is owned by the native service. The React layer consumes peer/payment state through Capacitor events and plugin calls rather than running a second independent transport stack.

## Payment model

Blee separates nearby delivery from settlement. The app can exchange signed payment payloads over nearby transport while durable local state records the payment lifecycle. Settlement logic lives in the TypeScript/native payment stack and the configured EVM network layer.

Payment authorization data must not be rewritten when display identity metadata changes. Names, avatars and saved-contact presentation are local/display metadata layered over wallet-canonical identities.

## Persistence

Durable state is native-first for Android. Payment/mesh identity data survives process restarts and does not depend on ephemeral React component state.

## Build architecture

The build is source-first:

1. `npm ci`
2. source contract verification
3. TypeScript check
4. Next.js static build
5. `npx cap sync android`
6. Gradle `assembleDebug`
7. APK validation/checksum

There is no bootstrap materialization stage and no source-rewrite patch chain in the active build.
