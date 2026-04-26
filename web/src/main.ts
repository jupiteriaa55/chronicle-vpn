/**
 * Chronicle VPN — minimal client web shell.
 *
 * On Android (Capacitor): hands a .conf file to the official WireGuard app via
 * the FileProvider+ACTION_VIEW intent (provided by our native plugin).
 * On the web: triggers a browser download of the .conf file.
 */
import { registerSW } from "virtual:pwa-register";

registerSW({ immediate: true });

const $ = <T extends HTMLElement>(sel: string): T => {
  const el = document.querySelector<T>(sel);
  if (!el) throw new Error(`element not found: ${sel}`);
  return el;
};

const BOT_USERNAME =
  (window as { __BOT_USERNAME__?: string }).__BOT_USERNAME__ ?? "your_vpn_bot";

const openBot = $<HTMLAnchorElement>("#open-bot");
openBot.href = `https://t.me/${BOT_USERNAME}`;

const openWG = $<HTMLAnchorElement>("#open-wireguard");
const isAndroid = /Android/i.test(navigator.userAgent);
openWG.addEventListener("click", (ev) => {
  ev.preventDefault();
  if (isAndroid) {
    // Deep-link into the official WG app (com.wireguard.android).
    location.href =
      "intent://#Intent;package=com.wireguard.android;action=android.intent.action.MAIN;end";
  } else {
    location.href = "https://www.wireguard.com/install/";
  }
});

const importBtn = $<HTMLButtonElement>("#import-btn");
const confInput = $<HTMLTextAreaElement>("#conf-input");
const statusEl = $<HTMLParagraphElement>("#status");

importBtn.addEventListener("click", async () => {
  const text = confInput.value.trim();
  if (!text) {
    statusEl.textContent = "Paste a WireGuard config first.";
    return;
  }
  if (!text.includes("[Interface]")) {
    statusEl.textContent = "That doesn't look like a WireGuard .conf — missing [Interface] section.";
    return;
  }
  await importConfig(text);
});

async function importConfig(text: string): Promise<void> {
  // Capacitor bridge — when running inside the APK, our native plugin exposes
  // window.WireGuardImporter.importConfig(text) which writes the file via
  // FileProvider and launches the WG app intent.
  type Importer = { importConfig(args: { text: string }): Promise<void> };
  const cap = (window as { Capacitor?: { Plugins?: { WireGuardImporter?: Importer } } }).Capacitor;
  if (cap?.Plugins?.WireGuardImporter) {
    try {
      await cap.Plugins.WireGuardImporter.importConfig({ text });
      statusEl.textContent = "Sent to WireGuard.";
      return;
    } catch (e) {
      statusEl.textContent = `Failed to import: ${(e as Error).message}`;
      return;
    }
  }
  // Web fallback: download the file.
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "chronicle-vpn.conf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  statusEl.textContent = "Downloaded chronicle-vpn.conf — open with the WireGuard app.";
}
