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
  s.source_files = "packages/sdk/react-native/ios/**/*.{h,m,mm,swift}"

  s.dependency "React-Core"
  # Pre-1.0 minors may break, so 0.x pins to the current minor; from 1.0 any compatible minor is allowed.
  major, minor = s.version.to_s.split('.').first(2).map(&:to_i)
  if major.zero?
    s.dependency "AetherSDK", ">= #{s.version}", "< 0.#{minor + 1}.0"
  else
    s.dependency "AetherSDK", "~> #{major}.0"
  end

  # install_modules_dependencies is injected by react-native-builder-bob / RN Podfile helpers.
  # Guard so `pod spec lint --quick` (no RN context) does not fail.
  install_modules_dependencies(s) if respond_to?(:install_modules_dependencies, true)
end
