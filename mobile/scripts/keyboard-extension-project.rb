gem 'xcodeproj', '= 1.27.0'
require 'xcodeproj'
root, fixture, strict_opening_height = ARGV
height_diagnostics = ENV['CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS'] == '1'
# Isolated cursor-trace branch only. Never merge these generated-copy probes.
cursor_diagnostics = true
def cursor_trace_replace(source, needle, replacement)
  raise "Cursor trace source boundary changed: #{needle.lines.first}" unless source.scan(needle).length == 1
  source.sub(needle, replacement)
end
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
  if cursor_diagnostics && name == 'KeyGridView.swift'
    original = File.read(source)
    original = cursor_trace_replace(original, '      switch phase {', <<~'SWIFT'.rstrip)
          NSLog("ClarifyCursorGrid %@", "t=\(ProcessInfo.processInfo.systemUptime) phase=\(phase.rawValue) id=\(id) x=\(point.x) token=\(spacePress?.token.uuidString ?? "nil") active=\(spacePress?.active ?? false) movable=\(spacePress?.movable ?? false)")
          switch phase {
    SWIFT
    original = cursor_trace_replace(original, '        let offset = Int(distance / 6)', <<~'SWIFT'.rstrip)
            let offset = Int(distance / 6)
            NSLog("ClarifyCursorGrid %@", "t=\(ProcessInfo.processInfo.systemUptime) delta=\(point.x - space.x) remainder=\(space.remainder) offset=\(offset) movable=\(space.movable) token=\(space.token)")
    SWIFT
    original = cursor_trace_replace(original, 'onMoveCursor?(offset) != true', 'tracedCursorMove(offset) != true')
    original = cursor_trace_replace(original, '  private func finishSpacePress() {', <<~'SWIFT'.rstrip)
      private func tracedCursorMove(_ offset: Int) -> Bool? {
        let result = onMoveCursor?(offset)
        NSLog("ClarifyCursorGrid %@", "t=\(ProcessInfo.processInfo.systemUptime) callback=\(String(describing: result)) offset=\(offset) token=\(spacePress?.token.uuidString ?? "nil")")
        return result
      }
      private func finishSpacePress() {
        NSLog("ClarifyCursorGrid %@", "t=\(ProcessInfo.processInfo.systemUptime) cleanup token=\(spacePress?.token.uuidString ?? "nil") active=\(spacePress?.active ?? false) movable=\(spacePress?.movable ?? false)")
    SWIFT
    source = File.join(fixture, name); File.write(source, original)
  end
  if cursor_diagnostics && name == 'TypingAssistant.swift'
    original = File.read(source)
    original = cursor_trace_replace(original, '  func prepareCursor(in proxy: UITextDocumentProxy) {', '  func prepareCursor(in proxy: UITextDocumentProxy) { cursorTrace("prepare")')
    original = cursor_trace_replace(original, '  func endCursor() { inputGeneration', '  func endCursor() { cursorTrace("end"); inputGeneration')
    original = cursor_trace_replace(original, '  func moveCursor(_ offset: Int, in proxy: UITextDocumentProxy) -> Bool {', '  func moveCursor(_ offset: Int, in proxy: UITextDocumentProxy) -> Bool { cursorTrace("move offset=\(offset)")')
    original = cursor_trace_replace(original, '      endCursor(); return false', '      cursorTrace("pre-reject"); endCursor(); return false')
    original = cursor_trace_replace(original, '    if moved.isEmpty { return true }', '    if moved.isEmpty { cursorTrace("boundary-noop"); return true }')
    original = cursor_trace_replace(original, '    snapshots.append(target)', '    snapshots.append(target); cursorTrace("request adjustment=\(adjustment)", snapshots)')
    original = cursor_trace_replace(original, '          inputGeneration == generation else { return false }', '          inputGeneration == generation else { cursorTrace("post-reject expectedGeneration=\(generation)", snapshots); return false }')
    original = cursor_trace_replace(original, '    return before && after', '    cursorTrace("match offset=\(snapshot.offset) before=\(before) after=\(after)"); return before && after')
    original = cursor_trace_replace(original, (<<~'SWIFT').lines.map { |line| '  ' + line }.join.rstrip, <<~'SWIFT'.rstrip)
      private func context(_ proxy: UITextDocumentProxy) -> TypingContext? {
        guard let before = proxy.documentContextBeforeInput else { return nil }
        return TypingContext(document: proxy.documentIdentifier, before: before,
          after: proxy.documentContextAfterInput ?? "", hasSelection: proxy.selectedText?.isEmpty == false)
      }
    SWIFT
      private func cursorTrace(_ stage: String, _ snapshots: [CursorSnapshot]? = nil) {
        let values = (snapshots ?? cursorSnapshots).map {
          "d=\($0.context.document) o=\($0.offset) b=\($0.context.before.utf16.count):\($0.context.before.hashValue) a=\($0.context.after.utf16.count):\($0.context.after.hashValue)"
        }.joined(separator: ";")
        NSLog("ClarifyCursorTrace %@", "t=\(ProcessInfo.processInfo.systemUptime) gen=\(inputGeneration) stage=\(stage) snapshots=[\(values)]")
      }
      private func cursorTraceSecure(_ proxy: UITextDocumentProxy) -> Bool? {
        let value = proxy.isSecureTextEntry
        cursorTrace("secure=\(String(describing: value))")
        return value
      }
      private func context(_ proxy: UITextDocumentProxy) -> TypingContext? {
        let started = ProcessInfo.processInfo.systemUptime
        guard let before = proxy.documentContextBeforeInput else { cursorTrace("context before=nil start=\(started)"); return nil }
        let document = proxy.documentIdentifier
        let after = proxy.documentContextAfterInput
        let selection = proxy.selectedText
        cursorTrace("context start=\(started) order=before-document-after-selection doc=\(document) before=\(before.utf16.count):\(before.hashValue) after=\(String(describing: after?.utf16.count)):\(String(describing: after?.hashValue)) selection=\(String(describing: selection?.utf16.count))")
        return TypingContext(document: document, before: before, after: after ?? "", hasSelection: selection?.isEmpty == false)
      }
    SWIFT
    # Instrument existing secure reads only in the cursor methods, once per read.
    first = original.index('  func prepareCursor('); last = original.index('  private func matches(')
    original[first...last] = original[first...last].gsub('proxy.isSecureTextEntry', 'cursorTraceSecure(proxy)')
    source = File.join(fixture, name); File.write(source, original)
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
