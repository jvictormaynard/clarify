const { withInfoPlist } = require('expo/config-plugins');

const relayException = {
  NSIncludesSubdomains: true,
  // Apple requires this scoped key to loosen HTTPS server trust for a
  // self-signed PC certificate. Swift still requires HTTPS and the exact pin.
  // https://developer.apple.com/documentation/bundleresources/information-property-list/nsexceptionallowsinsecurehttploads
  NSExceptionAllowsInsecureHTTPLoads: true,
  NSExceptionMinimumTLSVersion: 'TLSv1.2',
  NSExceptionRequiresForwardSecrecy: true,
};

function validRelayHost(host) {
  // Reserve 53 bytes for the certificate namespace and its separating dot.
  if (typeof host !== 'string' || host.length > 200) return false;
  const labels = host.split('.');
  return labels.length >= 2 && /[a-z]/.test(labels.at(-1)) &&
    !['local', 'localhost', 'internal', 'test', 'invalid'].includes(labels.at(-1)) &&
    labels.every(label => label.length >= 1 && label.length <= 63 && !/[^a-z0-9-]/.test(label) &&
      !label.startsWith('-') && !label.endsWith('-'));
}

module.exports = function withComputerRelay(config) {
  const settings = require('../../shared/computer_connect.json');
  if (!settings || Object.keys(settings).sort().join(',') !== 'relay_host,relay_port,schema_version' ||
    settings.schema_version !== 1 || !Number.isInteger(settings.relay_port) ||
    settings.relay_port < 1 || settings.relay_port > 65535 ||
    (settings.relay_host !== null && !validRelayHost(settings.relay_host))) {
    throw new Error('Invalid Clarify relay build configuration');
  }
  const host = process.env.EXPO_PUBLIC_CLARIFY_CONNECT_RELAY_HOST ?? settings.relay_host ?? undefined;
  if (host !== undefined && !validRelayHost(host)) throw new Error('Invalid Clarify relay host build configuration');
  return withInfoPlist(config, mod => {
    const plist = mod.modResults;
    // An existing native build cannot retain a different scope after the
    // variable changes or is removed. Require a clean prebuild in that case.
    if (plist.ClarifyConnectRelayHost !== undefined && plist.ClarifyConnectRelayHost !== host) {
      throw new Error('Stale Clarify relay host in native Info.plist; use a clean prebuild');
    }
    if (host === undefined) return mod;
    const ats = plist.NSAppTransportSecurity ?? {};
    const domains = ats.NSExceptionDomains ?? {};
    const existing = domains[host];
    if (existing !== undefined && (Object.keys(existing).length !== Object.keys(relayException).length ||
      Object.entries(relayException).some(([key, value]) => existing[key] !== value))) {
      throw new Error('Conflicting ATS exception for Clarify relay host');
    }
    plist.ClarifyConnectRelayHost = host;
    plist.NSAppTransportSecurity = { ...ats, NSExceptionDomains: { ...domains, [host]: { ...relayException } } };
    return mod;
  });
};
