require 'xcodeproj'
require 'fileutils'

root, fixture, endpoint = ARGV
raise 'Expected an isolated simulator fixture' unless File.basename(fixture).start_with?('.app-ui-') && File.dirname(fixture) == root
project_path = File.join(fixture, 'Clarify.xcodeproj')
project = Xcodeproj::Project.open(project_path)
app = project.targets.find { |target| target.name == 'Clarify' }
raise 'Containing app target is missing' unless app
if ENV['CLARIFY_APP_UI_INPUT_TRACE'] == 'true'
  trace = File.join(fixture, 'AppInputTrace.mm')
  FileUtils.cp(File.join(root, 'native/tests/AppInputTrace.mm'), trace)
  app.source_build_phase.add_file_reference(project.main_group.new_file(trace))
end
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
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app)
scheme.add_test_target(tests)
scheme.set_launch_target(app)
scheme.test_action.build_configuration = 'Release'
scheme.save_as(project_path, 'ClarifyAppFlow', true)
