Pod::Spec.new do |s|
  s.name         = "AetherSDK"
  s.version      = "8.8.0"
  s.summary      = "Aether native iOS analytics, feature flags, and identity SDK"
  s.description  = <<-DESC
    AetherSDK provides event batching, session management, device fingerprinting,
    auto screen tracking, feature flags, wallet events, and consent management
    for iOS applications.
  DESC

  s.homepage     = "https://github.com/DammnThatsCrazy/AETHER"
  s.license      = { :type => "UNLICENSED" }
  s.author       = { "Aether" => "sdk@aether.io" }

  s.ios.deployment_target = "14.0"
  s.swift_version         = "5.9"

  # Tagged as sdk/v{version} in the monorepo
  s.source       = {
    :git => "https://github.com/DammnThatsCrazy/AETHER.git",
    :tag => "sdk/v#{s.version}"
  }

  s.source_files = "packages/ios/Sources/AetherSDK/**/*.swift"
end
