"use client";

import { useMemo, useState } from "react";
import {
  ARC_TESTNET,
  deleteNetwork,
  getActiveNetwork,
  listNetworks,
  saveNetwork,
  setActiveNetwork,
  testNetwork,
  type BleeNetwork,
} from "../lib/networkConfig";
import {
  exportEncryptedWalletBackup,
  importEncryptedWalletBackup,
  importPrivateKey,
  revealPrivateKey,
} from "../lib/walletRecovery";

const emptyNetwork = (): BleeNetwork => ({
  id: `custom-${Date.now()}`,
  name: "",
  chainId: 0,
  rpcUrl: "",
  explorerUrl: "",
  nativeSymbol: "ETH",
  tokenSymbol: "USDC",
  tokenAddress: "0x0000000000000000000000000000000000000000",
  tokenDecimals: 6,
  eip712Name: "USDC",
  eip712Version: "2",
  testnet: false,
});

function copyText(value: string) {
  return navigator.clipboard.writeText(value);
}

function downloadText(filename: string, body: string) {
  const blob = new Blob([body], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function BleeAdvancedSettings() {
  const [networks, setNetworks] = useState<BleeNetwork[]>(() => listNetworks());
  const [active, setActive] = useState<BleeNetwork>(() => getActiveNetwork());
  const [draft, setDraft] = useState<BleeNetwork>(() => emptyNetwork());
  const [networkMessage, setNetworkMessage] = useState("");
  const [testing, setTesting] = useState(false);

  const [walletPassphrase, setWalletPassphrase] = useState("");
  const [revealedKey, setRevealedKey] = useState("");
  const [walletMessage, setWalletMessage] = useState("");
  const [importKey, setImportKey] = useState("");
  const [importPassphrase, setImportPassphrase] = useState("");
  const [backupJson, setBackupJson] = useState("");
  const [confirmImport, setConfirmImport] = useState("");

  const activeSummary = useMemo(
    () => `${active.name} · ${active.tokenSymbol} · Chain ${active.chainId}`,
    [active],
  );

  async function handleSaveNetwork() {
    setNetworkMessage("");
    setTesting(true);
    try {
      await testNetwork(draft);
      const saved = saveNetwork(draft);
      const next = listNetworks();
      setNetworks(next);
      setDraft(emptyNetwork());
      setNetworkMessage(`${saved.name} verified and saved.`);
    } catch (error) {
      setNetworkMessage(error instanceof Error ? error.message : "Could not save network");
    } finally {
      setTesting(false);
    }
  }

  function activateNetwork(id: string) {
    const selected = setActiveNetwork(id);
    setActive(selected);
    setNetworkMessage(`${selected.name} is now active. Reloading Blee…`);
    setTimeout(() => window.location.reload(), 600);
  }

  async function handleReveal() {
    setWalletMessage("");
    setRevealedKey("");
    try {
      const key = await revealPrivateKey(walletPassphrase);
      setRevealedKey(key);
      setWalletMessage("Private key revealed. Keep it offline and never share it.");
      setTimeout(() => setRevealedKey(""), 30000);
    } catch (error) {
      setWalletMessage(error instanceof Error ? error.message : "Could not reveal private key");
    }
  }

  async function handleEncryptedBackup() {
    setWalletMessage("");
    try {
      const backup = await exportEncryptedWalletBackup();
      downloadText(`blee-wallet-backup-${Date.now()}.json`, backup);
      setWalletMessage("Encrypted wallet backup downloaded. It still requires your passphrase.");
    } catch (error) {
      setWalletMessage(error instanceof Error ? error.message : "Could not export wallet backup");
    }
  }

  async function handleImportPrivateKey() {
    setWalletMessage("");
    if (confirmImport !== "IMPORT") {
      setWalletMessage('Type "IMPORT" to confirm wallet replacement.');
      return;
    }
    try {
      const address = await importPrivateKey(importKey, importPassphrase);
      setWalletMessage(`Wallet ${address.slice(0, 8)}… imported. Reloading Blee…`);
      setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      setWalletMessage(error instanceof Error ? error.message : "Could not import private key");
    }
  }

  async function handleImportBackup() {
    setWalletMessage("");
    if (confirmImport !== "IMPORT") {
      setWalletMessage('Type "IMPORT" to confirm wallet replacement.');
      return;
    }
    try {
      const address = await importEncryptedWalletBackup(backupJson);
      setWalletMessage(`Wallet ${address.slice(0, 8)}… restored. Reloading Blee…`);
      setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      setWalletMessage(error instanceof Error ? error.message : "Could not import wallet backup");
    }
  }

  const summaryStyle = { cursor: "pointer", listStyle: "none" as const, padding: "16px 0", fontWeight: 700 };
  const noteStyle = { fontSize: 12, lineHeight: 1.55, opacity: 0.72, marginTop: 10 };
  const dangerStyle = { fontSize: 12, lineHeight: 1.55, color: "#8b2b2b", marginTop: 10 };
  const gridStyle = { display: "grid", gap: 10, marginTop: 12 };

  return (
    <>
      <section className="settings-group">
        <div className="settings-heading">
          <span>Networks</span>
          <small>MetaMask-style custom EVM networks</small>
        </div>
        <div className="premium-card settings-list">
          <div className="setting-row">
            <div>
              <strong>Active settlement network</strong>
              <small>{activeSummary}</small>
            </div>
            <span className={`status-badge ${active.testnet ? "" : "good"}`}>{active.testnet ? "TESTNET" : "CUSTOM"}</span>
          </div>
          <div className="card-divider" />
          {networks.map((network) => (
            <div key={network.id} style={{ padding: "12px 0" }}>
              <div className="setting-row">
                <div>
                  <strong>{network.name}</strong>
                  <small>{network.tokenSymbol} · Chain {network.chainId}</small>
                </div>
                <button
                  className="button secondary"
                  disabled={active.id === network.id}
                  onClick={() => activateNetwork(network.id)}
                >
                  {active.id === network.id ? "Active" : "Use"}
                </button>
              </div>
              {!network.locked && (
                <button className="text-button" onClick={() => { deleteNetwork(network.id); setNetworks(listNetworks()); }}>
                  Remove
                </button>
              )}
            </div>
          ))}
          <div className="card-divider" />
          <details>
            <summary style={summaryStyle}>Add network</summary>
            <div style={gridStyle}>
              <label className="field-group"><span>Network name</span><div className="input-shell"><input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Arc Mainnet" /></div></label>
              <label className="field-group"><span>Chain ID</span><div className="input-shell"><input inputMode="numeric" value={draft.chainId || ""} onChange={(e) => setDraft({ ...draft, chainId: Number(e.target.value || 0) })} placeholder="Chain ID" /></div></label>
              <label className="field-group"><span>RPC URL</span><div className="input-shell"><input value={draft.rpcUrl} onChange={(e) => setDraft({ ...draft, rpcUrl: e.target.value })} placeholder="https://…" /></div></label>
              <label className="field-group"><span>Block explorer</span><div className="input-shell"><input value={draft.explorerUrl} onChange={(e) => setDraft({ ...draft, explorerUrl: e.target.value })} placeholder="https://…" /></div></label>
              <label className="field-group"><span>Native currency symbol</span><div className="input-shell"><input value={draft.nativeSymbol} onChange={(e) => setDraft({ ...draft, nativeSymbol: e.target.value })} placeholder="ETH" /></div></label>
              <label className="field-group"><span>Payment token symbol</span><div className="input-shell"><input value={draft.tokenSymbol} onChange={(e) => setDraft({ ...draft, tokenSymbol: e.target.value })} placeholder="USDC" /></div></label>
              <label className="field-group"><span>Payment token contract</span><div className="input-shell mono"><input value={draft.tokenAddress} onChange={(e) => setDraft({ ...draft, tokenAddress: e.target.value as `0x${string}` })} placeholder="0x…" /></div></label>
              <label className="field-group"><span>Token decimals</span><div className="input-shell"><input inputMode="numeric" value={draft.tokenDecimals} onChange={(e) => setDraft({ ...draft, tokenDecimals: Number(e.target.value || 0) })} /></div></label>
              <label className="field-group"><span>EIP-712 token name</span><div className="input-shell"><input value={draft.eip712Name} onChange={(e) => setDraft({ ...draft, eip712Name: e.target.value })} placeholder="USDC" /></div></label>
              <label className="field-group"><span>EIP-712 version</span><div className="input-shell"><input value={draft.eip712Version} onChange={(e) => setDraft({ ...draft, eip712Version: e.target.value })} placeholder="2" /></div></label>
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <input type="checkbox" checked={draft.testnet} onChange={(e) => setDraft({ ...draft, testnet: e.target.checked })} /> Test network
              </label>
              <button className="button primary full" disabled={testing} onClick={handleSaveNetwork}>{testing ? "Testing RPC…" : "Test & save network"}</button>
              {networkMessage && <div className="notice">{networkMessage}</div>}
            </div>
          </details>
        </div>
        <p style={noteStyle}>
          Blee is bundled and tested with Arc Testnet. Custom networks are user-supplied. For payment settlement, the configured token must support EIP-3009 transferWithAuthorization and authorizationState with the matching EIP-712 domain. Mainnet has not been validated in this build; add official mainnet details when available and test with small value first.
        </p>
      </section>

      <section className="settings-group">
        <div className="settings-heading">
          <span>Wallet recovery</span>
          <small>Your keys remain under your control</small>
        </div>
        <div className="premium-card settings-list">
          <details>
            <summary style={summaryStyle}>Back up wallet</summary>
            <button className="button secondary full" onClick={handleEncryptedBackup}>Download encrypted backup</button>
            <div style={gridStyle}>
              <label className="field-group"><span>Wallet passphrase</span><div className="input-shell"><input type="password" value={walletPassphrase} onChange={(e) => setWalletPassphrase(e.target.value)} placeholder="Enter passphrase" /></div></label>
              <button className="button secondary full" onClick={handleReveal}>Reveal private key</button>
              {revealedKey && (
                <div className="notice" style={{ wordBreak: "break-all" }}>
                  <strong>Private key</strong><br />{revealedKey}<br />
                  <button className="text-button" onClick={() => copyText(revealedKey)}>Copy private key</button>
                </div>
              )}
              <p style={dangerStyle}>Anyone with this private key can control the wallet. Blee never uploads it. The revealed key automatically disappears from this screen after 30 seconds.</p>
            </div>
          </details>
          <div className="card-divider" />
          <details>
            <summary style={summaryStyle}>Import or restore wallet</summary>
            <div style={gridStyle}>
              <label className="field-group"><span>Private key</span><div className="input-shell mono"><input type="password" value={importKey} onChange={(e) => setImportKey(e.target.value)} placeholder="0x…" /></div></label>
              <label className="field-group"><span>New Blee passphrase</span><div className="input-shell"><input type="password" value={importPassphrase} onChange={(e) => setImportPassphrase(e.target.value)} placeholder="At least 12 characters" /></div></label>
              <label className="field-group"><span>Or paste encrypted Blee backup JSON</span><div className="input-shell"><textarea value={backupJson} onChange={(e) => setBackupJson(e.target.value)} rows={4} style={{ width: "100%", border: 0, outline: 0, background: "transparent", resize: "vertical" }} placeholder='{"format":"blee-wallet-backup",…}' /></div></label>
              <label className="field-group"><span>Type IMPORT to replace the wallet on this device</span><div className="input-shell"><input value={confirmImport} onChange={(e) => setConfirmImport(e.target.value)} placeholder="IMPORT" /></div></label>
              <button className="button primary full" disabled={!importKey || importPassphrase.length < 12} onClick={handleImportPrivateKey}>Import private key</button>
              <button className="button secondary full" disabled={!backupJson} onClick={handleImportBackup}>Restore encrypted backup</button>
              <p style={dangerStyle}>Import replaces the local wallet vault. Confirm that you have backed up the current wallet first. Payment history remains in the local SQLite journal, but on-chain funds belong to the imported address.</p>
            </div>
          </details>
          {walletMessage && <div className="notice" style={{ marginTop: 10 }}>{walletMessage}</div>}
        </div>
      </section>

      <section className="settings-group">
        <div className="settings-heading">
          <span>How Blee works</span>
          <small>Current test build</small>
        </div>
        <div className="premium-card settings-list">
          <div className="setting-row"><div><strong>Activity storage</strong><small>Native SQLite + WAL on this Android device</small></div><span className="status-badge good">LOCAL</span></div>
          <div className="card-divider" />
          <div className="setting-row"><div><strong>Offline delivery</strong><small>Signed payment authorizations move over Bluetooth or local Wi-Fi and are durably stored before acknowledgement</small></div></div>
          <div className="card-divider" />
          <div className="setting-row"><div><strong>Final settlement</strong><small>Pending payments become spendable only after the active network confirms settlement</small></div></div>
          <div className="card-divider" />
          <div className="setting-row"><div><strong>Mainnet status</strong><small>Not yet validated. This build is for testnet/hackathon testing until official mainnet parameters are verified.</small></div><span className="status-badge">TEST</span></div>
        </div>
      </section>
    </>
  );
}
