require 'xcodeproj'
root, fixture, strict_opening_height = ARGV
height_diagnostics = ENV['CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS'] == '1'
project = Xcodeproj::Project.new(File.join(fixture, 'KeyboardExtension.xcodeproj'))
app = project.new_target(:application, 'KeyboardHost', :ios, '16.4')
keyboard = project.new_target(:app_extension, 'ClarifyKeyboard', :ios, '16.4')
tests = project.new_target(:ui_test_bundle, 'ExtensionTests', :ios, '16.4')
container = project.new_target(:application, 'ActivationContainer', :ios, '16.4')
container.add_dependency(keyboard); tests.add_dependency(app)
app.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionHost.swift')))
shared_root = File.join(fixture, 'Shared'); Dir.mkdir(shared_root)
# Runtime metadata stays in the isolated simulator fixture. Do not link this
# probe into the distributed app or invoke the discovered private selectors.
runtime_probe = File.join(fixture, 'KeyboardReferenceProbe.m')
File.write(runtime_probe, <<~OBJC)
  #import <UIKit/UIKit.h>
  #import <objc/runtime.h>
  #import <TargetConditionals.h>
  #if TARGET_OS_SIMULATOR
  static void CaptureKeyboardRuntimeReference(void) {
    NSDictionary *selectors = @{
      @"UIKeyboardImpl": @[@"sharedInstance", @"activeInstance", @"initWithFrame:", @"inputManager", @"layout"],
      @"UIKeyboardAutomatic": @[@"sharedInstance", @"initWithFrame:"],
      @"UIKeyboardLayoutStar": @[@"initWithFrame:", @"keyplane", @"keyplaneView", @"renderingContext"],
      @"UIKBRenderFactory": @[@"init", @"lightKeycapsFontName", @"lightTextFontName", @"renderConfig"],
      @"UIKBRenderConfig": @[@"defaultConfig", @"darkConfig", @"blurRadius", @"keycapOpacity"],
      @"UIKBRenderTraits": @[@"symbolStyle", @"geometry", @"highlightedVariantTraits"],
      @"UIKBTextStyle": @[@"font", @"fontName", @"fontSize"],
      @"UIKBKeyViewAnimator": @[@"transitionKeyView:fromState:toState:completion:", @"delayedDeactivationTimeForKeyView:"],
      @"TUIKeyboardContentView": @[@"initWithFrame:"],
      @"TUIKeyplaneView": @[@"initWithFrame:"]
    };
    NSMutableDictionary *classes = [NSMutableDictionary dictionary];
    for (NSString *name in selectors) {
      Class cls = NSClassFromString(name);
      NSMutableDictionary *instance = [NSMutableDictionary dictionary], *type = [NSMutableDictionary dictionary];
      for (NSString *nameOfSelector in selectors[name]) {
        SEL selector = NSSelectorFromString(nameOfSelector);
        Method method = cls ? class_getInstanceMethod(cls, selector) : NULL;
        if (method) instance[nameOfSelector] = @(method_getTypeEncoding(method));
        method = cls ? class_getClassMethod(cls, selector) : NULL;
        if (method) type[nameOfSelector] = @(method_getTypeEncoding(method));
      }
      classes[name] = @{@"available": @(cls != Nil), @"instanceSelectors": instance, @"classSelectors": type};
    }
    NSMutableArray *fonts = [NSMutableArray array];
    for (NSString *name in @[@".SFUI-Regular", @".SFCompact-Regular", @"SFCompact-Regular", @".SFCompactDisplay-Regular"]) {
      UIFont *font = [UIFont fontWithName:name size:25];
      [fonts addObject:@{@"requested": name, @"resolved": font.fontName ?: [NSNull null]}];
    }
    UIFont *font = [UIFont systemFontOfSize:25];
    NSArray *arguments = NSProcessInfo.processInfo.arguments;
    NSString *scenario = [arguments containsObject:@"--native-keyboard-reference"] ? @"ordinary-system" :
      ([arguments containsObject:@"--system-keyboard"] ? @"secure-system" :
      ([NSBundle.mainBundle.bundleIdentifier hasSuffix:@".keyboard"] ? @"extension" : @"extension-host"));
    NSDictionary *report = @{@"os": NSProcessInfo.processInfo.operatingSystemVersionString, @"scenario": scenario,
      @"process": NSBundle.mainBundle.bundleIdentifier ?: @"unknown", @"classes": classes,
      @"fontCandidates": fonts, @"systemFont25": font.fontName,
      @"scope": @"Metadata only. No private selector invoked; availability does not establish engine embedding or behavior."};
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:NULL];
    NSString *name = [NSString stringWithFormat:@"keyboard-runtime-%@-%@.json", NSBundle.mainBundle.bundleIdentifier, scenario];
    [data writeToFile:[@#{shared_root.inspect} stringByAppendingPathComponent:name] atomically:YES];
  }
  __attribute__((constructor)) static void ScheduleKeyboardRuntimeReference(void) {
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
      CaptureKeyboardRuntimeReference();
    });
  }
  #endif
OBJC
[app, keyboard].each do |target|
  target.source_build_phase.add_file_reference(project.main_group.new_file(runtime_probe))
end
shared_source = File.join(fixture, 'SharedState.swift')
File.write(shared_source, File.read(File.join(root, 'modules/clarify-core/ios/SharedState.swift')).sub(/  init\?\(\) \{.*?\n  \}/m, "  init?() { self.root = URL(fileURLWithPath: #{shared_root.inspect}) }"))
app.source_build_phase.add_file_reference(project.main_group.new_file(shared_source))
container.source_build_phase.add_file_reference(project.main_group.new_file(shared_source))
%w[ClarifyError.swift Localization.swift].each do |name|
  source = File.join(root, 'modules/clarify-core/ios', name)
  [app, container].each do |target|
    target.source_build_phase.add_file_reference(project.main_group.new_file(source))
  end
end
%w[ActivationRequest.swift].each do |name|
  container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'modules/clarify-core/ios', name)))
end
container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardActivationContainer.swift')))
container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardReturnProbe.m')))
container.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'modules/clarify-core/ios/ClarifyReturnBridge.m')))
container_bridge = File.join(fixture, 'Container-Bridging-Header.h')
File.write(container_bridge, "#import #{File.join(root, 'modules/clarify-core/ios/ClarifyReturnBridge.h').inspect}\nNSDictionary *ClarifyReturnDiagnostics(void);\n")
tests.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionTests.swift')))
%w[KeyboardViewController.swift DictationEdit.swift KeyGridView.swift KeyPreview.swift TypingAssistant.swift HostActivation.swift KBHostArbiterHook.m KeyboardHeightSync.m].each do |name|
  source = File.join(root, 'native/keyboard', name)
  if name == 'KeyboardViewController.swift'
    original = File.read(source)
    original = original.sub('        openURL(url)', '        openURL(url) { accepted in NSLog("ClarifyFixtureOpen accepted=%d", accepted) }') if height_diagnostics
    source = File.join(fixture, name)
    instrumentation = <<~'SWIFT'
        var chain: [UIView] = []; var ancestor: UIView? = view
        while let item = ancestor, chain.count < 8 { chain.append(item); ancestor = item.superview }
        let geometry = chain.map { "\(type(of: $0)):\($0.frame):\($0.bounds)" }.joined(separator: " > ")
        NSLog("ClarifyFixtureGeometry %@", geometry)
    SWIFT
    File.write(source, height_diagnostics ? original.sub("    super.viewDidLayoutSubviews()", "    super.viewDidLayoutSubviews()\n" + instrumentation) : original)
  end
  if name == 'KeyGridView.swift' && height_diagnostics
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('    for touch in touches.sorted', '    NSLog("ClarifyFixtureTouch phase=%ld count=%ld", phase.rawValue, touches.count)' + "\n" + '    for touch in touches.sorted'))
  end
  if name == 'HostActivation.swift' && height_diagnostics
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('        let generation = KBHostArbiterHook.captureGeneration()', '        NSLog("ClarifyFixtureHost cached=%@", KBHostArbiterHook.lastCapturedHostBundleId() ?? "unknown")' + "\n" + '        let generation = KBHostArbiterHook.captureGeneration()')
      .sub('    let request = ActivationRequest(sourceBundleID: source)', '    NSLog("ClarifyFixtureHost resolved=%@", source ?? "unknown")' + "\n" + '    let request = ActivationRequest(sourceBundleID: source)'))
  end
  if name == 'KBHostArbiterHook.m' && height_diagnostics
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub("    os_unfair_lock_unlock(&sHookLock);\n}\n\n+ (void)activeArbiterCheck", <<~'OBJC'))
        os_unfair_lock_unlock(&sHookLock);
        NSLog(@"ClarifyFixtureHook queue=%s handled=%s installed=%d/%d enabled=%d", method ? method_getTypeEncoding(method) : "missing", handled ? method_getTypeEncoding(handled) : "missing", sOriginalIMP != NULL, sOriginalHandledIMP != NULL, sEnabledInstalled);
    }

    + (void)activeArbiterCheck
    OBJC
  end
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(source))
end
bridge = File.join(root, 'native/keyboard/ClarifyKeyboard-Bridging-Header.h')
%w[SharedState.swift ClarifyError.swift KeyboardVocabulary.swift KeyboardState.swift TypingCorrection.swift HapticFeedback.swift ClarifyMark.swift ActivationRequest.swift Localization.swift].each do |name|
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
    'GCC_PREPROCESSOR_DEFINITIONS' => ['$(inherited)', "CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS=#{height_diagnostics ? 1 : 0}"],
    'SWIFT_OBJC_BRIDGING_HEADER' => bridge })
end
test_info = { 'CFBundleName' => 'ExtensionTests', 'CFBundleIdentifier' => '$(PRODUCT_BUNDLE_IDENTIFIER)',
  'CFBundleExecutable' => '$(EXECUTABLE_NAME)', 'CFBundlePackageType' => 'BNDL',
  'CFBundleShortVersionString' => '1.0', 'CFBundleVersion' => '1',
  'ClarifyFixtureDirectory' => shared_root, 'ClarifyStrictOpeningHeight' => strict_opening_height == 'true',
  'ClarifyInternalManualReturn' => ENV['CLARIFY_INTERNAL_MANUAL_RETURN'] == '1' }
Xcodeproj::Plist.write_to_path(test_info, File.join(fixture, 'Tests.plist'))
tests.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.tests', 'TEST_TARGET_NAME' => 'KeyboardHost',
    'GENERATE_INFOPLIST_FILE' => 'NO', 'INFOPLIST_FILE' => File.join(fixture, 'Tests.plist') })
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app); scheme.add_test_target(tests); scheme.set_launch_target(app)
scheme.test_action.build_configuration = 'Release'
scheme.save_as(project.path, 'KeyboardExtension', true)
container_scheme = Xcodeproj::XCScheme.new
container_scheme.add_build_target(container); container_scheme.set_launch_target(container)
container_scheme.save_as(project.path, 'ActivationContainer', true)
