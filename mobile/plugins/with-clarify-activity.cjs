const { withXcodeProject, withDangerousMod } = require('expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');
const plist = require('@expo/plist');
const targetName = 'ClarifyActivity';

module.exports = function withClarifyActivity(config) {
  const bundle = `${config.ios.bundleIdentifier}.activity`;
  config.ios.infoPlist = { ...config.ios.infoPlist, NSSupportsLiveActivities: true };
  const ios = config.extra.eas.build.experimental.ios;
  ios.appExtensions = [...ios.appExtensions.filter((item) => item.targetName !== targetName),
    { targetName, bundleIdentifier: bundle, entitlements: {} }];
  config = withDangerousMod(config, ['ios', async (mod) => {
    const root = mod.modRequest.projectRoot;
    const out = path.join(mod.modRequest.platformProjectRoot, targetName);
    fs.mkdirSync(out, { recursive: true });
    fs.copyFileSync(path.join(root, 'native/activity/ClarifyActivity.swift'), path.join(out, 'ClarifyActivity.swift'));
    fs.copyFileSync(path.join(root, 'modules/clarify-core/ios/ClarifyActivityAttributes.swift'), path.join(out, 'ClarifyActivityAttributes.swift'));
    fs.copyFileSync(path.join(root, 'modules/clarify-core/ios/ClarifyMark.swift'), path.join(out, 'ClarifyMark.swift'));
    fs.writeFileSync(path.join(out, 'Info.plist'), plist.default.build({
      CFBundleDisplayName: 'Clarify', CFBundleName: targetName, CFBundleIdentifier: '$(PRODUCT_BUNDLE_IDENTIFIER)',
      CFBundleExecutable: '$(EXECUTABLE_NAME)', CFBundlePackageType: 'XPC!',
      CFBundleShortVersionString: config.version, CFBundleVersion: '$(CURRENT_PROJECT_VERSION)',
      NSExtension: { NSExtensionPointIdentifier: 'com.apple.widgetkit-extension' },
    }));
    return mod;
  }]);
  return withXcodeProject(config, (mod) => {
    const project = mod.modResults;
    if (project.pbxTargetByName(targetName)) return mod;
    const target = project.addTarget(targetName, 'app_extension', targetName, bundle);
    const files = ['ClarifyActivity.swift', 'ClarifyActivityAttributes.swift', 'ClarifyMark.swift'];
    const group = project.addPbxGroup(files, targetName, targetName);
    project.addToPbxGroup(group.uuid, project.getFirstProject().firstProject.mainGroup);
    project.addBuildPhase(files.map((name) => `${targetName}/${name}`), 'PBXSourcesBuildPhase', 'Sources', target.uuid);
    project.addBuildPhase([], 'PBXFrameworksBuildPhase', 'Frameworks', target.uuid);
    for (const entry of Object.values(project.pbxXCBuildConfigurationSection())) {
      if (!entry?.buildSettings || entry.buildSettings.PRODUCT_NAME !== `"${targetName}"`) continue;
      Object.assign(entry.buildSettings, {
        INFOPLIST_FILE: `"${targetName}/Info.plist"`, PRODUCT_BUNDLE_IDENTIFIER: `"${bundle}"`,
        SWIFT_VERSION: '5.0', IPHONEOS_DEPLOYMENT_TARGET: '16.4', TARGETED_DEVICE_FAMILY: '1',
        APPLICATION_EXTENSION_API_ONLY: 'YES', SKIP_INSTALL: 'YES',
        CURRENT_PROJECT_VERSION: config.ios.buildNumber ?? '1', GENERATE_INFOPLIST_FILE: 'NO',
        LD_RUNPATH_SEARCH_PATHS: '"$(inherited) @executable_path/Frameworks @executable_path/../../Frameworks"',
      });
    }
    return mod;
  });
};
