require 'json'
package = JSON.parse(File.read(File.join(__dir__, 'package.json')))

Pod::Spec.new do |s|
  s.name         = "aether-react-native"
  s.version      = package['version']
  s.summary      = package['description']
  s.homepage     = "https://github.com/DammnThatsCrazy/AETHER"
  s.license      = { :type => package['license'] }
  s.author       = { "Olympus Labs" => "https://olympuslabsml.com" }

  s.ios.deployment_target = "14.0"
  # AdServices (Apple Ads attribution token) ships with iOS 14.3; weak-link it
  # so 14.0-14.2 devices still launch. Calls are guarded by #available.
  s.ios.weak_frameworks = "AdServices"
  s.swift_version         = "5.9"

  # This podspec is consumed by React Native autolinking from
  # node_modules/@olympuslabs/aether-react-native (a :path pod), so paths are
  # relative to this file and `source` is informational. It is not pushed to
  # CocoaPods trunk: it depends on React-Core and only builds inside an RN app.
  s.source       = {
    :git => "https://github.com/DammnThatsCrazy/AETHER.git",
    :tag => "sdk/v#{s.version}"
  }
  s.source_files = "ios/**/*.{h,m,mm,swift}"

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
