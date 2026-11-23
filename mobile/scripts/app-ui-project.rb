require 'xcodeproj'
require 'fileutils'

root, fixture, endpoint = ARGV
raise 'Expected an isolated simulator fixture' unless File.basename(fixture).start_with?('.app-ui-') && File.dirname(fixture) == root
raise 'Pods project must be a private copy' if File.symlink?(File.join(fixture, 'Pods')) || File.symlink?(File.join(fixture, 'Pods/Pods.xcodeproj'))
# Replace only fixture-owned Pod file references. Never mutate the shared Pods project.
core = File.join(root, 'modules/clarify-core/ios')
fixture_core = File.join(fixture, 'ComputerFixture')
FileUtils.cp_r(core, fixture_core)
connection_file = File.join(fixture_core, 'ComputerConnection.swift')
connection = File.read(connection_file)
needle = 'static let shared = ComputerConnection()'
raise 'ComputerConnection injection point changed' unless connection.scan(needle).length == 1
connection.sub!(needle, <<~SWIFT.strip)
  static let shared = ComputerConnection(transport: { request, route in
    // The real connection validates the HTTPS identity and protocol. Only I/O is fake.
    guard route.url == "https://192.168.1.33:9443",
      route.certificateSHA256 == String(repeating: "a", count: 64),
      let original = request.url else { throw ComputerFailure.invalidResponse }
    var local = request
    local.url = URL(string: "#{endpoint}" + original.path)
    let (data, response) = try await URLSession.shared.data(for: local)
    guard let response = response as? HTTPURLResponse else { throw ComputerFailure.invalidResponse }
    return (data, HTTPURLResponse(url: original, statusCode: response.statusCode,
      httpVersion: nil, headerFields: nil)!)
  })
SWIFT
File.write(connection_file, connection)
scanner_file = File.join(fixture_core, 'ComputerScanner.swift')
scanner = File.read(scanner_file)
start = scanner.index('    let allowed = await withCheckedContinuation')
finish = scanner.index('  override func viewDidLoad()')
raise 'Scanner injection point changed' unless start && finish
scanner[start...finish] = <<~SWIFT
    let (data, response) = try await URLSession.shared.data(from: URL(string: "#{endpoint}/__fixture/invitation")!)
    guard (response as? HTTPURLResponse)?.statusCode == 200,
      let value = try JSONSerialization.jsonObject(with: data) as? [String: String],
      let invitation = value["invitation"] else { throw ComputerFailure.invalidQR }
    return invitation
  }
SWIFT
File.write(scanner_file, scanner)
pods_path = File.join(fixture, 'Pods/Pods.xcodeproj')
pods = Xcodeproj::Project.open(pods_path)
replaced = []
pods.files.each do |file|
  resolved = file.real_path.to_s
  next unless resolved.start_with?(core + '/')
  file.path = resolved.sub(core, fixture_core)
  file.source_tree = '<absolute>'
  replaced << File.basename(resolved)
end
raise 'ClarifyCore fixture sources were not found' unless ['ComputerConnection.swift', 'ComputerScanner.swift'].all? { |name| replaced.include?(name) }
pods.save

project_path = File.join(fixture, 'Clarify.xcodeproj')
project = Xcodeproj::Project.open(project_path)
app = project.targets.find { |target| target.name == 'Clarify' }
raise 'Containing app target is missing' unless app
tests = project.new_target(:ui_test_bundle, 'ClarifyAppFlowTests', :ios, '16.4')
tests.add_dependency(app)
tests.build_configurations.each do |configuration|
  configuration.build_settings.merge!({
    'PRODUCT_BUNDLE_IDENTIFIER' => 'com.jvictormaynard.clarify.appflowtests',
    'PRODUCT_NAME' => '$(TARGET_NAME)',
    'PRODUCT_MODULE_NAME' => 'ClarifyAppFlowTests',
    'GENERATE_INFOPLIST_FILE' => 'YES', 'SWIFT_VERSION' => '5.0',
    'TEST_TARGET_NAME' => 'Clarify', 'TARGETED_DEVICE_FAMILY' => '1',
    'CODE_SIGNING_ALLOWED' => 'YES', 'CODE_SIGN_IDENTITY' => '-',
    'CODE_SIGN_INJECT_BASE_ENTITLEMENTS' => 'YES', 'ONLY_ACTIVE_ARCH' => 'YES'
  })
end
file = File.join(fixture, 'ClarifyAppFlowTests.swift')
FileUtils.cp(File.join(root, 'native/tests/AppFlowUITests.swift'), file)
tests.source_build_phase.add_file_reference(project.main_group.new_file(file))
native = project.new_target(:unit_test_bundle, 'ClarifyTextInputTests', :ios, '16.4')
native.add_dependency(app)
native.build_configurations.each do |configuration|
  app_configuration = app.build_configurations.find { |item| item.name == configuration.name }
  raise 'App CocoaPods configuration is missing' unless app_configuration&.base_configuration_reference
  configuration.base_configuration_reference = app_configuration.base_configuration_reference
  configuration.build_settings.merge!({
    'PRODUCT_BUNDLE_IDENTIFIER' => 'com.jvictormaynard.clarify.textinputtests',
    'PRODUCT_NAME' => '$(TARGET_NAME)', 'GENERATE_INFOPLIST_FILE' => 'YES',
    'SWIFT_VERSION' => '5.0',
    'CLANG_CXX_LANGUAGE_STANDARD' => 'c++20', 'CLANG_ENABLE_OBJC_ARC' => 'YES', 'CLANG_ENABLE_MODULES' => 'YES',
    'CODE_SIGNING_ALLOWED' => 'YES', 'CODE_SIGN_IDENTITY' => '-',
    'CODE_SIGN_INJECT_BASE_ENTITLEMENTS' => 'YES', 'ONLY_ACTIVE_ARCH' => 'YES',
    'OTHER_LDFLAGS' => ['$(inherited)', '-framework', 'XCTest'],
    'FRAMEWORK_SEARCH_PATHS' => ['$(inherited)', '$(PLATFORM_DIR)/Developer/Library/Frameworks', '$(SDKROOT)/Developer/Library/Frameworks'],
    'HEADER_SEARCH_PATHS' => ['$(inherited)', '$(SRCROOT)/../node_modules/react-native/ReactCommon',
      '$(SRCROOT)/../node_modules/react-native/ReactCommon/react/renderer/textlayoutmanager/platform/ios',
      '$(SRCROOT)/../node_modules/react-native/ReactCommon/react/renderer/graphics/platform/ios'],
    'LD_RUNPATH_SEARCH_PATHS' => ['$(inherited)', '@executable_path/Frameworks', '@loader_path/Frameworks'],
    'ALWAYS_EMBED_SWIFT_STANDARD_LIBRARIES' => 'YES'
  })
end
app.shell_script_build_phases.select { |phase| phase.name == '[CP] Embed Pods Frameworks' }.each do |phase|
  embed = native.new_shell_script_build_phase(phase.name)
  embed.shell_path = phase.shell_path; embed.shell_script = phase.shell_script
  embed.input_paths = phase.input_paths; embed.output_paths = phase.output_paths
  embed.input_file_list_paths = phase.input_file_list_paths; embed.output_file_list_paths = phase.output_file_list_paths
end
native_file = File.join(fixture, 'TextInputStateTests.mm')
FileUtils.cp(File.join(root, 'native/tests/TextInputStateTests.mm'), native_file)
native.source_build_phase.add_file_reference(project.main_group.new_file(native_file))
swift_file = File.join(fixture, 'TextInputTestRuntime.swift')
File.write(swift_file, <<~SWIFT)
  // This Objective-C++ test bundle links Swift Pods. A Swift source file makes
  // Xcode add the Swift compiler's runtime paths and compatibility libraries.
  import Foundation
SWIFT
native.source_build_phase.add_file_reference(project.main_group.new_file(swift_file))
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app)
scheme.add_test_target(tests)
scheme.add_test_target(native)
scheme.set_launch_target(app)
scheme.test_action.build_configuration = 'Release'
scheme.save_as(project_path, 'ClarifyAppFlow', true)
