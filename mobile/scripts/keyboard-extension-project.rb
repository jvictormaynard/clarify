require 'xcodeproj'
root, fixture = ARGV
project = Xcodeproj::Project.new(File.join(fixture, 'KeyboardExtension.xcodeproj'))
app = project.new_target(:application, 'KeyboardHost', :ios, '16.4')
keyboard = project.new_target(:app_extension, 'ClarifyKeyboard', :ios, '16.4')
tests = project.new_target(:ui_test_bundle, 'ExtensionTests', :ios, '16.4')
app.add_dependency(keyboard); tests.add_dependency(app)
app.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionHost.swift')))
tests.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionTests.swift')))
%w[KeyboardViewController.swift DictationEdit.swift KeyGridView.swift KeyPreview.swift TypingAssistant.swift HostActivation.swift KBHostArbiterHook.m].each do |name|
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/keyboard', name)))
end
bridge = File.join(root, 'native/keyboard/ClarifyKeyboard-Bridging-Header.h')
%w[SharedState.swift KeyboardVocabulary.swift KeyboardState.swift TypingCorrection.swift HapticFeedback.swift ClarifyMark.swift ActivationRequest.swift Localization.swift].each do |name|
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'modules/clarify-core/ios', name)))
end
embed = app.new_copy_files_build_phase('Embed App Extensions'); embed.dst_subfolder_spec = '13'
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
info = { 'CFBundleDisplayName' => 'Clarify', 'CFBundleName' => 'ClarifyKeyboard',
  'CFBundleIdentifier' => '$(PRODUCT_BUNDLE_IDENTIFIER)', 'CFBundleExecutable' => '$(EXECUTABLE_NAME)',
  'CFBundlePackageType' => 'XPC!', 'CFBundleShortVersionString' => '1.0', 'CFBundleVersion' => '1',
  'NSExtension' => { 'NSExtensionPointIdentifier' => 'com.apple.keyboard-service',
    'NSExtensionPrincipalClass' => '$(PRODUCT_MODULE_NAME).KeyboardViewController',
    'NSExtensionAttributes' => { 'IsASCIICapable' => true, 'PrimaryLanguage' => 'pt-BR', 'RequestsOpenAccess' => true } } }
Xcodeproj::Plist.write_to_path(info, File.join(fixture, 'Keyboard.plist'))
keyboard.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.host.keyboard',
    'APPLICATION_EXTENSION_API_ONLY' => 'YES', 'SKIP_INSTALL' => 'YES', 'GENERATE_INFOPLIST_FILE' => 'NO',
    'INFOPLIST_FILE' => File.join(fixture, 'Keyboard.plist'),
    'SWIFT_OBJC_BRIDGING_HEADER' => bridge })
end
tests.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.tests', 'TEST_TARGET_NAME' => 'KeyboardHost' })
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app); scheme.add_test_target(tests); scheme.set_launch_target(app)
scheme.test_action.build_configuration = 'Debug'
scheme.save_as(project.path, 'KeyboardExtension', true)
