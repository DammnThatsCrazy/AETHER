require 'json'
package = JSON.parse(File.read(File.join(__dir__, 'package.json')))

Pod::Spec.new do |s|
  s.name         = "aether-react-native"
  s.version      = package['version']
  s.summary      = package['description']
  s.homepage     = "https://github.com/aether/react-native-sdk"
  s.license      = package['license']
  s.author       = "Aether"
  s.platform     = :ios, "14.0"
  s.source       = { :git => "https://github.com/aether/react-native-sdk.git", :tag => s.version }
  s.source_files = "ios/**/*.{h,m,mm,swift}"

  s.dependency "React-Core"

  # Include the core iOS SDK
  s.dependency "AetherSDK", "~> 4.0"

  install_modules_dependencies(s)
end
