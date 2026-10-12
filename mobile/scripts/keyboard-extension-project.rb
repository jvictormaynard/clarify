require 'xcodeproj'
require 'fileutils'
root, fixture = ARGV
project = Xcodeproj::Project.new(File.join(fixture, 'KeyboardExtension.xcodeproj'))
variant = ENV.fetch('CLARIFY_KEYBOARD_VARIANT', 'baseline')
app = project.new_target(:application, 'KeyboardHost', :ios, '16.4')
keyboard = project.new_target(:app_extension, 'ClarifyKeyboard', :ios, '16.4')
tests = project.new_target(:ui_test_bundle, 'ExtensionTests', :ios, '16.4')
app.add_dependency(keyboard); tests.add_dependency(app)
app.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionHost.swift')))
tests.source_build_phase.add_file_reference(project.main_group.new_file(File.join(root, 'native/tests/KeyboardExtensionTests.swift')))
%w[KeyboardViewController.swift DictationEdit.swift KeyGridView.swift KeyPreview.swift TypingAssistant.swift HostActivation.swift KBHostArbiterHook.m].each do |name|
  file = File.join(root, 'native/keyboard', name)
  if name == 'KeyboardViewController.swift' && variant != 'baseline'
    source = File.read(file)
    start = source.index('  // The remote input host')
    finish = source.index('  override func viewDidLoad()', start)
    raise 'Sizing fixture source boundary changed' unless start && finish
    initialization = <<~SWIFT
      override init(nibName: String?, bundle: Bundle?) {
        #{variant == 'controller-policy' ? 'KBInstallFixtureSizing(KeyboardViewController.self)' : ''}
        super.init(nibName: nibName, bundle: bundle)
        preferredContentSize = CGSize(width: UIScreen.main.bounds.width, height: KeyboardInputView.contentHeight)
        #{variant.start_with?('eager-') ? 'loadViewIfNeeded()' : ''}
        #{variant == 'eager-layout' ? 'view.layoutIfNeeded()' : ''}
      }
      required init?(coder: NSCoder) {
        #{variant == 'controller-policy' ? 'KBInstallFixtureSizing(KeyboardViewController.self)' : ''}
        super.init(coder: coder)
        preferredContentSize = CGSize(width: UIScreen.main.bounds.width, height: KeyboardInputView.contentHeight)
        #{variant.start_with?('eager-') ? 'loadViewIfNeeded()' : ''}
        #{variant == 'eager-layout' ? 'view.layoutIfNeeded()' : ''}
      }
    SWIFT
    layout = case variant
    when 'native-root'
      'super.loadView(); view.heightAnchor.constraint(equalToConstant: KeyboardInputView.contentHeight).isActive = true'
    when 'fixed-frame'
      'inputView = UIInputView(frame: CGRect(origin: .zero, size: preferredContentSize), inputViewStyle: .keyboard)'
    else
      'inputView = KeyboardInputView(frame: CGRect(origin: .zero, size: preferredContentSize), inputViewStyle: .keyboard)'
    end
    replacement = initialization + "override func loadView() {\n#{layout}\nview.backgroundColor = .clear; view.isOpaque = false\n}\n"
    source[start...finish] = replacement
    if variant == 'no-hosting'
      host_start = source.index('    let host = UIHostingController(rootView: ActivationLink')
      host_end = source.index('    requestSupplementaryLexicon', host_start)
      source[host_start...host_end] = ''
    end
    file = File.join(fixture, name); File.write(file, source)
  end
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(file))
end
bridge = File.join(root, 'native/keyboard/ClarifyKeyboard-Bridging-Header.h')
if variant == 'controller-policy'
  source = <<~OBJC
    #import <UIKit/UIKit.h>
    #import <objc/runtime.h>
    #include <string.h>
    static BOOL matches(Method method, unsigned int index, const char *expected) {
      char *type = method_copyArgumentType(method, index);
      BOOL valid = type && strcmp(type, expected) == 0; free(type); return valid;
    }
    void KBInstallFixtureSizing(Class target) {
      static dispatch_once_t once; dispatch_once(&once, ^{
        SEL selector = NSSelectorFromString(@"_systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:");
        Method method = class_getInstanceMethod(UIInputViewController.class, selector);
        char *result = method ? method_copyReturnType(method) : NULL;
        BOOL valid = result && strcmp(result, @encode(CGSize)) == 0 && method_getNumberOfArguments(method) == 5 &&
          matches(method, 2, @encode(CGSize)) && matches(method, 3, @encode(float)) && matches(method, 4, @encode(float));
        free(result);
        NSLog(@"Clarify sizing fixture: compatible=%d", valid);
        if (!valid) return;
        IMP implementation = imp_implementationWithBlock(^CGSize(id controller, CGSize size, float horizontal, float vertical) {
          CGFloat width = size.width > 0 && size.width < 2000 ? size.width : UIScreen.mainScreen.bounds.size.width;
          NSLog(@"Clarify sizing fixture: request=%.1fx%.1f", size.width, size.height);
          return CGSizeMake(width, 278);
        });
        if (!class_addMethod(target, selector, implementation, method_getTypeEncoding(method))) imp_removeBlock(implementation);
      });
    }
  OBJC
  file = File.join(fixture, 'ControllerSizing.m'); File.write(file, source)
  keyboard.source_build_phase.add_file_reference(project.main_group.new_file(file))
  header = "#import \"#{bridge}\"\nvoid KBInstallFixtureSizing(Class target);\n"
  bridge = File.join(fixture, 'Bridge.h'); File.write(bridge, header)
end
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
    'INFOPLIST_KEY_UILaunchScreen_Generation' => 'YES', 'INFOPLIST_KEY_CFBundleDisplayName' => 'Clarify' })
end
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
