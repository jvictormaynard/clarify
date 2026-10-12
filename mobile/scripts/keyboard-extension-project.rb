require 'xcodeproj'
root, fixture = ARGV
project = Xcodeproj::Project.new(File.join(fixture, 'KeyboardExtension.xcodeproj'))
app = project.new_target(:application, 'KeyboardHost', :ios, '16.4')
keyboard = project.new_target(:app_extension, 'ClarifyKeyboard', :ios, '16.4')
tests = project.new_target(:ui_test_bundle, 'ExtensionTests', :ios, '16.4')
container = project.new_target(:application, 'ActivationContainer', :ios, '16.4')
container.add_dependency(keyboard); tests.add_dependency(app)
app.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionHost.swift')))
shared_root = File.join(fixture, 'Shared'); Dir.mkdir(shared_root)
shared_source = File.join(fixture, 'SharedState.swift')
File.write(shared_source, File.read(File.join(root, 'modules/clarify-core/ios/SharedState.swift')).sub(/  init\?\(\) \{.*?\n  \}/m, "  init?() { self.root = URL(fileURLWithPath: #{shared_root.inspect}) }"))
app.source_build_phase.add_file_reference(project.main_group.new_file(shared_source))
container.source_build_phase.add_file_reference(project.main_group.new_file(shared_source))
%w[ActivationRequest.swift].each do |name|
  container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'modules/clarify-core/ios', name)))
end
container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardActivationContainer.swift')))
container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardReturnProbe.m')))
container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'modules/clarify-core/ios/ClarifyReturnBridge.m')))
container_bridge = File.join(fixture, 'Container-Bridging-Header.h')
File.write(container_bridge, "#import #{File.join(root, 'modules/clarify-core/ios/ClarifyReturnBridge.h').inspect}\nNSDictionary *ClarifyReturnDiagnostics(void);\n")
tests.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionTests.swift')))
%w[KeyboardViewController.swift DictationEdit.swift KeyGridView.swift KeyPreview.swift TypingAssistant.swift HostActivation.swift KBHostArbiterHook.m].each do |name|
  source = File.join(root, 'native/keyboard', name)
  if name == 'KBHostArbiterHook.m' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'without-host-hooks'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('[self installHooks];', '// Isolated diagnostic: no process-wide arbiter hooks.'))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'without-swiftui'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub(/    let host = UIHostingController.*?    activation = host/m, '// Isolated diagnostic: omit the activation hosting controller.'))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'without-preferred-size'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub(/  override var preferredContentSize: CGSize \{.*?\n  \}/m, '// Isolated diagnostic: use UIKit preferred sizing.'))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'initial-width'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('width: 0, height: KeyboardInputView.contentHeight', 'width: UIScreen.main.bounds.width, height: KeyboardInputView.contentHeight'))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_SELF_SIZING'] == 'off'
    original = File.read(source)
    raise 'Self-sizing experiment no longer matches the production source' unless original.scan('allowsSelfSizing = true').length == 1
    source = File.join(fixture, name)
    File.write(source, original.sub('allowsSelfSizing = true', 'allowsSelfSizing = false'))
  end
  if name == 'KeyboardViewController.swift'
    original = File.read(source)
    source = File.join(fixture, name)
    instrumentation = <<~'SWIFT'
        var chain: [UIView] = []; var ancestor: UIView? = view
        while let item = ancestor, chain.count < 8 { chain.append(item); ancestor = item.superview }
        let geometry = chain.map { "\(type(of: $0)):\($0.frame):\($0.bounds)" }.joined(separator: " > ")
        NSLog("ClarifyFixtureGeometry %@", geometry)
    SWIFT
    File.write(source, original.sub("    super.viewDidLayoutSubviews()", "    super.viewDidLayoutSubviews()\n" + instrumentation))
  end
  if name == 'KeyGridView.swift'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('    for touch in touches.sorted', '    NSLog("ClarifyFixtureTouch phase=%ld count=%ld", phase.rawValue, touches.count)' + "\n" + '    for touch in touches.sorted'))
  end
  if name == 'HostActivation.swift'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('        let generation = KBHostArbiterHook.captureGeneration()', '        NSLog("ClarifyFixtureHost cached=%@", KBHostArbiterHook.lastCapturedHostBundleId() ?? "unknown")' + "\n" + '        let generation = KBHostArbiterHook.captureGeneration()')
      .sub('    let request = ActivationRequest(sourceBundleID: source)', '    NSLog("ClarifyFixtureHost resolved=%@", source ?? "unknown")' + "\n" + '    let request = ActivationRequest(sourceBundleID: source)'))
  end
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(source))
end
bridge = File.join(root, 'native/keyboard/ClarifyKeyboard-Bridging-Header.h')
%w[SharedState.swift KeyboardVocabulary.swift KeyboardState.swift TypingCorrection.swift HapticFeedback.swift ClarifyMark.swift ActivationRequest.swift Localization.swift].each do |name|
  source = name == 'SharedState.swift' ? shared_source : File.join(root, 'modules/clarify-core/ios', name)
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(source))
end
embed = container.new_copy_files_build_phase('Embed App Extensions'); embed.dst_subfolder_spec = '13'
embed.add_file_reference(keyboard.product_reference).settings = { 'ATTRIBUTES' => ['RemoveHeadersOnCopy'] }
project.targets.each do |target|
  target.build_configurations.each do |config|
    config.build_settings.merge!({ 'SWIFT_VERSION' => '5.0', 'CODE_SIGNING_ALLOWED' => 'NO',
      'GENERATE_INFOPLIST_FILE' => 'YES', 'TARGETED_DEVICE_FAMILY' => '1', 'CURRENT_PROJECT_VERSION' => '1', 'MARKETING_VERSION' => '1.0' })
  end
end
app.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.host',
    'GENERATE_INFOPLIST_FILE' => 'NO', 'INFOPLIST_FILE' => File.join(fixture, 'App.plist') })
end
app_info = { 'CFBundleDisplayName' => 'Clarify', 'CFBundleName' => 'KeyboardHost',
  'CFBundleIdentifier' => '$(PRODUCT_BUNDLE_IDENTIFIER)', 'CFBundleExecutable' => '$(EXECUTABLE_NAME)',
  'CFBundlePackageType' => 'APPL', 'CFBundleShortVersionString' => '1.0', 'CFBundleVersion' => '1', 'UILaunchScreen' => {},
  'UIApplicationSceneManifest' => { 'UIApplicationSupportsMultipleScenes' => false,
    'UISceneConfigurations' => { 'UIWindowSceneSessionRoleApplication' => [
      { 'UISceneConfigurationName' => 'KeyboardHost', 'UISceneDelegateClassName' => '$(PRODUCT_MODULE_NAME).KeyboardHostScene' }
    ] } } }
Xcodeproj::Plist.write_to_path(app_info, File.join(fixture, 'App.plist'))
container_info = Marshal.load(Marshal.dump(app_info))
container_info['CFBundleName'] = 'ActivationContainer'
container_info['CFBundleDisplayName'] = 'Clarify'
container_info['CFBundleURLTypes'] = [{ 'CFBundleURLSchemes' => ['clarify'] }]
container_info['UIApplicationSceneManifest']['UISceneConfigurations']['UIWindowSceneSessionRoleApplication'][0]['UISceneDelegateClassName'] = '$(PRODUCT_MODULE_NAME).ActivationFixtureScene'
Xcodeproj::Plist.write_to_path(container_info, File.join(fixture, 'Container.plist'))
container.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.container',
    'GENERATE_INFOPLIST_FILE' => 'NO', 'INFOPLIST_FILE' => File.join(fixture, 'Container.plist'),
    'SWIFT_OBJC_BRIDGING_HEADER' => container_bridge })
end
info = { 'CFBundleDisplayName' => 'Clarify', 'CFBundleName' => 'ClarifyKeyboard',
  'CFBundleIdentifier' => '$(PRODUCT_BUNDLE_IDENTIFIER)', 'CFBundleExecutable' => '$(EXECUTABLE_NAME)',
  'CFBundlePackageType' => 'XPC!', 'CFBundleShortVersionString' => '1.0', 'CFBundleVersion' => '1',
  'NSExtension' => { 'NSExtensionPointIdentifier' => 'com.apple.keyboard-service',
    'NSExtensionPrincipalClass' => '$(PRODUCT_MODULE_NAME).KeyboardViewController',
    'NSExtensionAttributes' => { 'IsASCIICapable' => true, 'PrimaryLanguage' => 'pt-BR', 'RequestsOpenAccess' => true } } }
Xcodeproj::Plist.write_to_path(info, File.join(fixture, 'Keyboard.plist'))
keyboard.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.container.keyboard',
    'APPLICATION_EXTENSION_API_ONLY' => 'YES', 'SKIP_INSTALL' => 'YES', 'GENERATE_INFOPLIST_FILE' => 'NO',
    'INFOPLIST_FILE' => File.join(fixture, 'Keyboard.plist'),
    'HEADER_SEARCH_PATHS' => File.join(root, 'native/keyboard'),
    'SWIFT_OBJC_BRIDGING_HEADER' => bridge })
end
tests.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.tests', 'TEST_TARGET_NAME' => 'KeyboardHost',
    'INFOPLIST_KEY_ClarifyFixtureDirectory' => shared_root })
  config.build_settings['INFOPLIST_KEY_ClarifyDiagnosticVariant'] = ENV['CLARIFY_DIAGNOSTIC_VARIANT'] || 'production'
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app); scheme.add_test_target(tests); scheme.set_launch_target(app)
scheme.test_action.build_configuration = 'Debug'
scheme.save_as(project.path, 'KeyboardExtension', true)
container_scheme = Xcodeproj::XCScheme.new
container_scheme.add_build_target(container); container_scheme.set_launch_target(container)
container_scheme.save_as(project.path, 'ActivationContainer', true)
