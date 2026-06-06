require 'json'
package = JSON.parse(File.read(File.join(__dir__, 'package.json')))

Pod::Spec.new do |s|
  s.name         = "aether-react-native"
  s.version      = package['version']
  s.summary      = package['description']
  s.homepage     = "https://github.com/DammnThatsCrazy/AETHER"
  s.license      = { :type => package['license'] }
  s.author       = { "Aether" => "sdk@aether.io" }

  s.ios.deployment_target = "14.0"
  s.swift_version         = "5.9"

  s.source       = {
    :git => "https://github.com/DammnThatsCrazy/AETHER.git",
    :tag => "sdk/v#{s.version}"
  }
  s.source_files = "packages/react-native/ios/**/*.{h,m,mm,swift}"

  s.dependency "React-Core"
  s.dependency "AetherSDK", "~> #{s.version.to_s.split('.').first}.0"

  install_modules_dependencies(s)
end
