// ─────────────────────────────────────────────
//  SentinelEdge — Login Screen
// ─────────────────────────────────────────────
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StatusBar,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { login, saveSession } from '../services/auth';
import { registerPushToken } from '../services/pushTokenService';
import { loadServer, saveServer, serverBase, serverLabel } from '../config/config';
import axios from 'axios';

const LoginScreen = ({ navigation }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [server, setServer] = useState('');

  // show the address that was used last time
  useEffect(() => {
    loadServer().then(() => setServer(serverLabel()));
  }, []);

  const handleLogin = async () => {
    if (!server.trim()) {
      setError('Enter the server address given by your company.');
      return;
    }
    if (!username.trim() || !password.trim()) {
      setError('Please enter both your name and your PIN / password.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await saveServer(server);
      // is there a SentinelEdge server at this address?
      try {
        await axios.get(`${serverBase()}/api/health`, { timeout: 6000 });
      } catch (e) {
        throw Object.assign(new Error('server'), { code: 'NOSERVER' });
      }
      const data = await login(username.trim(), password);
      const token = data.token || data.access_token || data.auth_token;
      if (!token) throw new Error('No token received from server.');

      await saveSession(token, data.name || username.trim(), data.kind || 'subscriber', data.company ? data.company.name : '');
      navigation.replace('Main');
      if ((data.kind || 'subscriber') === 'subscriber') {
        registerPushToken(token, serverBase()).catch(() => {});
      }
    } catch (err) {
      if (err.code === 'NOSERVER') {
        setError(`Cannot reach a SentinelEdge server at ${serverLabel()}. Check the address and that this phone is on the same network (or VPN).`);
        setLoading(false);
        return;
      }
      if (err.message && !err.response && !err.request && err.code !== 'ECONNABORTED') {
        setError(err.message);
        setLoading(false);
        return;
      }
      console.error('[Login] Error:', err);
      if (err.response?.status === 401) {
        setError('Name or PIN / password is incorrect.');
      } else if (err.response?.status === 403) {
        setError('Account locked. Contact administrator.');
      } else if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
        setError('Connection timed out. Check server is running.');
      } else if (!err.response) {
        setError('Cannot reach server. Check your network connection.');
      } else {
        setError(err.response?.data?.message || 'Login failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <LinearGradient colors={['#0F0C29', '#1E1B4B', '#24243E']} style={styles.gradient}>
      <StatusBar barStyle="light-content" backgroundColor="#0F0C29" />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView
          contentContainerStyle={styles.container}
          keyboardShouldPersistTaps="handled"
        >
          {/* Logo / Brand */}
          <View style={styles.brandSection}>
            <View style={styles.logoCircle}>
              <Ionicons name="shield-checkmark" size={48} color="#818CF8" />
            </View>
            <Text style={styles.brandName}>SentinelEdge</Text>
            <Text style={styles.brandSubtitle}>Industrial Monitoring</Text>
          </View>

          {/* Card */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Sign in</Text>
            <Text style={styles.cardSubtitle}>Enter the server address your company gave you, then your name and PIN</Text>

            {/* Server address */}
            <View style={styles.inputWrapper}>
              <Ionicons name="server-outline" size={20} color="#818CF8" style={styles.inputIcon} />
              <TextInput
                style={styles.input}
                placeholder="Server address (e.g. 192.168.1.20)"
                placeholderTextColor="#6B7280"
                value={server}
                onChangeText={(t) => { setServer(t); setError(''); }}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                returnKeyType="next"
              />
            </View>

            {/* Username */}
            <View style={styles.inputWrapper}>
              <Ionicons name="person-outline" size={20} color="#818CF8" style={styles.inputIcon} />
              <TextInput
                style={styles.input}
                placeholder="Your name"
                placeholderTextColor="#6B7280"
                value={username}
                onChangeText={(t) => { setUsername(t); setError(''); }}
                autoCapitalize="none"
                autoCorrect={false}
                returnKeyType="next"
              />
            </View>

            {/* Password */}
            <View style={styles.inputWrapper}>
              <Ionicons name="lock-closed-outline" size={20} color="#818CF8" style={styles.inputIcon} />
              <TextInput
                style={[styles.input, styles.passwordInput]}
                placeholder="PIN / password"
                placeholderTextColor="#6B7280"
                value={password}
                onChangeText={(t) => { setPassword(t); setError(''); }}
                secureTextEntry={!showPassword}
                returnKeyType="done"
                onSubmitEditing={handleLogin}
              />
              <TouchableOpacity
                style={styles.eyeButton}
                onPress={() => setShowPassword((v) => !v)}
              >
                <Ionicons
                  name={showPassword ? 'eye-off-outline' : 'eye-outline'}
                  size={20}
                  color="#6B7280"
                />
              </TouchableOpacity>
            </View>

            {/* Error message */}
            {error ? (
              <View style={styles.errorContainer}>
                <Ionicons name="alert-circle-outline" size={16} color="#F87171" />
                <Text style={styles.errorText}>{error}</Text>
              </View>
            ) : null}

            {/* Login Button */}
            <TouchableOpacity
              style={[styles.loginButton, loading && styles.loginButtonDisabled]}
              onPress={handleLogin}
              disabled={loading}
              activeOpacity={0.85}
            >
              <LinearGradient
                colors={loading ? ['#4B5563', '#4B5563'] : ['#6366F1', '#818CF8']}
                style={styles.loginButtonGradient}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 0 }}
              >
                {loading ? (
                  <ActivityIndicator color="#FFFFFF" size="small" />
                ) : (
                  <>
                    <Ionicons name="log-in-outline" size={20} color="#FFFFFF" style={{ marginRight: 8 }} />
                    <Text style={styles.loginButtonText}>Sign In</Text>
                  </>
                )}
              </LinearGradient>
            </TouchableOpacity>
          </View>

          {/* Footer */}
          <Text style={styles.footer}>SentinelEdge v1.0.0 • Secure Connection</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </LinearGradient>
  );
};

const styles = StyleSheet.create({
  flex: { flex: 1 },
  gradient: { flex: 1 },
  container: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingVertical: 40,
  },
  brandSection: {
    alignItems: 'center',
    marginBottom: 36,
  },
  logoCircle: {
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: 'rgba(129,140,248,0.15)',
    borderWidth: 2,
    borderColor: 'rgba(129,140,248,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 14,
  },
  brandName: {
    fontSize: 30,
    fontWeight: '800',
    color: '#FFFFFF',
    letterSpacing: 1.5,
  },
  brandSubtitle: {
    fontSize: 13,
    color: '#9CA3AF',
    marginTop: 4,
    letterSpacing: 0.5,
  },
  card: {
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 20,
    padding: 24,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  cardTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#FFFFFF',
    marginBottom: 4,
  },
  cardSubtitle: {
    fontSize: 13,
    color: '#9CA3AF',
    marginBottom: 24,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.12)',
    marginBottom: 14,
    paddingHorizontal: 14,
  },
  inputIcon: {
    marginRight: 10,
  },
  input: {
    flex: 1,
    color: '#FFFFFF',
    fontSize: 15,
    paddingVertical: 14,
  },
  passwordInput: {
    paddingRight: 8,
  },
  eyeButton: {
    padding: 4,
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(248,113,113,0.12)',
    borderRadius: 8,
    padding: 10,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: 'rgba(248,113,113,0.3)',
  },
  errorText: {
    color: '#F87171',
    fontSize: 13,
    marginLeft: 6,
    flex: 1,
  },
  loginButton: {
    borderRadius: 12,
    overflow: 'hidden',
    marginTop: 6,
  },
  loginButtonDisabled: {
    opacity: 0.7,
  },
  loginButtonGradient: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 16,
  },
  loginButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  footer: {
    color: '#4B5563',
    fontSize: 12,
    marginTop: 32,
    textAlign: 'center',
  },
});

export default LoginScreen;
