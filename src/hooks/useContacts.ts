'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Capacitor, registerPlugin } from '@capacitor/core';

export type BleeContact = {
  wallet: string;
  displayName: string;
  avatar?: string;
  createdAt?: number;
  updatedAt?: number;
  lastInteractedAt?: number;
  saved: boolean;
};

type ContactsPlugin = {
  listContacts(): Promise<{ contacts: BleeContact[] }>;
  contactCandidates(): Promise<{ contacts: BleeContact[] }>;
  saveContact(options: { wallet: string; displayName?: string; avatar?: string }): Promise<{ contact: BleeContact }>;
  deleteContact(options: { wallet: string }): Promise<{ deleted: boolean }>;
};

const BleeMeshContacts = registerPlugin<ContactsPlugin>('BleeMesh');

function canonicalContact(contact: Partial<BleeContact>): BleeContact | null {
  const wallet = String(contact.wallet || '').trim().toLowerCase();
  if (!/^0x[0-9a-f]{40}$/.test(wallet)) return null;
  return {
    wallet,
    displayName: String(contact.displayName || '').trim(),
    avatar: String(contact.avatar || '').trim() || undefined,
    createdAt: Number(contact.createdAt || 0) || undefined,
    updatedAt: Number(contact.updatedAt || 0) || undefined,
    lastInteractedAt: Number(contact.lastInteractedAt || 0) || undefined,
    saved: contact.saved === true,
  };
}

function mergeContacts(saved: BleeContact[], candidates: BleeContact[]): BleeContact[] {
  const byWallet = new Map<string, BleeContact>();
  for (const source of [...candidates, ...saved]) {
    const contact = canonicalContact(source);
    if (!contact) continue;
    const previous = byWallet.get(contact.wallet);
    if (!previous) {
      byWallet.set(contact.wallet, contact);
      continue;
    }
    byWallet.set(contact.wallet, {
      ...previous,
      ...contact,
      displayName: contact.displayName || previous.displayName,
      avatar: contact.avatar || previous.avatar,
      saved: previous.saved || contact.saved,
      lastInteractedAt: Math.max(previous.lastInteractedAt || 0, contact.lastInteractedAt || 0) || undefined,
      updatedAt: Math.max(previous.updatedAt || 0, contact.updatedAt || 0) || undefined,
    });
  }
  return [...byWallet.values()].sort((a, b) => {
    if (a.saved !== b.saved) return a.saved ? -1 : 1;
    const recencyA = a.lastInteractedAt || a.updatedAt || 0;
    const recencyB = b.lastInteractedAt || b.updatedAt || 0;
    if (recencyA !== recencyB) return recencyB - recencyA;
    return (a.displayName || a.wallet).localeCompare(b.displayName || b.wallet);
  });
}

export function useContacts() {
  const [saved, setSaved] = useState<BleeContact[]>([]);
  const [candidates, setCandidates] = useState<BleeContact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!Capacitor.isNativePlatform()) return;
    setLoading(true);
    try {
      const [savedResult, candidateResult] = await Promise.all([
        BleeMeshContacts.listContacts(),
        BleeMeshContacts.contactCandidates(),
      ]);
      setSaved((savedResult.contacts || []).map(canonicalContact).filter(Boolean) as BleeContact[]);
      setCandidates((candidateResult.contacts || []).map(canonicalContact).filter(Boolean) as BleeContact[]);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onChange = () => { void refresh(); };
    window.addEventListener('blee:ledger-changed', onChange);
    window.addEventListener('focus', onChange);
    return () => {
      window.removeEventListener('blee:ledger-changed', onChange);
      window.removeEventListener('focus', onChange);
    };
  }, [refresh]);

  const save = useCallback(async (contact: Pick<BleeContact, 'wallet'> & Partial<Pick<BleeContact, 'displayName' | 'avatar'>>) => {
    const wallet = String(contact.wallet || '').trim().toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(wallet)) throw new Error('Invalid contact wallet');
    const result = await BleeMeshContacts.saveContact({
      wallet,
      displayName: String(contact.displayName || '').trim(),
      avatar: String(contact.avatar || '').trim(),
    });
    await refresh();
    return canonicalContact(result.contact);
  }, [refresh]);

  const remove = useCallback(async (wallet: string) => {
    const normalized = wallet.trim().toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(normalized)) return false;
    const result = await BleeMeshContacts.deleteContact({ wallet: normalized });
    await refresh();
    return result.deleted;
  }, [refresh]);

  const contacts = useMemo(() => mergeContacts(saved, candidates), [saved, candidates]);

  return {
    contacts,
    saved: contacts.filter((contact) => contact.saved),
    recent: contacts.filter((contact) => !contact.saved),
    loading,
    error,
    refresh,
    save,
    remove,
  };
}
