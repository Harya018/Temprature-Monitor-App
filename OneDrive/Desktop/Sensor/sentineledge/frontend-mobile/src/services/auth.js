// ─────────────────────────────────────────────
//  SentinelEdge — Authentication Service
//  A subscriber signs in with name + PIN, a company admin with name + password: the server tells the
//  app which one it was and which company it belongs to.
// ─────────────────────────────────────────────
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { apiBase } from '../config/config';

const KEY_TOKEN = '@sentineledge_token';
const KEY_USERNAME = '@sentineledge_username';
const KEY_KIND = '@sentineledge_kind';        // 'subscriber' | 'admin'
const KEY_COMPANY = '@sentineledge_company';  // company name

/**
 * login — POST /api/app/login
 * @returns {Promise<{token, kind, name, company:{id,name}}>}
 */
export const login = async (name, secret) => {
  const response = await axios.post(
    `${apiBase()}/app/login`,
    { name, pin: secret },
    { timeout: 8000, headers: { 'Content-Type': 'application/json' } }
  );
  return response.data;
};

export const saveSession = async (token, username, kind = 'subscriber', company = '') => {
  await AsyncStorage.multiSet([
    [KEY_TOKEN, token],
    [KEY_USERNAME, username || ''],
    [KEY_KIND, kind || 'subscriber'],
    [KEY_COMPANY, company || ''],
  ]);
};

/** getSession — { token, username, kind, company } (nulls when signed out) */
export const getSession = async () => {
  const pairs = await AsyncStorage.multiGet([KEY_TOKEN, KEY_USERNAME, KEY_KIND, KEY_COMPANY]);
  return { token: pairs[0][1], username: pairs[1][1], kind: pairs[2][1] || 'subscriber', company: pairs[3][1] || '' };
};

export const clearSession = async () => {
  await AsyncStorage.multiRemove([KEY_TOKEN, KEY_USERNAME, KEY_KIND, KEY_COMPANY]);
};

/**
 * verifySession — true if the person is still signed in. If the server says the sign-in is no longer
 * valid (switched off, expired) the saved sign-in is removed; if the server cannot be reached the
 * person stays signed in (offline).
 */
export const verifySession = async () => {
  const { token, kind } = await getSession();
  if (!token || !apiBase()) return false;
  try {
    await axios.get(`${apiBase()}/app/config`, {
      timeout: 6000,
      headers: kind === 'admin' ? { Authorization: `Bearer ${token}` } : { 'X-Auth-Token': token },
    });
    return true;
  } catch (err) {
    if (err.response && (err.response.status === 401 || err.response.status === 403)) {
      await clearSession();
      return false;
    }
    return true;
  }
};
