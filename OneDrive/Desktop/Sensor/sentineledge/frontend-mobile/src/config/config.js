// ─────────────────────────────────────────────
//  SentinelEdge — Server address
//  ONE app serves every company: the person types the address of THEIR company's SentinelEdge server
//  once (e.g. 192.168.1.20 or a Tailscale address such as 100.64.1.5, optionally with :port). It is
//  remembered on the phone. Nothing is built into the app.
// ─────────────────────────────────────────────
import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY_SERVER = '@sentineledge_server';
const DEFAULT_PORT = 5000;

let current = null; // { host, port } once loaded / saved

/**
 * parseServer — turns what the person typed into { host, port } (or an error text).
 * Accepts "192.168.1.20", "192.168.1.20:5000", "http://192.168.1.20:5000/", "plant.example.com".
 */
export const parseServer = (input) => {
  let text = String(input || '').trim();
  if (!text) return { error: 'Enter the server address given by your company.' };
  text = text.replace(/^[a-z]+:\/\//i, '').split('/')[0].split('?')[0];
  let host = text;
  let port = DEFAULT_PORT;
  const idx = text.lastIndexOf(':');
  if (idx > 0) {
    host = text.slice(0, idx);
    port = Number(text.slice(idx + 1));
  }
  if (!/^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$/.test(host)) {
    return { error: 'That does not look like a server address. Example: 192.168.1.20' };
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { error: 'The port must be a number between 1 and 65535 (usually 5000).' };
  }
  return { host, port };
};

/** loadServer — read the saved address (call once when the app starts). */
export const loadServer = async () => {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY_SERVER);
    current = raw ? JSON.parse(raw) : null;
  } catch {
    current = null;
  }
  return current;
};

/** saveServer — validate and remember the address. Returns { host, port } or throws an Error with a plain message. */
export const saveServer = async (input) => {
  const parsed = parseServer(input);
  if (parsed.error) throw new Error(parsed.error);
  current = { host: parsed.host, port: parsed.port };
  await AsyncStorage.setItem(STORAGE_KEY_SERVER, JSON.stringify(current));
  return current;
};

export const getServer = () => current;
export const serverLabel = () => (current ? `${current.host}:${current.port}` : '');
export const serverBase = () => (current ? `http://${current.host}:${current.port}` : '');
export const apiBase = () => (current ? `${serverBase()}/api` : '');
export const healthUrl = () => (current ? `${serverBase()}/api/health` : '');
export const wsUrl = (token) =>
  current ? `ws://${current.host}:${current.port}/ws?token=${encodeURIComponent(token || '')}` : '';
