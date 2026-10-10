# Apply signing to CNG output only; generated native projects stay out of Git.
require 'json'
require 'xcodeproj'

profiles = JSON.parse(File.read(File.join(ENV.fetch('RUNNER_TEMP'), 'clarify-signing/profiles.json')))
project = Xcodeproj::Project.open('ios/Clarify.xcodeproj')
targets = {
  'Clarify' => 'com.jvictormaynard.clarify',
  'ClarifyKeyboard' => 'com.jvictormaynard.clarify.keyboard',
  'ClarifyActivity' => 'com.jvictormaynard.clarify.activity'
}
raise 'Unexpected native targets' unless project.targets.map(&:name).sort == targets.keys.sort
project.targets.each do |target|
  bundle = targets.fetch(target.name)
  target.build_configurations.each do |configuration|
    settings = configuration.build_settings
    raise 'Unexpected target bundle identifier' unless settings.fetch('PRODUCT_BUNDLE_IDENTIFIER') == bundle
    settings['DEVELOPMENT_TEAM'] = '8K353P3496'
    settings['CODE_SIGN_STYLE'] = 'Manual'
    settings['CODE_SIGN_IDENTITY'] = 'Apple Distribution'
    settings['PROVISIONING_PROFILE_SPECIFIER'] = profiles.fetch(bundle)
  end
end
project.save
puts 'Applied manual distribution signing to the app and both extensions.'
