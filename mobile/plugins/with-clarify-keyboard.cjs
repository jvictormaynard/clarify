const { withXcodeProject, withDangerousMod } = require('expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');
const plist = require('@expo/plist');
const targetName = 'ClarifyKeyboard';

module.exports = function withClarifyKeyboard(config) {
  const bundle = config.ios.bundleIdentifier;
  const group = `group.${bundle}`;
  config.ios.entitlements = { ...config.ios.entitlements, 'com.apple.security.application-groups': [group] };
  config.ios.infoPlist = { ...config.ios.infoPlist, ClarifyAppGroup: group, UIBackgroundModes: ['audio'] };
  config.extra = { ...config.extra, eas: { ...config.extra?.eas, build: { experimental: { ios: {
    appExtensions: [{ targetName, bundleIdentifier: `${bundle}.keyboard`, entitlements: {
      'com.apple.security.application-groups': [group],
    } }],
  } } } } };
  config = withDangerousMod(config, ['ios', async (mod) => {
    const root = mod.modRequest.projectRoot;
    const out = path.join(mod.modRequest.platformProjectRoot, targetName);
    fs.mkdirSync(out, { recursive: true });
    fs.copyFileSync(path.join(root, 'third-party/KeyboardHostBundleID/LICENSE'), path.join(out, 'KeyboardHostBundleID.LICENSE'));
    for (const name of ['KeyboardViewController.swift', 'KeyGridView.swift', 'KeyPreview.swift', 'TypingAssistant.swift', 'HostActivation.swift', 'KBHostArbiterHook.m', 'KBHostArbiterHook.h', 'ClarifyKeyboard-Bridging-Header.h']) {
      fs.copyFileSync(path.join(root, 'native/keyboard', name), path.join(out, name));
    }
    for (const name of ['SharedState.swift', 'KeyboardVocabulary.swift', 'KeyboardState.swift', 'TypingCorrection.swift', 'HapticFeedback.swift', 'ClarifyMark.swift', 'ActivationRequest.swift', 'Localization.swift']) {
      fs.copyFileSync(path.join(root, 'modules/clarify-core/ios', name), path.join(out, name));
    }
    fs.writeFileSync(path.join(out, 'Info.plist'), plist.default.build({
      CFBundleDisplayName: 'Clarify', CFBundleName: targetName, CFBundleIdentifier: '$(PRODUCT_BUNDLE_IDENTIFIER)',
      CFBundleExecutable: '$(EXECUTABLE_NAME)', CFBundlePackageType: 'XPC!',
      CFBundleShortVersionString: config.version, CFBundleVersion: '$(CURRENT_PROJECT_VERSION)',
      ClarifyAppGroup: group,
      NSExtension: { NSExtensionPointIdentifier: 'com.apple.keyboard-service',
        NSExtensionPrincipalClass: '$(PRODUCT_MODULE_NAME).KeyboardViewController',
        NSExtensionAttributes: { IsASCIICapable: true, PrimaryLanguage: 'pt-BR', RequestsOpenAccess: true, PrefersRightToLeft: false } },
    }));
    fs.writeFileSync(path.join(out, `${targetName}.entitlements`), plist.default.build({
      'com.apple.security.application-groups': [group],
    }));
    return mod;
  }]);
  return withXcodeProject(config, (mod) => {
    const project = mod.modResults;
    if (project.pbxTargetByName(targetName)) return mod;
    const target = project.addTarget(targetName, 'app_extension', targetName, `${bundle}.keyboard`);
    const files = ['KeyboardViewController.swift', 'KeyGridView.swift', 'KeyPreview.swift', 'TypingAssistant.swift', 'HostActivation.swift', 'KBHostArbiterHook.m', 'SharedState.swift', 'KeyboardVocabulary.swift', 'KeyboardState.swift', 'TypingCorrection.swift', 'HapticFeedback.swift', 'ClarifyMark.swift', 'ActivationRequest.swift', 'Localization.swift'];
    const pbxGroup = project.addPbxGroup(files, targetName, targetName);
    project.addToPbxGroup(pbxGroup.uuid, project.getFirstProject().firstProject.mainGroup);
    project.addBuildPhase(files.map((name) => `${targetName}/${name}`), 'PBXSourcesBuildPhase', 'Sources', target.uuid);
    project.addBuildPhase([], 'PBXFrameworksBuildPhase', 'Frameworks', target.uuid);
    project.addBuildPhase([`${targetName}/KeyboardHostBundleID.LICENSE`], 'PBXResourcesBuildPhase', 'Resources', target.uuid);
    for (const entry of Object.values(project.pbxXCBuildConfigurationSection())) {
      if (!entry?.buildSettings || entry.buildSettings.PRODUCT_NAME !== `"${targetName}"`) continue;
      Object.assign(entry.buildSettings, {
        INFOPLIST_FILE: `"${targetName}/Info.plist"`,
        CODE_SIGN_ENTITLEMENTS: `"${targetName}/${targetName}.entitlements"`,
        PRODUCT_BUNDLE_IDENTIFIER: `"${bundle}.keyboard"`, SWIFT_VERSION: '5.0',
        IPHONEOS_DEPLOYMENT_TARGET: '16.4', TARGETED_DEVICE_FAMILY: '1',
        APPLICATION_EXTENSION_API_ONLY: 'YES', SKIP_INSTALL: 'YES', CURRENT_PROJECT_VERSION: config.ios.buildNumber ?? '1',
        GENERATE_INFOPLIST_FILE: 'NO',
        SWIFT_OBJC_BRIDGING_HEADER: `"${targetName}/ClarifyKeyboard-Bridging-Header.h"`,
        LD_RUNPATH_SEARCH_PATHS: '"$(inherited) @executable_path/Frameworks @executable_path/../../Frameworks"',
      });
    }
    return mod;
  });
};
