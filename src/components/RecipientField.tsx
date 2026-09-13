'use client';

import { useMemo, useState } from 'react';
import { registerPlugin } from '@capacitor/core';
import { isAddress } from 'viem';
import { useContacts, type BleeContact } from '../hooks/useContacts';
import styles from './RecipientField.module.css';

type QrScannerPlugin = {
  scan(): Promise<{ value?: string; cancelled?: boolean }>;
};

const BleeQrScanner = registerPlugin<QrScannerPlugin>('BleeQrScanner');

function shortWallet(value: string) {
  return value.length > 12 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value;
}

function parseRecipientQr(rawValue: string): string {
  const raw = String(rawValue || '').trim();
  const address = (value: unknown) => {
    const candidate = String(value || '').trim();
    const direct = candidate.match(/^0x[0-9a-fA-F]{40}$/);
    if (direct) return direct[0];
    const embedded = candidate.match(/0x[0-9a-fA-F]{40}/);
    return embedded ? embedded[0] : '';
  };

  const direct = address(raw);
  if (direct && /^0x[0-9a-fA-F]{40}$/.test(raw)) return direct;

  try {
    const parsed = JSON.parse(raw);
    for (const key of ['wallet', 'address', 'recipient', 'to', 'walletAddress']) {
      const candidate = address(parsed?.[key]);
      if (candidate) return candidate;
    }
  } catch {}

  try {
    const normalized = raw.replace(/^ethereum:/i, 'blee://pay/');
    const url = new URL(normalized);
    for (const key of ['to', 'address', 'wallet', 'recipient']) {
      const candidate = address(url.searchParams.get(key));
      if (candidate) return candidate;
    }
    const candidate = address(url.pathname) || address(url.hostname);
    if (candidate) return candidate;
  } catch {}

  const embedded = address(raw);
  if (embedded && /^(?:blee:|ethereum:|https?:)/i.test(raw)) return embedded;
  throw new Error('This QR code does not contain a valid Blee recipient address.');
}

function ContactsIcon() {
  return (
    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="9" cy="8" r="3" />
      <path d="M3.8 19c.7-3.7 2.5-5.6 5.2-5.6s4.5 1.9 5.2 5.6" />
      <path d="M16 7h5M18.5 4.5v5" />
    </svg>
  );
}

function QrIcon() {
  return (
    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4z" />
      <path d="M14 14h2v2h-2zM18 14h2v6h-6v-2M14 18h2" />
    </svg>
  );
}

function ContactAvatar({ contact }: { contact: BleeContact }) {
  if (contact.avatar) {
    return <img className={styles.avatar} src={contact.avatar} alt="" />;
  }
  const initial = (contact.displayName || shortWallet(contact.wallet)).trim().charAt(0).toUpperCase() || 'B';
  return <span className={styles.avatar}>{initial}</span>;
}

export function RecipientField({
  value,
  onChange,
  onSelectContact,
}: {
  value: string;
  onChange: (value: string) => void;
  onSelectContact?: (contact: BleeContact) => void;
}) {
  const contacts = useContacts();
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState('');

  const currentSaved = useMemo(() => {
    const normalized = value.trim().toLowerCase();
    return contacts.saved.find((contact) => contact.wallet === normalized) || null;
  }, [contacts.saved, value]);

  const select = (contact: BleeContact) => {
    onChange(contact.wallet);
    onSelectContact?.(contact);
    setOpen(false);
  };

  const scan = async () => {
    setAction('');
    try {
      const result = await BleeQrScanner.scan();
      if (result.cancelled || !result.value) return;
      onChange(parseRecipientQr(result.value));
    } catch (error) {
      setAction(error instanceof Error ? error.message : 'Unable to scan this QR code.');
    }
  };

  const save = async (contact: Pick<BleeContact, 'wallet'> & Partial<Pick<BleeContact, 'displayName' | 'avatar'>>) => {
    setAction('Saving contact…');
    try {
      await contacts.save(contact);
      setAction('Contact saved');
    } catch (error) {
      setAction(error instanceof Error ? error.message : 'Unable to save contact.');
    }
  };

  const remove = async (wallet: string) => {
    setAction('Removing contact…');
    try {
      await contacts.remove(wallet);
      setAction('Contact removed');
    } catch (error) {
      setAction(error instanceof Error ? error.message : 'Unable to remove contact.');
    }
  };

  return (
    <>
      <div className={styles.entry}>
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="0x…"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-label="Recipient wallet address"
        />
        <div className={styles.actions} aria-label="Recipient actions">
          <button type="button" onClick={() => setOpen(true)} aria-label="Choose saved contact" title="Contacts">
            <ContactsIcon />
          </button>
          <button type="button" onClick={() => void scan()} aria-label="Scan recipient QR code" title="Scan QR">
            <QrIcon />
          </button>
        </div>
      </div>
      {action && !open && <small className={styles.message}>{action}</small>}

      {open && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Blee contacts" onClick={(event) => {
          if (event.currentTarget === event.target) setOpen(false);
        }}>
          <div className={styles.sheet}>
            <div className={styles.header}>
              <div>
                <small>RECIPIENTS</small>
                <h2>Contacts</h2>
              </div>
              <button type="button" className={styles.close} onClick={() => setOpen(false)} aria-label="Close contacts">×</button>
            </div>

            {isAddress(value) && !currentSaved && (
              <button type="button" className={styles.saveCurrent} onClick={() => void save({ wallet: value })}>
                <span>Save current address</span>
                <code>{shortWallet(value.toLowerCase())}</code>
              </button>
            )}

            {contacts.saved.length > 0 && (
              <section className={styles.section}>
                <h3>Saved</h3>
                <div className={styles.list}>
                  {contacts.saved.map((contact) => (
                    <div className={styles.row} key={contact.wallet}>
                      <button type="button" className={styles.main} onClick={() => select(contact)}>
                        <ContactAvatar contact={contact} />
                        <span>
                          <strong>{contact.displayName || shortWallet(contact.wallet)}</strong>
                          <code>{shortWallet(contact.wallet)}</code>
                        </span>
                      </button>
                      <button type="button" className={styles.secondary} onClick={() => void remove(contact.wallet)} aria-label={`Remove ${contact.displayName || shortWallet(contact.wallet)}`}>
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {contacts.recent.length > 0 && (
              <section className={styles.section}>
                <h3>Recent people</h3>
                <div className={styles.list}>
                  {contacts.recent.map((contact) => (
                    <div className={styles.row} key={contact.wallet}>
                      <button type="button" className={styles.main} onClick={() => select(contact)}>
                        <ContactAvatar contact={contact} />
                        <span>
                          <strong>{contact.displayName || shortWallet(contact.wallet)}</strong>
                          <code>{shortWallet(contact.wallet)}</code>
                        </span>
                      </button>
                      <button type="button" className={styles.secondary} onClick={() => void save(contact)}>
                        Save
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {!contacts.loading && contacts.contacts.length === 0 && (
              <div className={styles.empty}>
                <strong>No contacts yet</strong>
                <p>People you discover or pay will appear here. Save them once and you can select their wallet later even when they are not nearby.</p>
              </div>
            )}
            {contacts.loading && <div className={styles.empty}>Loading contacts…</div>}
            {(contacts.error || action) && <div className={styles.status}>{contacts.error || action}</div>}
          </div>
        </div>
      )}
    </>
  );
}
