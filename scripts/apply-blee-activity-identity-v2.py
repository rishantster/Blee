#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee activity identity v2: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    if "BLEE_ACTIVITY_IDENTITY_BACKFILL_V2" in text:
        print("VERIFIED: Activity identity backfill already installed")
        return
    if "BLEE_PEER_IDENTITY_MERGE_V1" not in text:
        fail("wallet-canonical peer identity stage must run first")

    insert_line = '            db().insertWithOnConflict("peer_identities", null, cv, SQLiteDatabase.CONFLICT_REPLACE);'
    replacement = insert_line + '\n            backfillPaymentIdentity(normalized, cleanName, cleanAvatarValue);'
    if insert_line not in text:
        fail("peer identity insert anchor missing")
    text = text.replace(insert_line, replacement, 1)

    anchor = "    synchronized JSONObject peerIdentity(String wallet) {"
    helper = r'''    // BLEE_ACTIVITY_IDENTITY_BACKFILL_V2
    // Payment authorization/signature data is untouched. This only adds display
    // metadata to the local projection so Activity can immediately replace a raw
    // wallet label with the resolved peer name/avatar.
    private void backfillPaymentIdentity(String wallet, String displayName, String avatar) {
        if (wallet == null || wallet.isEmpty()) return;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        List<String[]> updates = new ArrayList<String[]>();
        try (Cursor c = db().query(
            "payments", new String[] { "payment_key", "payload" },
            null, null, null, null, "updated_at DESC"
        )) {
            while (c.moveToNext()) {
                String key = c.getString(0);
                String raw = c.getString(1);
                try {
                    JSONObject payment = new JSONObject(raw);
                    if (!paymentReferencesWallet(payment, normalized)) continue;
                    boolean changed = false;
                    String cleanName = displayName == null ? "" : displayName.trim();
                    if (!cleanName.isEmpty()) {
                        if (!cleanName.equals(payment.optString("counterpartyName", ""))) { payment.put("counterpartyName", cleanName); changed = true; }
                        payment.put("peerName", cleanName);
                        payment.put("contactName", cleanName);
                    }
                    if (avatar != null && !avatar.isEmpty()) {
                        if (!avatar.equals(payment.optString("counterpartyAvatar", ""))) { payment.put("counterpartyAvatar", avatar); changed = true; }
                        payment.put("peerAvatar", avatar);
                        payment.put("contactAvatar", avatar);
                    }
                    payment.put("counterpartyWallet", normalized);
                    JSONObject profile = payment.optJSONObject("counterpartyProfile");
                    if (profile == null) profile = new JSONObject();
                    profile.put("wallet", normalized);
                    if (!cleanName.isEmpty()) profile.put("displayName", cleanName);
                    if (avatar != null && !avatar.isEmpty()) profile.put("avatar", avatar);
                    payment.put("counterpartyProfile", profile);
                    if (changed) updates.add(new String[] { key, payment.toString() });
                } catch (Throwable ignored) {}
            }
        } catch (Throwable ignored) {}
        for (String[] update : updates) {
            ContentValues values = new ContentValues();
            values.put("payload", update[1]);
            values.put("updated_at", System.currentTimeMillis());
            db().update("payments", values, "payment_key=?", new String[] { update[0] });
        }
    }

    private static boolean paymentReferencesWallet(JSONObject payment, String wallet) {
        if (payment == null || wallet == null) return false;
        for (String key : new String[] { "sender", "receiver", "from", "to", "counterparty", "counterpartyWallet" }) {
            if (wallet.equalsIgnoreCase(payment.optString(key, ""))) return true;
        }
        JSONObject auth = authorization(payment);
        if (auth != null) {
            if (wallet.equalsIgnoreCase(auth.optString("from", ""))) return true;
            if (wallet.equalsIgnoreCase(auth.optString("to", ""))) return true;
        }
        return false;
    }

'''
    if anchor not in text:
        fail("peerIdentity helper anchor missing")
    text = text.replace(anchor, helper + anchor, 1)
    path.write_text(text)

    generated = path.read_text()
    for marker in ("BLEE_ACTIVITY_IDENTITY_BACKFILL_V2", "backfillPaymentIdentity", "counterpartyName", "counterpartyAvatar"):
        if marker not in generated:
            fail(f"missing {marker}")
    print("VERIFIED: late peer identity backfills Activity name/avatar without touching payment authorization")


if __name__ == "__main__":
    main()
