Pod::Spec.new do |s|
  s.name = 'ClarifyCore'
  s.version = '0.1.0'
  s.summary = 'Clarify iOS microphone session and Groq processing'
  s.description = s.summary
  s.license = { :type => 'MIT' }
  s.author = 'Clarify contributors'
  s.homepage = 'https://github.com/jvictormaynard/clarify'
  s.platforms = { :ios => '16.4' }
  s.source = { :git => s.homepage }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.source_files = '*.{swift,h,m}'
  s.libraries = 'sqlite3'
  s.swift_version = '5.0'
end
