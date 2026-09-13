# Repository structure

Blee uses a source-first repository. The checked-in application and Android source are authoritative.

## Authoritative source

- `app/` — Next.js application shell and global CSS
- `src/` — React screens, runtime state, wallet/payment logic and TypeScript libraries
- `plugins/` — local Capacitor plugins used by the app
- `android/` — Android project and native transport/persistence code
- `public/` — static runtime assets
- `assets/brand/` — brand assets

A clean build must never reconstruct these directories from an archive or mutate them through a versioned patch chain.

## Build path

There is one supported Android build entrypoint:

```bash
npm run android:build
```

This calls `scripts/build-android.sh`. It verifies the tracked source, builds the Next.js static export, runs `npx cap sync android`, assembles the Android debug APK, validates it and writes a checksum.

The Android project is already tracked. Do not use `npx cap add android`.

## Generated files

The following are generated and must remain untracked:

- `node_modules/`
- `.next/`
- `out/`
- `dist/`
- Android Gradle build directories
- `android/local.properties`
- `android/app/src/main/assets/public/`
- generated Capacitor metadata in `android/app/src/main/assets/`

## Historical code

The previous archive-and-patch build system is preserved in Git history and dedicated `archive/*` branches. It is not an input to the active build and should not be reintroduced into `main`.

Experimental relay work is also archived separately rather than mixed into the direct nearby-payment production path.

## Versioning

The current aligned version contract is:

```text
package.json: 2.7.0
Android versionCode: 17
Android versionName: 2.7.0
APK: dist/Blee-2.7.0.apk
```

When releasing a new version, update the package version, Android versionCode/versionName, build artifact name, README and CI together in one change.

## Branch discipline

`main` is the active source branch. New product work should branch from `main` and return through a focused pull request. Avoid long-lived branches that duplicate the same fix under multiple names.
