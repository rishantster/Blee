#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"
CSS = ROOT / "app/globals.css"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts React v3: {message}")


def ensure_register_plugin(text: str) -> str:
    if re.search(r"\bregisterPlugin\b", text):
        return text
    match = re.search(r"import\s*\{(?P<body>[^}]*)\}\s*from\s*['\"]@capacitor/core['\"]\s*;?", text, re.S)
    if match:
        body = match.group("body").strip()
        replacement = match.group(0).replace(
            "{" + match.group("body") + "}",
            "{ " + body.rstrip() + (", " if body else "") + "registerPlugin }",
        )
        return text[: match.start()] + replacement + text[match.end() :]
    imports = list(re.finditer(r"(?m)^import\s.+?;\s*$", text))
    if not imports:
        fail("BleeApp import block missing")
    pos = imports[-1].end()
    return text[:pos] + "\nimport { registerPlugin } from '@capacitor/core';" + text[pos:]


def patch_app() -> None:
    if not APP.is_file():
        fail("materialized BleeApp.tsx missing")
    text = APP.read_text()
    if "BLEE_CONTACTS_REACT_V3" in text:
        verify_app(text)
        return

    text = ensure_register_plugin(text)

    backup_anchor = "type BackupMode = 'overview' | 'reveal' | 'import-key' | 'restore';"
    if backup_anchor not in text:
        fail("BackupMode anchor missing")
    type_block = r'''

// BLEE_CONTACTS_REACT_V3
// Contacts are a first-class React feature. No MutationObserver/DOM injection is
// used. Durable data lives in the native BleeMesh SQLite store.
type BleeContact = {
  wallet: string;
  displayName?: string;
  avatar?: string;
  saved?: boolean;
  lastInteractedAt?: number;
};
type ContactPanel = 'filter' | 'manage' | 'edit' | null;
interface BleeContactsPlugin {
  listContacts(): Promise<{ contacts?: BleeContact[] }>;
  contactCandidates(): Promise<{ contacts?: BleeContact[] }>;
  saveContact(options: { wallet: string; displayName: string; avatar?: string }): Promise<{ contact?: BleeContact }>;
  deleteContact(options: { wallet: string }): Promise<{ deleted?: boolean }>;
}
const BleeContacts = registerPlugin<BleeContactsPlugin>('BleeMesh');

function canonicalWallet(value?: string | null) {
  const raw = String(value || '').trim();
  return /^0x[0-9a-fA-F]{40}$/.test(raw) ? raw.toLowerCase() : raw;
}
'''
    text = text.replace(backup_anchor, backup_anchor + type_block, 1)

    short_old = """function short(value?: string | null) {
  if (!value) return '—';
  return `${value.slice(0, 6)}…${value.slice(-4)}`;
}"""
    short_new = """function short(value?: string | null) {
  if (!value) return '—';
  const stable = canonicalWallet(value);
  return `${stable.slice(0, 6)}…${stable.slice(-4)}`;
}"""
    if short_old not in text:
        fail("short wallet formatter anchor missing")
    text = text.replace(short_old, short_new, 1)

    state_anchor = "  const [activityFilter, setActivityFilter] = useState<'all' | 'sent' | 'received'>('all');"
    if state_anchor not in text:
        fail("Activity filter state anchor missing")
    states = r'''
  const [contactFilter, setContactFilter] = useState('');
  const [contacts, setContacts] = useState<BleeContact[]>([]);
  const [contactCandidates, setContactCandidates] = useState<BleeContact[]>([]);
  const [contactPanel, setContactPanel] = useState<ContactPanel>(null);
  const [editingContact, setEditingContact] = useState<BleeContact | null>(null);
  const [contactName, setContactName] = useState('');
  const [contactBusy, setContactBusy] = useState(false);
'''
    text = text.replace(state_anchor, state_anchor + states, 1)

    visible_anchor = "  const visiblePayments = useMemo(() => app.payments.filter((row) => row.direction !== 'relay'), [app.payments]);"
    if visible_anchor not in text:
        fail("visiblePayments anchor missing")
    helpers = r'''
  const refreshContacts = async () => {
    if (!app.account) {
      setContacts([]);
      setContactCandidates([]);
      setContactFilter('');
      return;
    }
    const [savedResult, candidateResult] = await Promise.all([
      BleeContacts.listContacts().catch(() => ({ contacts: [] as BleeContact[] })),
      BleeContacts.contactCandidates().catch(() => ({ contacts: [] as BleeContact[] })),
    ]);
    const saved = Array.isArray(savedResult?.contacts) ? savedResult.contacts : [];
    const candidates = Array.isArray(candidateResult?.contacts) ? candidateResult.contacts : [];
    setContacts(saved);
    setContactCandidates(candidates);
    if (contactFilter && !saved.some((item) => canonicalWallet(item.wallet) === contactFilter)) setContactFilter('');
  };

  useEffect(() => {
    if (!app.account) return;
    if (screen === 'activity' || screen === 'activity-detail') void refreshContacts();
  }, [screen, app.account?.address, app.payments.length, app.peers.length]);

  const contactFor = (wallet?: string | null) => {
    const normalized = canonicalWallet(wallet);
    return contacts.find((item) => canonicalWallet(item.wallet) === normalized);
  };

  const contactCandidateFor = (wallet?: string | null) => {
    const normalized = canonicalWallet(wallet);
    const identity = normalized ? app.identityFor(normalized) : undefined;
    return contactCandidates.find((item) => canonicalWallet(item.wallet) === normalized)
      || contactFor(normalized)
      || (normalized ? { wallet: normalized, displayName: identity?.alias, avatar: identity?.avatar } : undefined);
  };

  const openContactEditor = (candidate: BleeContact) => {
    const normalized = canonicalWallet(candidate.wallet);
    if (!/^0x[0-9a-f]{40}$/.test(normalized)) return;
    const saved = contactFor(normalized);
    const identity = app.identityFor(normalized);
    const next = { ...candidate, ...saved, wallet: normalized, avatar: saved?.avatar || candidate.avatar || identity?.avatar || '' };
    setEditingContact(next);
    setContactName(saved?.displayName || candidate.displayName || identity?.alias || '');
    setContactPanel('edit');
  };

  const saveEditingContact = async () => {
    if (!editingContact || contactBusy) return;
    const wallet = canonicalWallet(editingContact.wallet);
    const name = contactName.trim();
    if (!/^0x[0-9a-f]{40}$/.test(wallet) || !name) return;
    setContactBusy(true);
    try {
      await BleeContacts.saveContact({ wallet, displayName: name, avatar: editingContact.avatar || '' });
      await refreshContacts();
      setContactPanel('manage');
    } finally {
      setContactBusy(false);
    }
  };

  const deleteEditingContact = async () => {
    if (!editingContact || contactBusy) return;
    const wallet = canonicalWallet(editingContact.wallet);
    setContactBusy(true);
    try {
      await BleeContacts.deleteContact({ wallet });
      if (contactFilter === wallet) setContactFilter('');
      await refreshContacts();
      setContactPanel('manage');
    } finally {
      setContactBusy(false);
    }
  };

'''
    text = text.replace(visible_anchor, helpers + visible_anchor, 1)

    filtered_old = "  const filteredPayments = useMemo(() => visiblePayments.filter((row) => activityFilter === 'all' || (activityFilter === 'sent' ? row.direction === 'out' : row.direction === 'in')), [visiblePayments, activityFilter]);"
    filtered_new = """  const filteredPayments = useMemo(() => visiblePayments.filter((row) => {
    const directionMatches = activityFilter === 'all' || (activityFilter === 'sent' ? row.direction === 'out' : row.direction === 'in');
    const contactMatches = !contactFilter || canonicalWallet(row.counterparty) === contactFilter;
    return directionMatches && contactMatches;
  }), [visiblePayments, activityFilter, contactFilter]);"""
    if filtered_old not in text:
        fail("filteredPayments anchor missing")
    text = text.replace(filtered_old, filtered_new, 1)

    render_home_anchor = "  const renderHome = () => ("
    if render_home_anchor not in text:
        fail("renderHome anchor missing")
    sheet = r'''
  const selectedContact = contactFilter ? contactFor(contactFilter) : undefined;

  const renderContactSheet = () => {
    if (!contactPanel) return null;
    const close = () => { setContactPanel(null); setEditingContact(null); setContactName(''); };
    const savedWallets = new Set(contacts.map((item) => canonicalWallet(item.wallet)));
    const candidates = contactCandidates.filter((item) => /^0x[0-9a-f]{40}$/.test(canonicalWallet(item.wallet)));
    return (
      <div className="react-contact-sheet" role="dialog" aria-modal="true" aria-label={contactPanel === 'filter' ? 'Filter activity by contact' : contactPanel === 'manage' ? 'Manage contacts' : 'Edit contact'}>
        <button className="react-contact-backdrop" aria-label="Close" onClick={close}/>
        <section className="react-contact-panel">
          <div className="react-contact-grabber"/>
          <div className="react-contact-head">
            <strong>{contactPanel === 'filter' ? 'Filter by contact' : contactPanel === 'manage' ? 'Contacts' : (contactFor(editingContact?.wallet)?.displayName ? 'Edit contact' : 'Save contact')}</strong>
            <button className="icon-button ghost" onClick={close} aria-label="Close contacts"><Icon name="close"/></button>
          </div>
          {contactPanel === 'filter' && (
            <div className="react-contact-list">
              <button className={`react-contact-row ${!contactFilter ? 'selected' : ''}`} onClick={() => { setContactFilter(''); close(); }}>
                <span className="contact-all-avatar">∞</span>
                <span className="react-contact-copy"><strong>All activity</strong><small>Every payment</small></span>
                {!contactFilter && <Icon name="check" size={16}/>} 
              </button>
              {contacts.map((contact) => {
                const wallet = canonicalWallet(contact.wallet);
                const name = contact.displayName || short(wallet);
                return <button key={wallet} className={`react-contact-row ${contactFilter === wallet ? 'selected' : ''}`} onClick={() => { setContactFilter(wallet); close(); }}>
                  <PersonAvatar name={name} src={contact.avatar} size="sm"/>
                  <span className="react-contact-copy"><strong>{name}</strong><small>{short(wallet)}</small></span>
                  {contactFilter === wallet && <Icon name="check" size={16}/>} 
                </button>;
              })}
              {!contacts.length && <div className="react-contact-empty"><strong>No saved contacts yet</strong><span>Save someone you have paid or received from, then filter Activity by that person.</span></div>}
              <button className="secondary-button full" onClick={() => setContactPanel('manage')}>Manage contacts</button>
            </div>
          )}
          {contactPanel === 'manage' && (
            <div className="react-contact-list">
              {candidates.length ? candidates.map((candidate) => {
                const wallet = canonicalWallet(candidate.wallet);
                const saved = savedWallets.has(wallet);
                const identity = app.identityFor(wallet);
                const name = contactFor(wallet)?.displayName || candidate.displayName || identity?.alias || short(wallet);
                const avatar = contactFor(wallet)?.avatar || candidate.avatar || identity?.avatar;
                return <button key={wallet} className="react-contact-row" onClick={() => openContactEditor({ ...candidate, wallet, displayName: name, avatar })}>
                  <PersonAvatar name={name} src={avatar} size="sm"/>
                  <span className="react-contact-copy"><strong>{name}</strong><small>{short(wallet)}</small></span>
                  <small className="react-contact-action">{saved ? 'Edit' : 'Save'}</small>
                </button>;
              }) : <div className="react-contact-empty"><strong>No people yet</strong><span>People you send to, receive from, or discover nearby will appear here.</span></div>}
            </div>
          )}
          {contactPanel === 'edit' && editingContact && (
            <div className="react-contact-editor">
              <div className="react-contact-person">
                <PersonAvatar name={contactName || editingContact.displayName || short(editingContact.wallet)} src={editingContact.avatar} size="lg"/>
                <span className="react-contact-copy"><strong>{editingContact.displayName || app.identityFor(editingContact.wallet)?.alias || 'Blee contact'}</strong><small>{short(editingContact.wallet)}</small></span>
              </div>
              <label className="field-block"><span>Name</span><input value={contactName} maxLength={64} onChange={(event) => setContactName(event.target.value)} autoFocus/></label>
              <button className="primary-button" disabled={!contactName.trim() || contactBusy} onClick={() => void saveEditingContact()}>{contactBusy ? 'Saving…' : 'Save contact'}</button>
              {contactFor(editingContact.wallet) && <button className="text-action danger" disabled={contactBusy} onClick={() => void deleteEditingContact()}>Remove contact</button>}
            </div>
          )}
        </section>
      </div>
    );
  };

'''
    text = text.replace(render_home_anchor, sheet + render_home_anchor, 1)

    activity_old = """  const renderActivity = () => (
    <div className=\"screen-content\"><ScreenHeader title=\"Activity\" trailing={pendingPayments.length ? <span className=\"count-badge\">{pendingPayments.length}</span> : null}/>
      <div className=\"filter-tabs\" role=\"tablist\" aria-label=\"Activity filter\">
        <button className={activityFilter === 'all' ? 'active' : ''} onClick={() => setActivityFilter('all')}>All</button>
        <button className={activityFilter === 'sent' ? 'active' : ''} onClick={() => setActivityFilter('sent')}>Sent</button>
        <button className={activityFilter === 'received' ? 'active' : ''} onClick={() => setActivityFilter('received')}>Received</button>
      </div>
      {filteredPayments.length ? <div className=\"surface-list activity-list\">{filteredPayments.map((row) => <PaymentRow key={`${row.direction}:${row.id}`} row={row} identity={app.identityFor(row.counterparty)} onOpen={openPayment}/>)}</div> : <EmptyState icon=\"activity\" title={visiblePayments.length ? 'Nothing in this view' : 'No activity yet'} copy={visiblePayments.length ? 'Choose another activity filter.' : 'Settled, pending and nearby payments stay in the durable payment journal.'}/>} 
    </div>
  );"""
    if activity_old not in text:
        # Older UI bundle has no trailing whitespace before the final newline.
        activity_old = activity_old.replace("/>} \n", "/>}\n")
    if activity_old not in text:
        fail("renderActivity anchor missing")
    activity_new = """  const renderActivity = () => (
    <div className=\"screen-content\"><ScreenHeader title=\"Activity\" trailing={pendingPayments.length ? <span className=\"count-badge\">{pendingPayments.length}</span> : null}/>
      <div className=\"filter-tabs\" role=\"tablist\" aria-label=\"Activity filter\">
        <button className={activityFilter === 'all' ? 'active' : ''} onClick={() => setActivityFilter('all')}>All</button>
        <button className={activityFilter === 'sent' ? 'active' : ''} onClick={() => setActivityFilter('sent')}>Sent</button>
        <button className={activityFilter === 'received' ? 'active' : ''} onClick={() => setActivityFilter('received')}>Received</button>
      </div>
      <button className={`activity-contact-filter ${selectedContact ? 'active' : ''}`} onClick={() => { void refreshContacts(); setContactPanel('filter'); }}>
        <Icon name=\"person\" size={17}/><span>{selectedContact?.displayName || 'Filter by contact'}</span><Icon name=\"chevron\" size={15}/>
      </button>
      {filteredPayments.length ? <div className=\"surface-list activity-list\">{filteredPayments.map((row) => {
        const saved = contactFor(row.counterparty);
        const identity = app.identityFor(row.counterparty);
        return <PaymentRow key={`${row.direction}:${row.id}`} row={row} identity={saved ? { alias: saved.displayName || identity?.alias, avatar: saved.avatar || identity?.avatar } : identity} onOpen={openPayment}/>;
      })}</div> : <EmptyState icon=\"activity\" title={visiblePayments.length ? 'Nothing in this view' : 'No activity yet'} copy={visiblePayments.length ? 'Choose another activity filter.' : 'Settled, pending and nearby payments stay in the durable payment journal.'}/>} 
    </div>
  );"""
    text = text.replace(activity_old, activity_new, 1)

    detail_old = """  const renderActivityDetail = () => {
    if (!selectedPayment) return renderActivity();
    const incoming = selectedPayment.direction === 'in';
    const counterparty = selectedPayment.counterpartyAlias || app.identityFor(selectedPayment.counterparty)?.alias || short(selectedPayment.counterparty);
    return <div className=\"screen-content\"><ScreenHeader title=\"Payment details\" onBack={() => { setSelectedPayment(null); goBack('activity'); }}/><div className=\"detail-hero\"><PersonAvatar name={counterparty} src={app.identityFor(selectedPayment.counterparty)?.avatar} size=\"lg\"/>"""
    detail_new = """  const renderActivityDetail = () => {
    if (!selectedPayment) return renderActivity();
    const incoming = selectedPayment.direction === 'in';
    const savedContact = contactFor(selectedPayment.counterparty);
    const remoteIdentity = app.identityFor(selectedPayment.counterparty);
    const counterparty = savedContact?.displayName || selectedPayment.counterpartyAlias || remoteIdentity?.alias || short(selectedPayment.counterparty);
    const counterpartyAvatar = savedContact?.avatar || remoteIdentity?.avatar;
    return <div className=\"screen-content\"><ScreenHeader title=\"Payment details\" onBack={() => { setSelectedPayment(null); goBack('activity'); }}/><div className=\"detail-hero\"><PersonAvatar name={counterparty} src={counterpartyAvatar} size=\"lg\"/>"""
    if detail_old not in text:
        fail("Activity detail identity anchor missing")
    text = text.replace(detail_old, detail_new, 1)

    detail_tail = "</section>{selectedPayment.txHash && network.explorerUrl && <a className=\"secondary-button full\" href={`${network.explorerUrl}/tx/${selectedPayment.txHash}`} target=\"_blank\" rel=\"noreferrer\">View transaction <Icon name=\"external\"/></a>}</div>;"
    detail_tail_new = "</section><button className=\"secondary-button full contact-detail-action\" onClick={() => { const candidate = contactCandidateFor(selectedPayment.counterparty); if (candidate) openContactEditor(candidate); }}><Icon name=\"person\"/>{savedContact ? 'Edit contact' : 'Save contact'}</button>{selectedPayment.txHash && network.explorerUrl && <a className=\"secondary-button full\" href={`${network.explorerUrl}/tx/${selectedPayment.txHash}`} target=\"_blank\" rel=\"noreferrer\">View transaction <Icon name=\"external\"/></a>}</div>;"
    if detail_tail not in text:
        fail("Activity detail action anchor missing")
    text = text.replace(detail_tail, detail_tail_new, 1)

    root_old = """      {primary && <BottomNav active={activeTab} onChange={selectTab}/>} 
    </main>"""
    root_new = """      {primary && <BottomNav active={activeTab} onChange={selectTab}/>} 
      {renderContactSheet()}
    </main>"""
    if root_old not in text:
        fail("BottomNav root anchor missing")
    text = text.replace(root_old, root_new, 1)

    text = text.replace("Blee 2.5 · Mesh v2", "Blee 2.7 · Mesh v2")
    APP.write_text(text)
    verify_app(text)


def patch_css() -> None:
    if not CSS.is_file():
        fail("materialized globals.css missing")
    text = CSS.read_text()
    if "BLEE_CONTACTS_REACT_V3" in text:
        return
    text = text.rstrip() + r'''

/* BLEE_CONTACTS_REACT_V3 */
.activity-contact-filter {
  width: 100%;
  min-height: 44px;
  margin: 10px 0 14px;
  padding: 0 13px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid rgba(9,9,9,.10);
  border-radius: 14px;
  background: rgba(255,255,255,.72);
  color: #111;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  text-align: left;
}
.activity-contact-filter > span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-contact-filter.active { background: #111; color: #fff; border-color: #111; }
.react-contact-sheet { position: fixed; inset: 0; z-index: 12000; }
.react-contact-backdrop { position: absolute; inset: 0; width: 100%; border: 0; background: rgba(0,0,0,.28); backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); }
.react-contact-panel {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  max-height: min(78dvh, 680px);
  overflow: hidden;
  padding: 8px 16px calc(18px + env(safe-area-inset-bottom, 0px));
  border-radius: 26px 26px 0 0;
  background: #f8f8f6;
  box-shadow: 0 -20px 70px rgba(0,0,0,.18);
  animation: blee-contact-sheet-in 220ms cubic-bezier(.2,.8,.2,1) both;
}
@keyframes blee-contact-sheet-in { from { transform: translateY(24px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
.react-contact-grabber { width: 36px; height: 4px; margin: 2px auto 10px; border-radius: 999px; background: rgba(0,0,0,.16); }
.react-contact-head { min-height: 46px; padding-bottom: 8px; display: flex; align-items: center; gap: 12px; }
.react-contact-head > strong { flex: 1; font-size: 20px; letter-spacing: -.025em; }
.react-contact-list { max-height: calc(min(78dvh, 680px) - 70px); overflow-y: auto; display: grid; gap: 7px; padding-bottom: 8px; }
.react-contact-row {
  width: 100%;
  min-height: 62px;
  padding: 9px 11px;
  display: flex;
  align-items: center;
  gap: 11px;
  border: 0;
  border-radius: 17px;
  background: #fff;
  color: #111;
  text-align: left;
  font: inherit;
}
.react-contact-row.selected { background: #111; color: #fff; }
.react-contact-copy { min-width: 0; flex: 1; display: grid; gap: 2px; }
.react-contact-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.react-contact-copy small { opacity: .56; font-size: 11px; }
.react-contact-action { margin-left: auto; opacity: .62; font-weight: 700; }
.contact-all-avatar { width: 40px; height: 40px; flex: 0 0 40px; display: grid; place-items: center; border-radius: 50%; background: rgba(0,0,0,.06); font-size: 18px; }
.react-contact-row.selected .contact-all-avatar { background: rgba(255,255,255,.14); }
.react-contact-empty { min-height: 130px; padding: 22px; display: grid; place-items: center; align-content: center; gap: 6px; text-align: center; }
.react-contact-empty span { max-width: 270px; opacity: .58; font-size: 13px; line-height: 1.45; }
.react-contact-editor { display: grid; gap: 14px; padding-bottom: 8px; }
.react-contact-person { display: flex; align-items: center; gap: 12px; padding: 4px 2px 2px; }
.react-contact-person .react-contact-copy { flex: 1; }
.contact-detail-action { margin-top: 12px; gap: 8px; }
'''
    CSS.write_text(text + "\n")


def patch_version() -> None:
    package = ROOT / "package.json"
    if package.is_file():
        data = json.loads(package.read_text())
        data["version"] = "2.7.0"
        package.write_text(json.dumps(data, indent=2) + "\n")
    native = ROOT / "scripts/configure-native.mjs"
    if native.is_file():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 17", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.7.0"', text)
        native.write_text(text)


def verify_app(text: str | None = None) -> None:
    text = text if text is not None else APP.read_text()
    required = (
        "BLEE_CONTACTS_REACT_V3",
        "registerPlugin<BleeContactsPlugin>('BleeMesh')",
        "activity-contact-filter",
        "renderContactSheet()",
        "Save contact",
        "Manage contacts",
        "contactMatches = !contactFilter",
        "savedContact?.displayName",
        "const stable = canonicalWallet(value)",
        "{primary && <BottomNav active={activeTab} onChange={selectTab}/>}",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        fail(f"BleeApp verification missing {missing}")

    home_start = text.find("const renderHome")
    nearby_start = text.find("const renderNearby", home_start)
    if home_start < 0 or nearby_start < 0:
        fail("Home/Nearby boundaries missing")
    home = text[home_start:nearby_start]
    for marker in ("activity-contact-filter", "Manage contacts", "Save contact"):
        if marker in home:
            fail(f"contacts UI leaked onto Home: {marker}")

    old_dom_markers = (
        "BLEE_CONTACTS_ACTIVITY_UI_V1",
        "blee-activity-contact-tools",
        "blee-activity-filter-button",
        "blee-activity-contacts-button",
    )
    for marker in old_dom_markers:
        if marker in text:
            fail(f"legacy DOM-injected contacts UI remains: {marker}")


def verify() -> None:
    verify_app()
    css = CSS.read_text()
    for marker in (
        "BLEE_CONTACTS_REACT_V3",
        ".activity-contact-filter",
        ".react-contact-sheet",
        ".react-contact-panel",
        ".react-contact-row",
    ):
        if marker not in css:
            fail(f"CSS missing {marker}")
    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.7.0":
        fail("package version is not 2.7.0")
    print("============================================================")
    print("VERIFIED: Blee contacts React v3")
    print("- contacts are implemented inside the real Activity React screen")
    print("- Home remains a clean Recent Activity surface")
    print("- Activity retains All / Sent / Received and adds one contact filter")
    print("- payment details can save/edit the counterparty")
    print("- saved contact alias/avatar override raw wallet presentation")
    print("- bottom navigation remains owned by the primary React shell")
    print("============================================================")


def main() -> None:
    patch_app()
    patch_css()
    patch_version()
    verify()


if __name__ == "__main__":
    main()
