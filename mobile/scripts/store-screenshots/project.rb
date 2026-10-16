require 'fileutils'
require 'xcodeproj'

fixture, source = ARGV
abort 'Expected isolated fixture and screenshot source paths' unless fixture && source
FileUtils.mkdir_p(fixture)
host_source = File.join(fixture, 'CaptureHost.swift')
File.write(host_source, <<~SWIFT)
  import SwiftUI
  @main struct CaptureHost: App {
    var body: some Scene { WindowGroup { Color.clear } }
  }
SWIFT
FileUtils.cp(source, File.join(fixture, 'StoreScreenshots.swift'))
project = Xcodeproj::Project.new(File.join(fixture, 'StoreScreenshots.xcodeproj'))
host = project.new_target(:application, 'CaptureHost', :ios, '16.4')
tests = project.new_target(:ui_test_bundle, 'StoreScreenshots', :ios, '16.4')
host.add_file_references([project.main_group.new_file(host_source)])
tests.add_file_references([project.main_group.new_file(File.join(fixture, 'StoreScreenshots.swift'))])
tests.add_dependency(host)
[host, tests].each do |target|
  target.build_configurations.each do |config|
    config.build_settings.merge!({
      'SWIFT_VERSION' => '5.0', 'CODE_SIGNING_ALLOWED' => 'NO',
      'CODE_SIGNING_REQUIRED' => 'NO', 'GENERATE_INFOPLIST_FILE' => 'YES',
      'TARGETED_DEVICE_FAMILY' => '1', 'IPHONEOS_DEPLOYMENT_TARGET' => '16.4',
      'PRODUCT_BUNDLE_IDENTIFIER' => "com.clarify.storecapture.#{target.name.downcase}"
    })
  end
end
host.build_configurations.each do |config|
  config.build_settings['INFOPLIST_KEY_UIApplicationSceneManifest_Generation'] = 'YES'
  config.build_settings['INFOPLIST_KEY_UILaunchScreen_Generation'] = 'YES'
end
tests.build_configurations.each do |config|
  config.build_settings['TEST_TARGET_NAME'] = 'CaptureHost'
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(host)
scheme.add_test_target(tests)
scheme.set_launch_target(host)
scheme.test_action.build_configuration = 'Release'
scheme.save_as(project.path, 'StoreScreenshots', true)
