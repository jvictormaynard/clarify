const { withAppDelegate, withInfoPlist } = require('expo/config-plugins');

// External system-camera URLs must not put a QR bootstrap token in Router,
// Linking events or React Native's initial launch options. In-app AVCapture is
// the pairing entrypoint. Fail closed when the pinned native template changes.
function protectComputerLinks(source) {
  if (source.includes('// clarify-computer-link-privacy')) return source;
  const launch = /(didFinishLaunchingWithOptions launchOptions: \[UIApplication\.LaunchOptionsKey: Any\]\? = nil\s*\) -> Bool \{)([\s\S]*?)(\n  \/\/ Linking API)/;
  if (!launch.test(source)) throw new Error('Unsupported Expo AppDelegate launch template for computer link privacy');
  source = source.replace(launch, (_match, signature, body, next) => {
    const safeBody = body.replace(/launchOptions: launchOptions/g, 'launchOptions: clarifyLaunchOptions')
      .replace(/didFinishLaunchingWithOptions: launchOptions/g, 'didFinishLaunchingWithOptions: clarifyLaunchOptions');
    if (safeBody === body) throw new Error('Expo launch options were not protected');
    return `${signature}
    // clarify-computer-link-privacy
    var clarifyLaunchOptions = launchOptions
    if let url = clarifyLaunchOptions?[.url] as? URL,
       url.scheme?.lowercased() == "clarify", url.host?.lowercased() == "computer" {
      clarifyLaunchOptions?.removeValue(forKey: .url)
    }${safeBody}${next}`;
  });
  const open = /(open url: URL,\s*options: \[UIApplication\.OpenURLOptionsKey: Any\] = \[:\]\s*\) -> Bool \{)/;
  if (!open.test(source)) throw new Error('Unsupported Expo AppDelegate URL template for computer link privacy');
  return source.replace(open, `$1
    if url.scheme?.lowercased() == "clarify", url.host?.lowercased() == "computer" { return true }`);
}

module.exports = function withComputerLinkPrivacy(config) {
  config = withInfoPlist(config, mod => {
    if (mod.modResults.UIApplicationSceneManifest) {
      throw new Error('Computer link privacy requires a reviewed scene delegate before enabling the scene lifecycle');
    }
    return mod;
  });
  return withAppDelegate(config, mod => {
    if (mod.modResults.language !== 'swift') throw new Error('Computer link privacy requires the pinned Swift AppDelegate');
    mod.modResults.contents = protectComputerLinks(mod.modResults.contents);
    return mod;
  });
};
module.exports.protectComputerLinks = protectComputerLinks;
