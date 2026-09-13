#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts v1: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def patch_db() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    if "BLEE_LOCAL_CONTACTS_V1" in text:
        return

    schema_anchor = '        db.execSQL("CREATE TABLE IF NOT EXISTS peer_identities (wallet_address TEXT PRIMARY KEY NOT NULL,display_name TEXT,avatar TEXT,device_id TEXT,updated_at INTEGER NOT NULL,payload TEXT NOT NULL)");'
    if schema_anchor not in text:
        fail("peer identity schema anchor missing")
    schema = schema_anchor + '\n        // BLEE_LOCAL_CONTACTS_V1\n        db.execSQL("CREATE TABLE IF NOT EXISTS contacts (wallet_address TEXT PRIMARY KEY NOT NULL,display_name TEXT NOT NULL,avatar TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,last_interacted_at INTEGER NOT NULL DEFAULT 0)");\n        db.execSQL("CREATE INDEX IF NOT EXISTS contacts_updated_idx ON contacts(updated_at DESC)");'
    text = text.replace(schema_anchor, schema, 1)

    anchor = "    synchronized String getKv(String key) {"
    if anchor not in text:
        fail("contacts helper insertion anchor missing")

    helpers = r'''    // BLEE_LOCAL_CONTACTS_V1
    synchronized JSONObject saveContact(String wallet, String displayName, String avatar) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return null;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        String own = activeWallet();
        if (own != null && own.equalsIgnoreCase(normalized)) return null;

        String name = displayName == null ? "" : displayName.trim();
        String photo = cleanAvatar(avatar);
        long createdAt = System.currentTimeMillis();
        long lastInteractedAt = 0L;

        try (Cursor c = db().query(
            "contacts", new String[] { "display_name", "avatar", "created_at", "last_interacted_at" },
            "wallet_address=?", new String[] { normalized }, null, null, null, "1"
        )) {
            if (c.moveToFirst()) {
                if (name.isEmpty()) name = c.isNull(0) ? "" : c.getString(0);
                if (photo == null) photo = cleanAvatar(c.isNull(1) ? null : c.getString(1));
                createdAt = c.getLong(2);
                lastInteractedAt = c.getLong(3);
            }
        } catch (Throwable ignored) {}

        JSONObject known = peerIdentity(normalized);
        if (known != null) {
            if (name.isEmpty()) name = known.optString("displayName", "").trim();
            if (photo == null) photo = cleanAvatar(known.optString("avatar", ""));
        }
        if (name.length() > 64) name = name.substring(0, 64);
        if (name.isEmpty()) name = normalized.substring(0, 6) + "…" + normalized.substring(normalized.length() - 4);

        long now = System.currentTimeMillis();
        ContentValues cv = new ContentValues();
        cv.put("wallet_address", normalized);
        cv.put("display_name", name);
        if (photo != null) cv.put("avatar", photo); else cv.putNull("avatar");
        cv.put("created_at", createdAt);
        cv.put("updated_at", now);
        cv.put("last_interacted_at", lastInteractedAt);
        db().insertWithOnConflict("contacts", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        return contact(normalized);
    }

    synchronized boolean deleteContact(String wallet) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return false;
        return db().delete("contacts", "wallet_address=?", new String[] { wallet.toLowerCase(Locale.ROOT) }) > 0;
    }

    synchronized JSONObject contact(String wallet) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return null;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        try (Cursor c = db().query(
            "contacts", new String[] { "display_name", "avatar", "created_at", "updated_at", "last_interacted_at" },
            "wallet_address=?", new String[] { normalized }, null, null, null, "1"
        )) {
            if (!c.moveToFirst()) return null;
            JSONObject out = new JSONObject();
            out.put("wallet", normalized);
            out.put("displayName", c.isNull(0) ? "" : c.getString(0));
            if (!c.isNull(1)) out.put("avatar", c.getString(1));
            out.put("createdAt", c.getLong(2));
            out.put("updatedAt", c.getLong(3));
            out.put("lastInteractedAt", c.getLong(4));
            out.put("saved", true);
            return out;
        } catch (Throwable ignored) {
            return null;
        }
    }

    synchronized List<JSONObject> listContacts() {
        List<JSONObject> rows = new ArrayList<JSONObject>();
        try (Cursor c = db().query(
            "contacts", new String[] { "wallet_address", "display_name", "avatar", "created_at", "updated_at", "last_interacted_at" },
            null, null, null, null, "display_name COLLATE NOCASE ASC, updated_at DESC"
        )) {
            while (c.moveToNext()) {
                JSONObject out = new JSONObject();
                out.put("wallet", c.getString(0));
                out.put("displayName", c.getString(1));
                if (!c.isNull(2)) out.put("avatar", c.getString(2));
                out.put("createdAt", c.getLong(3));
                out.put("updatedAt", c.getLong(4));
                out.put("lastInteractedAt", c.getLong(5));
                out.put("saved", true);
                rows.add(out);
            }
        } catch (Throwable ignored) {}
        return rows;
    }

    private static JSONObject candidateByWallet(List<JSONObject> rows, String wallet) {
        if (wallet == null) return null;
        for (JSONObject row : rows) {
            if (wallet.equalsIgnoreCase(row.optString("wallet", ""))) return row;
        }
        return null;
    }

    private void mergeContactCandidate(List<JSONObject> rows, String wallet, String displayName, String avatar, long interactedAt) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        String own = activeWallet();
        if (own != null && own.equalsIgnoreCase(normalized)) return;
        try {
            JSONObject row = candidateByWallet(rows, normalized);
            if (row == null) {
                row = new JSONObject();
                row.put("wallet", normalized);
                rows.add(row);
            }
            String name = displayName == null ? "" : displayName.trim();
            if (!name.isEmpty() && row.optString("displayName", "").isEmpty()) row.put("displayName", name);
            String photo = cleanAvatar(avatar);
            if (photo != null && row.optString("avatar", "").isEmpty()) row.put("avatar", photo);
            if (interactedAt > row.optLong("lastInteractedAt", 0L)) row.put("lastInteractedAt", interactedAt);
            row.put("saved", contact(normalized) != null);
        } catch (Throwable ignored) {}
    }

    synchronized List<JSONObject> contactCandidates() {
        List<JSONObject> rows = new ArrayList<JSONObject>();
        try (Cursor c = db().query(
            "peer_identities", new String[] { "wallet_address", "display_name", "avatar", "updated_at" },
            null, null, null, null, "updated_at DESC"
        )) {
            while (c.moveToNext()) {
                mergeContactCandidate(
                    rows,
                    c.getString(0),
                    c.isNull(1) ? "" : c.getString(1),
                    c.isNull(2) ? null : c.getString(2),
                    c.getLong(3)
                );
            }
        } catch (Throwable ignored) {}

        try (Cursor c = db().query(
            "payments", new String[] { "payload", "updated_at" },
            null, null, null, null, "updated_at DESC"
        )) {
            while (c.moveToNext()) {
                try {
                    JSONObject payment = new JSONObject(c.getString(0));
                    long at = c.getLong(1);
                    String own = activeWallet();
                    JSONObject auth = authorization(payment);
                    String[] wallets = new String[] {
                        payment.optString("counterpartyWallet", ""),
                        payment.optString("counterparty", ""),
                        payment.optString("sender", ""),
                        payment.optString("receiver", ""),
                        payment.optString("from", ""),
                        payment.optString("to", ""),
                        auth == null ? "" : auth.optString("from", ""),
                        auth == null ? "" : auth.optString("to", "")
                    };
                    for (String wallet : wallets) {
                        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) continue;
                        if (own != null && own.equalsIgnoreCase(wallet)) continue;
                        String name = firstNonEmpty(
                            payment.optString("counterpartyName", ""),
                            payment.optString("peerName", ""),
                            payment.optString("contactName", ""),
                            payment.optString("senderName", ""),
                            payment.optString("receiverName", "")
                        );
                        String photo = firstNonEmpty(
                            payment.optString("counterpartyAvatar", ""),
                            payment.optString("peerAvatar", ""),
                            payment.optString("contactAvatar", ""),
                            payment.optString("senderAvatar", ""),
                            payment.optString("receiverAvatar", "")
                        );
                        mergeContactCandidate(rows, wallet, name, photo, at);
                    }
                } catch (Throwable ignored) {}
            }
        } catch (Throwable ignored) {}

        // Saved contacts always remain available even if their last payment has
        // aged out of the visible activity projection.
        for (JSONObject saved : listContacts()) {
            mergeContactCandidate(
                rows,
                saved.optString("wallet", ""),
                saved.optString("displayName", ""),
                saved.optString("avatar", ""),
                saved.optLong("lastInteractedAt", saved.optLong("updatedAt", 0L))
            );
        }

        // Small lists are expected; insertion sort avoids extra comparator/imports.
        for (int i = 1; i < rows.size(); i++) {
            JSONObject key = rows.get(i);
            long keyAt = key.optLong("lastInteractedAt", 0L);
            int j = i - 1;
            while (j >= 0 && rows.get(j).optLong("lastInteractedAt", 0L) < keyAt) {
                rows.set(j + 1, rows.get(j));
                j--;
            }
            rows.set(j + 1, key);
        }
        return rows;
    }

'''
    text = text.replace(anchor, helpers + anchor, 1)
    path.write_text(text)


def patch_plugin() -> None:
    path = locate("BleeMeshPlugin.java")
    text = path.read_text()
    if "BLEE_CONTACTS_PLUGIN_V1" in text:
        return

    anchor = "    @PluginMethod\n    public void status(PluginCall call) {"
    if anchor not in text:
        fail("BleeMeshPlugin status() anchor missing")

    methods = r'''    // BLEE_CONTACTS_PLUGIN_V1
    @PluginMethod
    public void listContacts(PluginCall call) {
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            JSArray contacts = new JSArray();
            for (org.json.JSONObject item : db.listContacts()) contacts.put(item);
            JSObject result = new JSObject();
            result.put("contacts", contacts);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load Blee contacts: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    @PluginMethod
    public void contactCandidates(PluginCall call) {
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            JSArray contacts = new JSArray();
            for (org.json.JSONObject item : db.contactCandidates()) contacts.put(item);
            JSObject result = new JSObject();
            result.put("contacts", contacts);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load contact candidates: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    @PluginMethod
    public void saveContact(PluginCall call) {
        String wallet = call.getString("wallet", "");
        String displayName = call.getString("displayName", "");
        String avatar = call.getString("avatar", "");
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            org.json.JSONObject saved = db.saveContact(wallet, displayName, avatar);
            if (saved == null) {
                call.reject("Invalid Blee contact");
                return;
            }
            JSObject result = new JSObject();
            result.put("contact", saved);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to save Blee contact: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    @PluginMethod
    public void deleteContact(PluginCall call) {
        String wallet = call.getString("wallet", "");
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            JSObject result = new JSObject();
            result.put("deleted", db.deleteContact(wallet));
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to remove Blee contact: " + error.getMessage());
        } finally {
            db.close();
        }
    }

'''
    text = text.replace(anchor, methods + anchor, 1)
    path.write_text(text)


def patch_runtime_ui() -> None:
    runtime = ROOT / "src/components/BleeRuntime.tsx"
    css = ROOT / "app/globals.css"
    if not runtime.is_file() or not css.is_file():
        fail("materialized runtime/CSS missing")

    text = runtime.read_text()
    if "BLEE_CONTACTS_ACTIVITY_UI_V1" not in text:
        anchor = "const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');"
        if anchor not in text:
            fail("BleeMesh runtime registration anchor missing")

        ui = r'''

// BLEE_CONTACTS_ACTIVITY_UI_V1
// Contacts are local-only durable SQLite records exposed through BleeMesh.
// The Activity enhancement is deliberately DOM-scoped so it survives the
// generated React UI without changing signing/payment state.
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !(window as any).__bleeContactsUiInstalled) {
  (window as any).__bleeContactsUiInstalled = true;
  const NativeContacts = BleeMesh as any;
  let savedContacts: any[] = [];
  let contactCandidates: any[] = [];
  let selectedWallet = '';
  let mutationQueued = false;

  const wallet = (value: unknown) => String(value || '').trim().toLowerCase();
  const isWallet = (value: string) => /^0x[0-9a-f]{40}$/.test(value);
  const shortWallet = (value: string) => value && value.length >= 10 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
  const contactName = (contact: any) => String(contact?.displayName || contact?.name || '').trim();
  const contactAvatar = (contact: any) => String(contact?.avatar || '').trim();
  const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' } as any)[ch]);

  const refreshContacts = async () => {
    try {
      const response = await NativeContacts.listContacts?.();
      savedContacts = Array.isArray(response?.contacts) ? response.contacts : [];
    } catch { savedContacts = []; }
    try {
      const response = await NativeContacts.contactCandidates?.();
      contactCandidates = Array.isArray(response?.contacts) ? response.contacts : [];
    } catch { contactCandidates = savedContacts.slice(); }
    syncActivityUi();
  };

  const visible = (element: HTMLElement | null) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };

  const findExactText = (text: string) => {
    const target = text.trim().toLowerCase();
    const nodes = Array.from(document.querySelectorAll<HTMLElement>('h1,h2,h3,h4,[role="heading"],label,span,p,div'));
    return nodes.find((node) => visible(node) && (node.textContent || '').trim().toLowerCase() === target) || null;
  };

  const findActivityScreen = () => {
    const heading = findExactText('Activity');
    if (!heading) return null;
    return (heading.closest('[data-screen],.screen,.app-screen,.blee-screen,.page,main,section,article') as HTMLElement | null)
      || heading.parentElement?.parentElement
      || heading.parentElement;
  };

  const closeSheet = () => document.getElementById('blee-contact-sheet')?.remove();

  const sheetBase = (title: string) => {
    closeSheet();
    const sheet = document.createElement('div');
    sheet.id = 'blee-contact-sheet';
    sheet.innerHTML = `<div class="blee-contact-backdrop"></div><div class="blee-contact-panel"><div class="blee-contact-grabber"></div><div class="blee-contact-head"><strong>${escapeHtml(title)}</strong><button type="button" class="blee-contact-close" aria-label="Close contacts">×</button></div><div class="blee-contact-body"></div></div>`;
    document.body.appendChild(sheet);
    sheet.querySelector('.blee-contact-backdrop')?.addEventListener('click', closeSheet);
    sheet.querySelector('.blee-contact-close')?.addEventListener('click', closeSheet);
    return sheet;
  };

  const avatarMarkup = (contact: any) => {
    const avatar = contactAvatar(contact);
    const name = contactName(contact) || shortWallet(wallet(contact?.wallet));
    const initial = escapeHtml((name || '?').slice(0, 1).toUpperCase());
    if (avatar && (avatar.startsWith('data:image/') || avatar.startsWith('https://') || avatar.startsWith('http://'))) {
      return `<span class="blee-contact-avatar"><img src="${escapeHtml(avatar)}" alt="" /></span>`;
    }
    return `<span class="blee-contact-avatar blee-contact-initial">${initial}</span>`;
  };

  const editContact = (candidate: any) => {
    const targetWallet = wallet(candidate?.wallet);
    if (!isWallet(targetWallet)) return;
    const sheet = sheetBase(savedContacts.some((c) => wallet(c.wallet) === targetWallet) ? 'Edit contact' : 'Save contact');
    const body = sheet.querySelector('.blee-contact-body') as HTMLElement;
    const current = savedContacts.find((c) => wallet(c.wallet) === targetWallet) || candidate;
    body.innerHTML = `
      <div class="blee-contact-editor-person">${avatarMarkup(current)}<div><strong>${escapeHtml(contactName(current) || 'Blee contact')}</strong><span>${escapeHtml(shortWallet(targetWallet))}</span></div></div>
      <label class="blee-contact-label">Name<input id="blee-contact-name-input" maxlength="64" autocomplete="off" value="${escapeHtml(contactName(current))}" /></label>
      <button type="button" class="blee-contact-primary" id="blee-contact-save-action">Save contact</button>
      ${savedContacts.some((c) => wallet(c.wallet) === targetWallet) ? '<button type="button" class="blee-contact-danger" id="blee-contact-delete-action">Remove contact</button>' : ''}
    `;
    const input = body.querySelector('#blee-contact-name-input') as HTMLInputElement | null;
    window.setTimeout(() => input?.focus(), 80);
    body.querySelector('#blee-contact-save-action')?.addEventListener('click', async () => {
      const displayName = String(input?.value || '').trim();
      if (!displayName) { input?.focus(); return; }
      try {
        await NativeContacts.saveContact?.({ wallet: targetWallet, displayName, avatar: contactAvatar(current) });
        closeSheet();
        await refreshContacts();
      } catch {}
    });
    body.querySelector('#blee-contact-delete-action')?.addEventListener('click', async () => {
      try {
        await NativeContacts.deleteContact?.({ wallet: targetWallet });
        if (selectedWallet === targetWallet) selectedWallet = '';
        closeSheet();
        await refreshContacts();
      } catch {}
    });
  };

  const openContacts = () => {
    const sheet = sheetBase('Contacts');
    const body = sheet.querySelector('.blee-contact-body') as HTMLElement;
    const rows = contactCandidates.filter((candidate) => isWallet(wallet(candidate?.wallet)));
    if (!rows.length) {
      body.innerHTML = '<div class="blee-contact-empty"><strong>No people yet</strong><span>People you send to or receive from will appear here so you can save them.</span></div>';
      return;
    }
    const savedWallets = new Set(savedContacts.map((contact) => wallet(contact?.wallet)));
    body.innerHTML = `<div class="blee-contact-list">${rows.map((candidate) => {
      const w = wallet(candidate?.wallet);
      const saved = savedWallets.has(w);
      const name = contactName(candidate) || shortWallet(w);
      return `<button type="button" class="blee-contact-row" data-contact-wallet="${escapeHtml(w)}">${avatarMarkup(candidate)}<span class="blee-contact-copy"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(shortWallet(w))}</small></span><span class="blee-contact-row-action">${saved ? 'Edit' : 'Save'}</span></button>`;
    }).join('')}</div>`;
    body.querySelectorAll<HTMLElement>('[data-contact-wallet]').forEach((row) => {
      row.addEventListener('click', () => {
        const w = wallet(row.dataset.contactWallet);
        const candidate = rows.find((item) => wallet(item?.wallet) === w);
        if (candidate) editContact(candidate);
      });
    });
  };

  const openFilter = () => {
    const sheet = sheetBase('Filter activity');
    const body = sheet.querySelector('.blee-contact-body') as HTMLElement;
    const allRow = `<button type="button" class="blee-contact-row${selectedWallet ? '' : ' selected'}" data-filter-wallet=""><span class="blee-contact-avatar blee-contact-initial">∞</span><span class="blee-contact-copy"><strong>All activity</strong><small>Every payment</small></span><span class="blee-contact-check">${selectedWallet ? '' : '✓'}</span></button>`;
    const contactRows = savedContacts.map((contact) => {
      const w = wallet(contact?.wallet);
      const selected = selectedWallet === w;
      return `<button type="button" class="blee-contact-row${selected ? ' selected' : ''}" data-filter-wallet="${escapeHtml(w)}">${avatarMarkup(contact)}<span class="blee-contact-copy"><strong>${escapeHtml(contactName(contact) || shortWallet(w))}</strong><small>${escapeHtml(shortWallet(w))}</small></span><span class="blee-contact-check">${selected ? '✓' : ''}</span></button>`;
    }).join('');
    body.innerHTML = `<div class="blee-contact-list">${allRow}${contactRows}</div>${savedContacts.length ? '' : '<div class="blee-contact-empty compact"><span>Save someone as a contact first, then you can filter Activity by them.</span></div>'}`;
    body.querySelectorAll<HTMLElement>('[data-filter-wallet]').forEach((row) => {
      row.addEventListener('click', () => {
        selectedWallet = wallet(row.dataset.filterWallet);
        closeSheet();
        applyActivityFilter();
        syncActivityUi();
      });
    });
  };

  const activityRows = (screen: HTMLElement) => {
    const selectors = [
      '[data-payment-id]', '[data-activity-item]', '.activity-item', '.activity-row',
      '.transaction-item', '.transaction-row', '.payment-item', '.payment-row', 'li'
    ];
    const set = new Set<HTMLElement>();
    selectors.forEach((selector) => screen.querySelectorAll<HTMLElement>(selector).forEach((row) => set.add(row)));
    return Array.from(set).filter((row) => {
      if (row.closest('.blee-activity-contact-tools') || row.closest('#blee-contact-sheet')) return false;
      const text = (row.textContent || '').toLowerCase();
      return /usdc|sent|received|receive|pending|settled|delivered|failed|payment/.test(text) || /\b\d+(?:\.\d+)?\b/.test(text);
    });
  };

  const applyActivityFilter = () => {
    const screen = findActivityScreen();
    if (!screen) return;
    const previouslyFiltered = screen.querySelectorAll<HTMLElement>('[data-blee-contact-filtered="1"]');
    previouslyFiltered.forEach((row) => { row.hidden = false; row.removeAttribute('data-blee-contact-filtered'); });
    if (!selectedWallet) return;

    const selected = savedContacts.find((contact) => wallet(contact?.wallet) === selectedWallet);
    if (!selected) { selectedWallet = ''; return; }
    const name = contactName(selected).toLowerCase();
    const w = selectedWallet.toLowerCase();
    const needles = [w, shortWallet(w).toLowerCase(), name].filter(Boolean);
    activityRows(screen).forEach((row) => {
      const text = (row.textContent || '').toLowerCase();
      const matches = needles.some((needle) => text.includes(needle));
      if (!matches) {
        row.hidden = true;
        row.setAttribute('data-blee-contact-filtered', '1');
      }
    });
  };

  const removeSendOverlap = () => {
    const recipient = findExactText('Recipient');
    if (!recipient) return;
    const amount = findExactText('Amount');
    const scope = (recipient.closest('label') || recipient.parentElement || recipient) as HTMLElement;
    let input = scope.querySelector('input') as HTMLInputElement | null;
    if (!input) {
      const parent = recipient.parentElement?.parentElement || recipient.parentElement;
      input = parent?.querySelector('input') || null;
    }
    if (!input || (amount && input.compareDocumentPosition(amount) & Node.DOCUMENT_POSITION_PRECEDING)) return;
    const shell = input.parentElement;
    if (!shell) return;
    shell.querySelectorAll<HTMLButtonElement>('button').forEach((button) => {
      if (button.classList.contains('blee-recipient-qr-icon') || button.getAttribute('aria-label')?.toLowerCase().includes('qr')) return;
      button.dataset.bleeHiddenSendIcon = '1';
      button.style.display = 'none';
    });
  };

  function syncActivityUi() {
    removeSendOverlap();
    const screen = findActivityScreen();
    if (!screen) return;
    const heading = Array.from(screen.querySelectorAll<HTMLElement>('h1,h2,h3,h4,[role="heading"]')).find((node) => (node.textContent || '').trim().toLowerCase() === 'activity');
    if (!heading) return;
    let tools = screen.querySelector('.blee-activity-contact-tools') as HTMLElement | null;
    if (!tools) {
      tools = document.createElement('div');
      tools.className = 'blee-activity-contact-tools';
      tools.innerHTML = '<button type="button" class="blee-activity-filter-button"><span class="blee-filter-label">All activity</span><span aria-hidden="true">⌄</span></button><button type="button" class="blee-activity-contacts-button">Contacts</button>';
      heading.insertAdjacentElement('afterend', tools);
      tools.querySelector('.blee-activity-filter-button')?.addEventListener('click', openFilter);
      tools.querySelector('.blee-activity-contacts-button')?.addEventListener('click', openContacts);
    }
    const selected = savedContacts.find((contact) => wallet(contact?.wallet) === selectedWallet);
    const label = tools.querySelector('.blee-filter-label');
    if (label) label.textContent = selected ? contactName(selected) || shortWallet(selectedWallet) : 'All activity';
    applyActivityFilter();
  }

  const observer = new MutationObserver(() => {
    if (mutationQueued) return;
    mutationQueued = true;
    window.requestAnimationFrame(() => {
      mutationQueued = false;
      syncActivityUi();
    });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener('click', () => window.setTimeout(syncActivityUi, 30), true);
  window.addEventListener('blee:refresh-complete', () => { void refreshContacts(); });
  window.addEventListener('blee:native-nearby', () => { void refreshContacts(); });
  window.setTimeout(() => { void refreshContacts(); syncActivityUi(); }, 160);
}
'''
        text = text.replace(anchor, anchor + ui, 1)
        runtime.write_text(text)

    css_text = css.read_text()
    if "BLEE_CONTACTS_ACTIVITY_CSS_V1" not in css_text:
        css_text += r'''

/* BLEE_CONTACTS_ACTIVITY_CSS_V1 */
/* Recipient owns one trailing action only: QR. Contacts live under Activity. */
.blee-recipient-input-shell > button:not(.blee-recipient-qr-icon) { display: none !important; }
.blee-recipient-input-shell .blee-recipient-qr-icon { z-index: 4; }

.blee-activity-contact-tools {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 10px 0 14px;
}
.blee-activity-contact-tools button {
  min-height: 38px;
  border: 1px solid rgba(17,17,17,.1);
  background: rgba(255,255,255,.78);
  color: #111;
  border-radius: 999px;
  padding: 0 13px;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  -webkit-tap-highlight-color: transparent;
}
.blee-activity-filter-button { display: inline-flex; align-items: center; gap: 8px; max-width: 62%; }
.blee-filter-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.blee-activity-contacts-button { margin-left: auto; }

#blee-contact-sheet { position: fixed; inset: 0; z-index: 11000; }
.blee-contact-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,.28); backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); }
.blee-contact-panel {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  max-height: min(78vh, 680px);
  overflow: hidden;
  border-radius: 26px 26px 0 0;
  background: #f8f8f6;
  box-shadow: 0 -20px 70px rgba(0,0,0,.2);
  padding: 8px 16px calc(18px + env(safe-area-inset-bottom, 0px));
  animation: blee-contact-sheet-in 240ms cubic-bezier(.2,.8,.2,1) both;
}
@keyframes blee-contact-sheet-in { from { transform: translateY(24px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
.blee-contact-grabber { width: 36px; height: 4px; border-radius: 999px; background: rgba(0,0,0,.18); margin: 2px auto 10px; }
.blee-contact-head { display: flex; align-items: center; min-height: 48px; padding: 0 2px 8px; }
.blee-contact-head strong { font-size: 20px; letter-spacing: -.02em; }
.blee-contact-close { margin-left: auto; width: 34px; height: 34px; border: 0; border-radius: 50%; background: rgba(0,0,0,.06); font-size: 23px; line-height: 1; }
.blee-contact-body { overflow-y: auto; max-height: calc(min(78vh, 680px) - 72px); padding-bottom: 8px; }
.blee-contact-list { display: grid; gap: 6px; }
.blee-contact-row {
  width: 100%;
  min-height: 62px;
  display: flex;
  align-items: center;
  gap: 11px;
  border: 0;
  border-radius: 18px;
  background: rgba(255,255,255,.82);
  padding: 9px 11px;
  color: #111;
  text-align: left;
  font: inherit;
}
.blee-contact-row.selected { background: #111; color: #fff; }
.blee-contact-avatar { width: 40px; height: 40px; flex: 0 0 40px; overflow: hidden; border-radius: 50%; display: grid; place-items: center; background: rgba(0,0,0,.07); font-size: 14px; font-weight: 750; }
.blee-contact-avatar img { width: 100%; height: 100%; object-fit: cover; }
.blee-contact-row.selected .blee-contact-avatar { background: rgba(255,255,255,.14); }
.blee-contact-copy { min-width: 0; display: grid; gap: 2px; flex: 1; }
.blee-contact-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.blee-contact-copy small { opacity: .56; font-size: 11px; }
.blee-contact-row-action,.blee-contact-check { margin-left: auto; font-size: 12px; font-weight: 700; opacity: .72; }
.blee-contact-editor-person { display: flex; align-items: center; gap: 12px; margin: 4px 2px 18px; }
.blee-contact-editor-person > div { display: grid; gap: 2px; }
.blee-contact-editor-person span:not(.blee-contact-avatar) { font-size: 12px; opacity: .55; }
.blee-contact-label { display: grid; gap: 7px; font-size: 12px; font-weight: 650; margin-bottom: 14px; }
.blee-contact-label input { width: 100%; height: 52px; border: 1px solid rgba(0,0,0,.11); border-radius: 16px; padding: 0 14px; background: #fff; color: #111; font: inherit; font-size: 16px; outline: none; }
.blee-contact-primary,.blee-contact-danger { width: 100%; min-height: 50px; border: 0; border-radius: 16px; font: inherit; font-weight: 720; }
.blee-contact-primary { background: #111; color: #fff; }
.blee-contact-danger { margin-top: 8px; background: rgba(0,0,0,.055); color: #111; }
.blee-contact-empty { min-height: 160px; display: grid; place-items: center; align-content: center; gap: 7px; text-align: center; padding: 24px; }
.blee-contact-empty strong { font-size: 16px; }
.blee-contact-empty span { max-width: 260px; opacity: .58; font-size: 13px; line-height: 1.45; }
.blee-contact-empty.compact { min-height: 90px; }
'''
        css.write_text(css_text)


def verify() -> None:
    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    css = (ROOT / "app/globals.css").read_text()

    for marker in (
        "BLEE_LOCAL_CONTACTS_V1",
        "CREATE TABLE IF NOT EXISTS contacts",
        "saveContact(String wallet",
        "listContacts()",
        "contactCandidates()",
        "payments",
        "peer_identities",
    ):
        if marker not in db:
            fail(f"DB missing {marker}")
    for marker in (
        "BLEE_CONTACTS_PLUGIN_V1",
        "listContacts(PluginCall call)",
        "contactCandidates(PluginCall call)",
        "saveContact(PluginCall call)",
        "deleteContact(PluginCall call)",
    ):
        if marker not in plugin:
            fail(f"plugin missing {marker}")
    for marker in (
        "BLEE_CONTACTS_ACTIVITY_UI_V1",
        "Filter activity",
        "Save contact",
        "removeSendOverlap",
        "data-blee-contact-filtered",
        "blee:refresh-complete",
    ):
        if marker not in runtime:
            fail(f"runtime missing {marker}")
    for marker in (
        "BLEE_CONTACTS_ACTIVITY_CSS_V1",
        ".blee-activity-contact-tools",
        "#blee-contact-sheet",
        ".blee-recipient-input-shell > button:not(.blee-recipient-qr-icon)",
    ):
        if marker not in css:
            fail(f"CSS missing {marker}")

    print("============================================================")
    print("VERIFIED: Blee local contacts v1")
    print("- contacts are persisted locally in SQLite, keyed by wallet")
    print("- payment history + discovered identities become saveable candidates")
    print("- Activity exposes Contacts and a saved-contact filter")
    print("- Send Recipient keeps only the QR action; overlapping contact button is removed")
    print("============================================================")


def main() -> None:
    patch_db()
    patch_plugin()
    patch_runtime_ui()
    verify()


if __name__ == "__main__":
    main()
