const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const SOURCE_OVERRIDE = "ENV['RCT_USE_PREBUILT_RNCORE'] = '0'";
const sourcePath = 'node_modules/react-native/React/Fabric/Mounting/ComponentViews/TextInput/RCTTextInputComponentView.mm';
const sourceHash = '9c18f5ec8c2a497d51b25f89abfad934a581bb21c1ce9850eb8068e41eb35e63';

function verifySource(root) {
  const version = JSON.parse(fs.readFileSync(path.join(root, 'node_modules/react-native/package.json'), 'utf8')).version;
  if (version !== '0.86.3') throw new Error('Revalidate the native text patch before changing React Native.');
  const source = fs.readFileSync(path.join(root, sourcePath), 'utf8').replace(/\r\n/g, '\n');
  const actual = crypto.createHash('sha256').update(source).digest('hex');
  if (actual !== sourceHash) throw new Error('The required React Native text patch is absent or changed.');
}

function configurePodfile(contents) {
  const prefix = SOURCE_OVERRIDE + '\n';
  return contents.startsWith(prefix) ? contents : prefix + contents;
}

function verifyPods(root) {
  verifySource(root);
  const podfile = fs.readFileSync(path.join(root, 'ios/Podfile'), 'utf8').replace(/\r\n/g, '\n');
  const lock = fs.readFileSync(path.join(root, 'ios/Podfile.lock'), 'utf8');
  if (!podfile.startsWith(SOURCE_OVERRIDE + '\n')) throw new Error('React Native source compilation is not configured.');
  if (/React-Core-prebuilt/.test(lock) || !/^\s+- React-RCTFabric \(/m.test(lock)) {
    throw new Error('CocoaPods did not resolve the patched React Native source targets.');
  }
}

module.exports = { SOURCE_OVERRIDE, sourcePath, verifySource, configurePodfile, verifyPods };
if (require.main === module) {
  const root = path.resolve(__dirname, '..');
  if (process.argv[2] === '--source-only') verifySource(root);
  else verifyPods(root);
  console.log('Verified patched React Native source' + (process.argv[2] === '--source-only' ? '.' : ' and CocoaPods source targets.'));
}
