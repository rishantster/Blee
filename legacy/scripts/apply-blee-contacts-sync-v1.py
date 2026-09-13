#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts activity sync: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    db_path = locate("BleeMeshDb.java")
    plugin_path = locate("BleeMeshPlugin.java")
    db = db_path.read_text()
    plugin = plugin_path.read_text()

    if "BLEE_CONTACT_ACTIVITY_SYNC_V1" not in db:
        if "BLEE_LOCAL_CONTACTS_V1" not in db or "BLEE_ACTIVITY_IDENTITY_BACKFILL_V2" not in db:
            fail("contacts + Activity identity stages must run first")
        old = '''        db().insertWithOnConflict("contacts", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        return contact(normalized);'''
        new = '''        db().insertWithOnConflict("contacts", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        // BLEE_CONTACT_ACTIVITY_SYNC_V1
        // A locally chosen contact name/avatar is display metadata only. Reuse
        // the existing Activity backfill path; signed payment authorization is
        // never modified.
        backfillPaymentIdentity(normalized, name, photo);
        return contact(normalized);'''
        if old not in db:
            fail("saveContact persistence anchor missing")
        db = db.replace(old, new, 1)
        db_path.write_text(db)

    # Once a user saves a local alias, future profile syncs from the remote phone
    # must not overwrite that local display choice inside Activity.
    db = db_path.read_text()
    if "BLEE_CONTACT_ALIAS_PRECEDENCE_V1" not in db:
        old = '''            backfillPaymentIdentity(normalized, cleanName, cleanAvatarValue);'''
        new = '''            // BLEE_CONTACT_ALIAS_PRECEDENCE_V1
            JSONObject localContact = contact(normalized);
            if (localContact != null) {
                String localName = localContact.optString("displayName", "").trim();
                String localAvatar = localContact.optString("avatar", "").trim();
                if (!localName.isEmpty()) cleanName = localName;
                String savedAvatar = cleanAvatar(localAvatar);
                if (savedAvatar != null) cleanAvatarValue = savedAvatar;
            }
            backfillPaymentIdentity(normalized, cleanName, cleanAvatarValue);'''
        if old not in db:
            fail("peer identity Activity backfill anchor missing")
        db = db.replace(old, new, 1)
        db_path.write_text(db)

    plugin = plugin_path.read_text()
    if "BLEE_CONTACT_ACTIVITY_WAKE_V1" not in plugin:
        if "BLEE_CONTACTS_PLUGIN_V1" not in plugin:
            fail("contacts plugin stage must run first")
        old = '''            JSObject result = new JSObject();
            result.put("contact", saved);
            call.resolve(result);'''
        new = '''            JSObject result = new JSObject();
            result.put("contact", saved);
            // BLEE_CONTACT_ACTIVITY_WAKE_V1
            Intent refresh = new Intent(BleeMeshService.ACTION_LEDGER_CHANGED);
            refresh.setPackage(getContext().getPackageName());
            refresh.putExtra(BleeMeshService.EXTRA_PAYMENT_ID, "");
            refresh.putExtra(BleeMeshService.EXTRA_EVENT_TYPE, "CONTACT_UPDATED");
            getContext().sendBroadcast(refresh);
            call.resolve(result);'''
        if old not in plugin:
            fail("saveContact plugin response anchor missing")
        plugin = plugin.replace(old, new, 1)
        plugin_path.write_text(plugin)

    db = db_path.read_text()
    plugin = plugin_path.read_text()
    for marker in (
        "BLEE_CONTACT_ACTIVITY_SYNC_V1",
        "backfillPaymentIdentity(normalized, name, photo)",
        "BLEE_CONTACT_ALIAS_PRECEDENCE_V1",
        "JSONObject localContact = contact(normalized)",
    ):
        if marker not in db:
            fail(f"DB missing {marker}")
    for marker in ("BLEE_CONTACT_ACTIVITY_WAKE_V1", "CONTACT_UPDATED"):
        if marker not in plugin:
            fail(f"plugin missing {marker}")
    print("VERIFIED: saved contact alias/avatar stays authoritative in Activity without touching signed payment data")


if __name__ == "__main__":
    main()
