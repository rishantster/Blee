# Blee

Blee is a nearby payments app built around Bluetooth-based peer discovery, durable local state, and USDC settlement on the configured EVM settlement network.

The repository is source-first: the files under `app/`, `src/`, `plugins/`, and `android/` are the code that gets built. There are no bootstrap archives or patch chains in the active project.

## Repository

```text
app/                 Next.js application shell and global styles
src/                 React UI, runtime, payment and wallet logic
plugins/             Local Capacitor plugins
android/             Android project and native Blee implementation
public/              Static app assets
assets/brand/        Brand assets
docs/                Architecture and repository documentation
scripts/             Build and source verification scripts
.github/workflows/   CI
```

Historical archive/patch builds are preserved only on `archive/*` branches and are not part of the active build.

## Requirements

- Node.js 22+
- Java 21
- Android SDK
- macOS, Linux, or another environment capable of running the Android Gradle toolchain

On macOS, Java 21 can be installed with:

```bash
brew install openjdk@21
```

## Install and verify

```bash
git clone https://github.com/rishantster/Blee.git
cd Blee
npm ci
npm run verify
npm run check
```

## Run the web UI

```bash
npm run dev
```

## Build the Android APK

The Android project is checked into Git. Do not run `cap add android`.

```bash
npm run android:build
```

The builder performs a clean dependency install, source verification, TypeScript check, Next.js static build, Capacitor sync, Gradle assembly, APK validation and SHA-256 generation.

Output:

```text
dist/Blee-2.7.0.apk
dist/Blee-2.7.0.apk.sha256
```

To sync web assets/native plugin metadata without assembling the APK:

```bash
npm ci
npm run android:sync
```

To install a debug-signed build on a connected Android device:

```bash
adb install -r dist/Blee-2.7.0.apk
```

If multiple devices are connected:

```bash
adb devices
adb -s <SERIAL> install -r dist/Blee-2.7.0.apk
```

## Release identity

Current source version:

```text
package version: 2.7.0
Android versionCode: 17
Android versionName: 2.7.0
```

This repository currently produces a directly installable debug-signed APK. Public app-store release signing is a separate release process.

## Documentation

- `docs/architecture.md` — application/native architecture
- `docs/ui-architecture.md` — UI ownership and screen structure
- `docs/repository.md` — source-control and build conventions
- `docs/source-provenance.md` — migration from the historical archive/patch pipeline
