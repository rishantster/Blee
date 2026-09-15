import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const sourceRoot = path.join(root, 'src');
const gatewayFile = path.join(sourceRoot, 'lib', 'solanaGateway.ts');
const expectedGateway = 'https://rpc.paywithblee.xyz/api/solana';

function walk(dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(full));
    } else if (/\.(ts|tsx|js|jsx|mjs)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

if (!fs.existsSync(gatewayFile)) {
  console.error('ERROR: canonical Solana gateway adapter is missing.');
  process.exit(1);
}

const gatewaySource = fs.readFileSync(gatewayFile, 'utf8');
if (!gatewaySource.includes(expectedGateway)) {
  console.error(`ERROR: Blee Solana gateway must be ${expectedGateway}`);
  process.exit(1);
}

const forbidden = [
  { re: /helius-rpc[.]com/i, label: 'direct Helius RPC hostname' },
  { re: /NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC/, label: 'public Helius RPC environment variable' },
  { re: /HELIUS_API_KEY/, label: 'Helius API key environment variable' },
  { re: /[?&]api-key=/i, label: 'provider API key query parameter' },
  { re: /https:\/\/api[.](mainnet-beta|devnet|testnet)[.]solana[.]com/i, label: 'direct Solana public RPC bypass' },
];

for (const file of walk(sourceRoot)) {
  const text = fs.readFileSync(file, 'utf8');
  for (const rule of forbidden) {
    if (rule.re.test(text)) {
      console.error(`ERROR: APK-bound source contains ${rule.label}: ${path.relative(root, file)}`);
      process.exit(1);
    }
  }
}

console.log(`VERIFIED: APK uses only Blee Solana RPC gateway ${expectedGateway}`);
