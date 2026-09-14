#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

PROFILE="android/app/src/main/java/com/blee/payments/BleeProfileIdentityTransport.java"
PLUGIN="android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java"
SERVICE="android/app/src/main/java/com/blee/payments/BleeMeshService.java"
VIEW="src/hooks/useBleeView.ts"
APP="src/components/BleeApp.tsx"

[ -f "$PROFILE" ] || fail "offline profile identity transport missing"
[ -f "$PLUGIN" ] || fail "BleeMesh plugin missing"
[ -f "$SERVICE" ] || fail "native mesh service missing"

# Profile metadata must stay a separate, direct-only, signed presentation packet.
grep -q 'static final String TYPE = "PROFILE_IDENTITY"' "$PROFILE" || fail "profile packet type missing"
grep -q 'packet.put("hopLimit", 0)' "$PROFILE" || fail "profile packets must remain direct-only"
grep -q 'packet.put("destinationWallet", "")' "$PROFILE" || fail "profile packets must not masquerade as financial destination traffic"
grep -q 'BleeDeviceIdentity.sign(signingString(packet))' "$PROFILE" || fail "profile packets are not device-signed"
grep -q 'packet.optInt("hopLimit", -1) != 0' "$PROFILE" || fail "receiver does not enforce direct-only profile packets"
grep -q 'packet.optLong("expiresAt", 0L) <= now' "$PROFILE" || fail "expired profile packets are not rejected"
grep -q 'MAX_AVATAR_CHARS = 24_000' "$PROFILE" || fail "nearby avatar size bound changed"
grep -q 'hasFinancialOutbox' "$PROFILE" || fail "profile traffic no longer yields to payment traffic"
grep -q 'if (previous == null) continue' "$PROFILE" || fail "profile metadata can be applied before canonical peer resolution"
grep -q 'storedRemoteVersion' "$PROFILE" || fail "stale profile rollback protection missing"
grep -q 'clear.putNull("avatar")' "$PROFILE" || fail "profile photo removal tombstone is not applied"
grep -q 'expires_at>? AND copy_budget>0' "$PROFILE" || fail "expired/exhausted profile outbox entries can block refresh"

# This class must never become a second settlement/payment engine.
if grep -Eq 'PAYMENT_ENVELOPE|SETTLEMENT_RECEIPT|settlement_jobs|courier_envelopes|BleePaymentNotifier|HttpURLConnection|https?://' "$PROFILE"; then
  fail "profile identity transport contains financial, courier, notification or network logic"
fi

# Native plugin owns background profile pumping and enriches every peer snapshot.
grep -q 'BleeProfileIdentityTransport.syncLocalProfilePacket' "$PLUGIN" || fail "native profile packet is not synchronized"
grep -q 'BleeProfileIdentityTransport.processIncoming' "$PLUGIN" || fail "received profile packets are not consumed"
grep -q 'BleeProfileIdentityTransport.enrichPeer' "$PLUGIN" || fail "native peer snapshots are not enriched with profile metadata"
grep -q 'scheduleWithFixedDelay' "$PLUGIN" || fail "background profile worker missing"

# The existing mesh frame budget must safely contain the compressed avatar packet.
grep -q 'MAX_PACKET_BYTES = 48 \* 1024' "$SERVICE" || fail "native mesh packet budget no longer covers profile avatar frames"

# Web profile edits must reach native SQLite, including explicit photo removal.
grep -q "setPersistentValue('profile.alias', core.alias)" "$VIEW" || fail "profile name is not mirrored to native persistence"
grep -q "setPersistentValue('profile.avatar', core.profilePhoto || '')" "$VIEW" || fail "profile avatar/tombstone is not mirrored to native persistence"
grep -q 'const avatar = typeof peer?.avatar' "$VIEW" || fail "live native peer avatar is not projected into the UI identity model"

# Every approved Nearby presentation surface must use the resolved peer identity.
grep -q 'app.identityFor(featuredPeer.address)?.avatar' "$APP" || fail "Home Nearby preview does not use resolved peer avatar"
grep -q 'app.identityFor(peer.address)?.avatar' "$APP" || fail "Nearby radar/list does not use resolved peer avatar"
grep -q 'src={app.profilePhoto}' "$APP" || fail "local profile avatar is not rendered in approved wallet UI"

printf 'VERIFIED: Nearby profile photos are signed, direct-only, stale-safe and projected from native mesh into approved UI\n'
