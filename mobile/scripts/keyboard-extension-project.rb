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
    File.write(source, original.gsub('[self installHooks];', '// Isolated diagnostic: no process-wide arbiter hooks.'))
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
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'early-valid-size'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('width: 0, height: KeyboardInputView.contentHeight', 'width: UIScreen.main.bounds.width, height: KeyboardInputView.contentHeight')
      .sub('    inputView = input', "    super.preferredContentSize = input.bounds.size\n    inputView = input"))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'root-frame'
    original = File.read(source)
    source = File.join(fixture, name)
    sizing = <<~'SWIFT'
      override var frame: CGRect {
        get { super.frame }
        set { var value = newValue; value.size.height = Self.contentHeight; super.frame = value }
      }
      override var bounds: CGRect {
        get { super.bounds }
        set { var value = newValue; value.size.height = Self.contentHeight; super.bounds = value }
      }
    SWIFT
    File.write(source, original.sub('  static let contentHeight: CGFloat = 278', '  static let contentHeight: CGFloat = 278' + "\n" + sizing))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'stored-preferred-size'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('    inputView = input', "    super.preferredContentSize = CGSize(width: 0, height: KeyboardInputView.contentHeight)\n    inputView = input"))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'root-autolayout'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub('    inputView = input', "    input.translatesAutoresizingMaskIntoConstraints = false\n    inputView = input"))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'parent-preferred-size'
    original = File.read(source)
    source = File.join(fixture, name)
    replacement = <<~'SWIFT'
      super.viewWillAppear(animated)
      super.preferredContentSize = CGSize(width: view.bounds.width, height: KeyboardInputView.contentHeight)
      parent?.preferredContentSizeDidChange(forChildContentContainer: self)
      NSLog("ClarifyFixtureSizing notified parent=%@", String(describing: parent))
    SWIFT
    File.write(source, original.sub('super.viewWillAppear(animated);', replacement))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'parent-fitting'
    original = File.read(source)
    source = File.join(fixture, name)
    replacement = <<~'SWIFT'
      view.invalidateIntrinsicContentSize()
      parent?.systemLayoutFittingSizeDidChange(forChildContentContainer: self)
      NSLog("ClarifyFixtureSizing notified fitting parent=%@", String(describing: parent))
      super.viewWillAppear(animated);
    SWIFT
    File.write(source, original.sub('super.viewWillAppear(animated);', replacement))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'system-sizing'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub(/final class KeyboardInputView: UIInputView \{.*?\n\}/m, "final class KeyboardInputView: UIInputView { static let contentHeight: CGFloat = 278 }")
      .sub(/  override var preferredContentSize: CGSize \{.*?\n  \}/m, '// Isolated diagnostic: let UIKit own the root height.')
      .sub('keys.heightAnchor.constraint(equalToConstant: 220)', 'keys.bottomAnchor.constraint(equalTo: view.bottomAnchor)'))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'default-root'
    original = File.read(source)
    source = File.join(fixture, name)
    replacement = <<~'SWIFT'
      override func loadView() {
        super.loadView()
        view.heightAnchor.constraint(equalToConstant: KeyboardInputView.contentHeight).isActive = true
        view.backgroundColor = .clear; view.isOpaque = false
      }
    SWIFT
    File.write(source, original.sub(/  override func loadView\(\) \{.*?\n  \}/m, replacement))
  end
  if name == 'KeyboardViewController.swift' && ENV['CLARIFY_DIAGNOSTIC_SELF_SIZING'] == 'off'
    original = File.read(source)
    raise 'Self-sizing experiment no longer matches the production source' unless original.scan('allowsSelfSizing = true').length == 1
    source = File.join(fixture, name)
    File.write(source, original.sub('allowsSelfSizing = true', 'allowsSelfSizing = false'))
  end
  if name == 'KeyboardViewController.swift'
    original = File.read(source)
    original = original.sub('        openURL(url)', '        openURL(url) { accepted in NSLog("ClarifyFixtureOpen accepted=%d", accepted) }')
    source = File.join(fixture, name)
    instrumentation = <<~'SWIFT'
        var chain: [UIView] = []; var ancestor: UIView? = view
        while let item = ancestor, chain.count < 8 { chain.append(item); ancestor = item.superview }
        let geometry = chain.map { "\(type(of: $0)):\($0.frame):\($0.bounds)" }.joined(separator: " > ")
        NSLog("ClarifyFixtureGeometry %@", geometry)
    SWIFT
    File.write(source, original.sub("    super.viewDidLayoutSubviews()", "    super.viewDidLayoutSubviews()\n" + instrumentation))
    if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'native-autosize'
      original = File.read(source)
      File.write(source, original.sub('    super.viewDidLoad()', "    super.viewDidLoad()\n    ClarifyFixtureDisableAutosizing(self)"))
    end
    if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'controller-fitting'
      original = File.read(source)
      File.write(source, original.sub('    super.viewDidLoad()', "    super.viewDidLoad()\n    ClarifyFixtureInstallFitting(self)"))
    end
    if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'early-intrinsic-message'
      original = File.read(source)
      File.write(source, original.sub('super.viewWillAppear(animated);', "ClarifyFixturePublishIntrinsicSize(self); super.viewWillAppear(animated);"))
    end
    if ['window-height', 'window-height-visible'].include?(ENV['CLARIFY_DIAGNOSTIC_VARIANT'])
      original = File.read(source)
      correction = <<~'SWIFT'
          if extensionContext != nil, let window = view.window, window.bounds.height != KeyboardInputView.contentHeight {
            UIView.performWithoutAnimation {
              var frame = window.frame; frame.size.height = KeyboardInputView.contentHeight; window.frame = frame
              window.rootViewController?.view.frame = window.bounds
              self.view.frame = CGRect(x: 0, y: 0, width: window.bounds.width, height: KeyboardInputView.contentHeight)
            }
          }
      SWIFT
      correction = correction.sub('if extensionContext != nil', 'if attached, extensionContext != nil') if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'window-height-visible'
      File.write(source, original.sub("    super.viewDidLayoutSubviews()", "    super.viewDidLayoutSubviews()\n" + correction))
    end
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
  if name == 'KBHostArbiterHook.m' && ENV['CLARIFY_DIAGNOSTIC_VARIANT'] != 'without-host-hooks'
    original = File.read(source)
    source = File.join(fixture, name)
    File.write(source, original.sub("    os_unfair_lock_unlock(&sHookLock);\n}\n\n+ (void)activeArbiterCheck", <<~'OBJC'))
        os_unfair_lock_unlock(&sHookLock);
        NSLog(@"ClarifyFixtureHook queue=%s handled=%s installed=%d/%d enabled=%d", method ? method_getTypeEncoding(method) : "missing", handled ? method_getTypeEncoding(handled) : "missing", sOriginalIMP != NULL, sOriginalHandledIMP != NULL, sEnabledInstalled);
    }

    + (void)activeArbiterCheck
    OBJC
    if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'native-autosize'
      File.open(source, 'a') { |file| file.write(<<~'OBJC') }
        void ClarifyFixtureDisableAutosizing(UIInputViewController *controller) {
          @try {
            SEL selector = NSSelectorFromString(@"_setAutosizeToCurrentKeyboard:");
            NSMethodSignature *signature = [controller methodSignatureForSelector:selector];
            if (!signature || signature.numberOfArguments != 3 || strcmp(signature.methodReturnType, "v") != 0
                || !IsBooleanType([signature getArgumentTypeAtIndex:2])) return;
            ((void (*)(id, SEL, BOOL))objc_msgSend)(controller, selector, NO);
            NSLog(@"ClarifyFixtureSizing disabled native autosizing");
          } @catch (__unused NSException *error) { NSLog(@"ClarifyFixtureSizing unsupported"); }
        }
      OBJC
    end
    if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'controller-fitting'
      File.open(source, 'a') { |file| file.write(<<~'OBJC') }
        static CGSize ClarifyFixtureFitting(id self, SEL command, CGSize size, float horizontal, float vertical) {
          NSLog(@"ClarifyFixtureSizing fitting proposed=%@", NSStringFromCGSize(size));
          return CGSizeMake(size.width, 278);
        }
        void ClarifyFixtureInstallFitting(UIInputViewController *controller) {
          SEL selector = NSSelectorFromString(@"_systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:");
          NSMethodSignature *signature = [controller methodSignatureForSelector:selector];
          if (!signature || signature.numberOfArguments != 5 || strncmp(signature.methodReturnType, "{CGSize=", 8) != 0
              || strncmp([signature getArgumentTypeAtIndex:2], "{CGSize=", 8) != 0
              || strcmp([signature getArgumentTypeAtIndex:3], "f") != 0 || strcmp([signature getArgumentTypeAtIndex:4], "f") != 0) return;
          Method original = class_getInstanceMethod(controller.class, selector);
          BOOL installed = class_addMethod(controller.class, selector, (IMP)&ClarifyFixtureFitting, method_getTypeEncoding(original));
          NSLog(@"ClarifyFixtureSizing controller fitting installed=%d", installed);
        }
      OBJC
    end
    if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'early-intrinsic-message'
      File.open(source, 'a') { |file| file.write(<<~'OBJC') }
        void ClarifyFixturePublishIntrinsicSize(UIInputViewController *controller) {
          @try {
            id parent = controller.parentViewController;
            Ivar ivar = class_getInstanceVariable([parent class], "_remoteViewControllerProxyToOperator");
            id proxy = ivar ? object_getIvar(parent, ivar) : nil;
            SEL selector = NSSelectorFromString(@"__viewServiceInstrinsicContentSizeDidChange:fence:");
            NSMethodSignature *signature = [proxy methodSignatureForSelector:selector];
            if (!signature || signature.numberOfArguments != 4 || strcmp(signature.methodReturnType, "v") != 0
                || strncmp([signature getArgumentTypeAtIndex:2], "{CGSize=", 8) != 0
                || [signature getArgumentTypeAtIndex:3][0] != '@') {
              NSLog(@"ClarifyFixtureSizing intrinsic message unsupported parent=%@ proxy=%@", parent, proxy); return;
            }
            CGSize size = CGSizeMake(controller.view.bounds.size.width, 278);
            ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, selector, size, nil);
            NSLog(@"ClarifyFixtureSizing published intrinsic size=%@", NSStringFromCGSize(size));
          } @catch (__unused NSException *error) { NSLog(@"ClarifyFixtureSizing intrinsic message exception"); }
        }
      OBJC
    end
  end
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(source))
end
bridge = File.join(root, 'native/keyboard/ClarifyKeyboard-Bridging-Header.h')
if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'native-autosize'
  original_bridge = bridge; bridge = File.join(fixture, 'Keyboard-Bridging-Header.h')
  File.write(bridge, "#import #{original_bridge.inspect}\nvoid ClarifyFixtureDisableAutosizing(UIInputViewController *controller);\n")
end
if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'controller-fitting'
  original_bridge = bridge; bridge = File.join(fixture, 'Keyboard-Bridging-Header.h')
  File.write(bridge, "#import #{original_bridge.inspect}\nvoid ClarifyFixtureInstallFitting(UIInputViewController *controller);\n")
end
if ENV['CLARIFY_DIAGNOSTIC_VARIANT'] == 'early-intrinsic-message'
  original_bridge = bridge; bridge = File.join(fixture, 'Keyboard-Bridging-Header.h')
  File.write(bridge, "#import #{original_bridge.inspect}\nvoid ClarifyFixturePublishIntrinsicSize(UIInputViewController *controller);\n")
end
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
test_info = { 'CFBundleName' => 'ExtensionTests', 'CFBundleIdentifier' => '$(PRODUCT_BUNDLE_IDENTIFIER)',
  'CFBundleExecutable' => '$(EXECUTABLE_NAME)', 'CFBundlePackageType' => 'BNDL',
  'CFBundleShortVersionString' => '1.0', 'CFBundleVersion' => '1',
  'ClarifyFixtureDirectory' => shared_root, 'ClarifyDiagnosticVariant' => ENV['CLARIFY_DIAGNOSTIC_VARIANT'] || 'production' }
Xcodeproj::Plist.write_to_path(test_info, File.join(fixture, 'Tests.plist'))
tests.build_configurations.each do |config|
  config.build_settings.merge!({ 'PRODUCT_BUNDLE_IDENTIFIER' => 'com.clarify.fixture.tests', 'TEST_TARGET_NAME' => 'KeyboardHost',
    'GENERATE_INFOPLIST_FILE' => 'NO', 'INFOPLIST_FILE' => File.join(fixture, 'Tests.plist') })
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app); scheme.add_test_target(tests); scheme.set_launch_target(app)
scheme.test_action.build_configuration = 'Debug'
scheme.save_as(project.path, 'KeyboardExtension', true)
container_scheme = Xcodeproj::XCScheme.new
container_scheme.add_build_target(container); container_scheme.set_launch_target(container)
container_scheme.save_as(project.path, 'ActivationContainer', true)
