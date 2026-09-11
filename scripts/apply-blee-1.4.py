#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LOGO_FUNCTIONS = r"""function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg
      className="blee-brand-mark"
      width={size}
      height={size}
      viewBox="0 0 100 100"
      role="img"
      aria-label="Blee"
    >
      <path d="M10.615,0.825L6.704,2.476L3.352,4.952L1.304,7.565L0.000,11.142L0.000,66.850L1.117,72.352L4.283,79.230L9.125,85.420L16.387,91.334L23.277,95.048L30.912,97.799L41.527,99.725L55.121,99.862L64.246,98.762L72.812,96.424L81.192,92.572L87.151,88.446L92.737,82.806L97.207,75.791L99.628,67.813L99.814,59.285L98.510,53.508L96.462,49.106L93.669,45.117L89.199,40.578L81.750,35.626L74.860,32.737L69.274,31.224L61.453,30.124L36.872,29.986L36.499,12.380L35.754,9.904L33.520,6.465L30.168,3.576L24.581,0.963L19.739,0.000L14.898,0.000Z M36.685,50.757L36.872,50.619L56.238,50.619L56.425,50.757L58.473,50.757L58.659,50.894L59.590,50.894L63.128,51.719L65.363,52.545L67.970,53.920L70.205,55.571L72.253,57.772L73.371,59.560L74.302,62.036L74.302,62.724L74.488,62.861L74.488,78.404L74.302,78.542L53.818,78.542L53.631,78.404L52.328,78.404L52.142,78.267L51.210,78.267L49.721,77.854L49.162,77.854L47.300,77.166L46.927,77.166L43.017,75.241L41.155,73.865L38.920,71.527L37.803,69.739L36.872,67.263L36.872,66.575L36.685,66.437Z" fill="currentColor" fillRule="evenodd" clipRule="evenodd" />
    </svg>
  );
}

function BleeWordmark({ height = 22 }: { height?: number }) {
  return (
    <svg
      className="blee-wordmark"
      height={height}
      viewBox="0 0 100 100"
      role="img"
      aria-label="Blee"
      preserveAspectRatio="xMidYMid meet"
    >
      <path d="M84.713,26.804L82.038,28.179L78.981,31.615L76.943,35.395L75.287,39.863L73.885,45.017L72.866,50.515L72.102,58.076L71.975,65.636L72.484,73.196L73.503,80.069L74.650,84.880L76.688,90.722L78.854,94.845L81.911,98.282L84.586,99.656L87.516,99.656L91.465,97.251L94.522,92.784L97.325,85.567L98.344,81.100L98.344,79.038L96.943,75.601L94.522,74.914L92.611,77.320L90.828,81.787L88.408,84.880L85.096,85.567L82.293,83.162L79.618,76.976L78.471,71.478L78.089,68.041L77.962,61.512L78.217,57.388L79.618,49.485L81.146,45.361L82.803,42.612L84.331,41.237L87.006,40.893L89.427,42.612L91.083,45.361L92.866,50.515L93.631,54.639L93.503,55.670L82.038,55.670L81.146,56.357L79.873,58.763L79.363,61.512L79.490,65.979L79.745,67.010L80.637,68.041L97.834,68.041L98.981,67.010L99.873,63.918L99.873,58.763L99.490,53.265L98.344,45.704L96.943,40.206L95.032,35.052L93.376,31.959L89.682,27.835L87.389,26.804Z M55.414,26.804L51.210,29.553L48.025,34.364L45.987,39.519L43.567,49.828L42.803,56.357L42.548,65.636L43.057,73.540L43.949,79.381L45.350,85.223L47.771,91.753L49.936,95.533L52.484,98.282L55.287,99.656L58.089,99.656L62.038,97.251L65.096,92.784L67.898,85.567L68.917,81.100L68.917,78.694L68.280,76.632L67.261,75.258L65.223,74.914L63.567,76.632L61.783,81.100L58.981,84.880L55.669,85.567L53.121,83.505L51.720,81.100L50.318,77.320L49.045,71.478L48.662,68.041L48.662,58.763L49.172,54.296L50.446,48.797L52.102,44.674L53.758,42.268L55.796,40.893L58.471,41.237L60.764,43.643L62.293,46.735L63.567,50.859L64.331,55.326L52.611,55.670L51.720,56.357L50.573,58.419L49.936,61.512L50.064,65.979L50.701,67.698L51.210,68.041L69.172,67.698L70.318,65.292L70.573,60.825L70.064,52.921L68.790,45.017L67.006,38.488L65.478,34.708L63.567,31.271L60.764,28.179L58.089,26.804Z M36.688,0.000L36.561,0.344L36.178,0.344L35.287,1.718L34.522,4.124L34.140,6.873L34.140,90.722L34.650,94.158L35.414,96.220L36.433,97.595L37.707,97.595L37.834,97.251L38.471,96.907L39.618,94.158L40.127,90.722L40.127,7.216L40.000,6.873L40.000,5.842L39.745,4.124L38.981,1.718L38.089,0.344L37.707,0.344L37.580,0.000Z M2.293,2.749L0.892,6.529L0.382,9.278L0.000,13.746L0.000,82.474L0.510,87.629L1.401,91.753L2.930,95.189L4.331,96.907L5.732,97.595L22.420,97.595L25.478,95.533L28.153,91.409L30.191,85.911L31.465,80.412L32.357,72.852L32.484,65.636L32.229,60.481L30.955,52.577L29.045,46.392L26.879,42.612L27.643,39.863L28.535,34.021L28.917,28.866L28.917,23.711L28.153,15.120L26.752,8.935L25.605,5.842L24.331,3.436L22.293,1.031L20.255,0.000L5.350,0.000L3.949,0.687Z M6.752,16.495L7.643,15.464L10.701,15.464L10.828,15.120L10.955,15.464L20.000,15.464L21.274,16.838L22.675,20.619L23.312,25.430L23.185,30.241L22.675,33.333L21.274,37.113L20.000,38.488L10.573,38.832L9.427,40.206L8.790,41.924L8.280,45.017L8.280,47.766L8.790,50.859L9.809,53.265L10.573,53.952L21.529,53.952L23.057,54.983L24.204,56.701L25.605,60.481L26.369,65.636L26.369,70.790L25.987,73.883L25.478,76.289L24.204,79.725L23.057,81.443L22.038,82.131L7.771,82.131L6.497,80.412L5.860,78.351L5.478,75.601L5.478,21.649L5.987,18.557Z" fill="currentColor" fillRule="evenodd" clipRule="evenodd" />
    </svg>
  );
}"""


def replace_function(text: str, name: str, replacement: str) -> tuple[str, bool]:
    marker = f"function {name}"
    start = text.find(marker)
    if start < 0:
        return text, False
    brace = text.find("{", start)
    if brace < 0:
        return text, False

    depth = 0
    quote: str | None = None
    escaped = False
    i = brace
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:start] + replacement.rstrip() + text[i + 1 :], True
        i += 1
    return text, False


def patch_app() -> None:
    path = ROOT / "src" / "components" / "BleeApp.tsx"
    text = path.read_text()

    text, replaced_logo = replace_function(text, "LogoMark", LOGO_FUNCTIONS)
    if not replaced_logo:
        raise SystemExit("Blee 1.4 patch could not locate LogoMark")

    wordmark_patterns = (
        ('<strong>Blee</strong>', '<BleeWordmark />'),
        ('<b>Blee</b>', '<BleeWordmark />'),
        ('<span className="brand-name">Blee</span>', '<BleeWordmark />'),
        ('<span className="app-name">Blee</span>', '<BleeWordmark />'),
    )
    replaced_wordmark = False
    for old, new in wordmark_patterns:
        if old in text:
            text = text.replace(old, new)
            replaced_wordmark = True

    if not replaced_wordmark:
        start = text.find("function Brand")
        if start >= 0:
            end = text.find("\nfunction ", start + len("function Brand"))
            if end < 0:
                end = min(len(text), start + 3500)
            segment = text[start:end]
            patched = re.sub(r'>\s*Blee\s*<', '><BleeWordmark /><', segment, count=1)
            if patched != segment:
                text = text[:start] + patched + text[end:]
                replaced_wordmark = True
    if not replaced_wordmark:
        raise SystemExit("Blee 1.4 patch could not locate the visible Blee wordmark in Brand()")

    if "function formatLedgerTimestamp(" not in text:
        helper = """
function formatLedgerTimestamp(value: string | number | Date) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unavailable";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

"""
        anchor = text.find("function LogoMark")
        text = text[:anchor] + helper + text[anchor:]

    # Activity is a ledger: never display date-only timestamps.
    text = text.replace(".toLocaleDateString()", ".toLocaleString()")
    text = text.replace(".toLocaleDateString(undefined)", ".toLocaleString(undefined)")
    text = re.sub(
        r'new Date\(([^\n;]+?)\)\.toLocaleString\(\)',
        r'formatLedgerTimestamp(\1)',
        text,
    )

    text = text.replace("Blee 1.3", "Blee 1.4")
    path.write_text(text)


def patch_advanced_settings() -> None:
    path = ROOT / "src" / "components" / "BleeAdvancedSettings.tsx"
    text = path.read_text()
    text = text.replace("MetaMask-style custom EVM networks", "Custom settlement networks")
    path.write_text(text)


def patch_css() -> None:
    path = ROOT / "app" / "globals.css"
    text = path.read_text()
    block = """
/* BLEE_BRAND_14 — supplied Blee logo + wordmark */
.blee-brand-mark {
  display: block;
  flex: 0 0 auto;
  color: #090a0b;
  overflow: visible;
}

.blee-wordmark {
  display: block;
  width: auto;
  height: 21px;
  max-width: 108px;
  color: #090a0b;
  overflow: visible;
}

.activity-time,
.ledger-timestamp {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (max-width: 420px) {
  .blee-wordmark {
    height: 19px;
    max-width: 100px;
  }
}
"""
    if "BLEE_BRAND_14" not in text:
        text += "\n" + block
    path.write_text(text)


def patch_package() -> None:
    path = ROOT / "package.json"
    data = json.loads(path.read_text())
    data["version"] = "1.4.0"
    path.write_text(json.dumps(data, indent=2) + "\n")


def patch_native_generator_version() -> None:
    path = ROOT / "scripts" / "configure-native.mjs"
    if not path.exists():
        return
    text = path.read_text()
    text = re.sub(r"versionCode\s+\d+", "versionCode 7", text)
    text = re.sub(r'versionName\s+"[^"]+"', 'versionName "1.4.0"', text)
    path.write_text(text)


def verify() -> None:
    files = {
        "src/components/BleeApp.tsx": (ROOT / "src/components/BleeApp.tsx").read_text(),
        "src/hooks/useBlee.ts": (ROOT / "src/hooks/useBlee.ts").read_text(),
        "src/components/BleeAdvancedSettings.tsx": (ROOT / "src/components/BleeAdvancedSettings.tsx").read_text(),
        "app/globals.css": (ROOT / "app/globals.css").read_text(),
    }
    required = {
        "src/components/BleeApp.tsx": (
            "BleeWordmark",
            "formatLedgerTimestamp",
            "QRCodeSVG",
            "prepareProfilePhoto",
            "Profile photo",
            "Scan to copy this wallet address",
            "Blee 1.4",
        ),
        "src/hooks/useBlee.ts": (
            "rememberIdentity",
            "profilePhoto",
            "avatar: profilePhotoRef.current",
            "startMesh().catch",
            "PEER_IDENTITIES_KEY",
        ),
        "src/components/BleeAdvancedSettings.tsx": (
            "Settlement network",
            "Final after settlement",
            "Stored on your phone",
        ),
        "app/globals.css": ("BLEE_BRAND_14",),
    }
    for rel, markers in required.items():
        missing = [marker for marker in markers if marker not in files[rel]]
        if missing:
            raise SystemExit(f"Blee 1.4 verification failed for {rel}: {missing}")
    if "MetaMask-style" in files["src/components/BleeAdvancedSettings.tsx"]:
        raise SystemExit("Blee 1.4 verification failed: prototype MetaMask-style copy remains")


def main() -> None:
    patch_app()
    patch_advanced_settings()
    patch_css()
    patch_package()
    patch_native_generator_version()
    verify()
    print("Blee 1.4 brand + ledger timestamp patch verified.")


if __name__ == "__main__":
    main()
