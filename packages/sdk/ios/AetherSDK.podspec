Pod::Spec.new do |s|
  s.name         = "AetherSDK"
  s.version         = "0.1.0-alpha.0"
  s.summary      = "Aether native iOS analytics, feature flags, and identity SDK"
  s.description  = <<-DESC
    AetherSDK provides event batching, session management, device fingerprinting,
    auto screen tracking, feature flags, wallet events, and consent management
    for iOS applications.
  DESC

  s.homepage     = "https://github.com/DammnThatsCrazy/AETHER"
  s.license      = { :type => "Apache-2.0", :file => "LICENSE" }
  s.author       = { "Olympus Labs" => "https://olympuslabsml.com" }

  s.ios.deployment_target = "14.0"
  # AdServices (Apple Ads attribution token) ships with iOS 14.3; weak-link it
  # so 14.0-14.2 devices still launch. Calls are guarded by #available.
  s.ios.weak_frameworks = "AdServices"
  s.swift_version         = "5.9"

  # Released from the public mirror repo, which the publish-sdk workflow fills
  # with the contents of packages/sdk/ios and tags with the bare version (the
  # tag format Swift Package Manager requires). Paths are relative to the
  # mirror root, which is also this file's directory in the monorepo.
  s.source       = {
    :git => "https://github.com/DammnThatsCrazy/aether-ios.git",
    :tag => s.version.to_s
  }

  s.source_files = "Sources/AetherSDK/**/*.swift"
  # Apple requires third-party SDKs to ship their privacy manifest.
  s.resource_bundles = { "AetherSDK_Privacy" => ["Sources/AetherSDK/PrivacyInfo.xcprivacy"] }
end
