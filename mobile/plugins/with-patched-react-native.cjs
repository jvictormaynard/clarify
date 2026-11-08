const { withPodfile } = require('expo/config-plugins');
const { configurePodfile, verifySource } = require('../scripts/verify-react-native-source.cjs');

module.exports = function withPatchedReactNative(config) {
  return withPodfile(config, config => {
    verifySource(config.modRequest.projectRoot);
    config.modResults.contents = configurePodfile(config.modResults.contents);
    return config;
  });
};
