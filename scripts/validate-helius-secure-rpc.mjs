import fs from 'node:fs';
import path from 'node:path';

const key = 'NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC';

function fromEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return '';
  const text = fs.readFileSync(filePath, 'utf8');
  for (const line of text.split(/\r?\n/)) {
    const clean = line.trim();
    if (!clean || clean.startsWith('#')) continue;
    const index = clean.indexOf('=');
    if (index <= 0) continue;
    if (clean.slice(0, index).trim() !== key) continue;
    let value = clean.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    return value.trim();
  }
  return '';
}

const root = process.cwd();
const value = String(process.env[key] || fromEnvFile(path.join(root, '.env.local'))).trim();
if (!value) {
  console.error(`ERROR: ${key} is required for a production Blee Android build.`);
  console.error('Create .env.local from .env.example and paste the Helius Dashboard Secure Mainnet RPC URL.');
  process.exit(1);
}

let url;
try { url = new URL(value); } catch {
  console.error(`ERROR: ${key} is not a valid URL.`);
  process.exit(1);
}

const hostname = url.hostname.toLowerCase();
if (
  url.protocol !== 'https:'
  || url.username
  || url.password
  || url.search
  || url.hash
  || !hostname.endsWith('-fast-mainnet.helius-rpc.com')
  || hostname === 'fast-mainnet.helius-rpc.com'
  || hostname === 'sender.helius-rpc.com'
) {
  console.error(`ERROR: ${key} must be the masked Helius Secure Mainnet RPC URL.`);
  console.error('Expected shape: https://<secure-id>-fast-mainnet.helius-rpc.com');
  console.error('Do not use ?api-key= URLs or the Helius Sender endpoint.');
  process.exit(1);
}

console.log('VERIFIED: Helius Secure Mainnet RPC build configuration');
