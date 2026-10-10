plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("maven-publish")
}

android {
    namespace = "com.aether.sdk"
    compileSdk = 34

    defaultConfig {
        minSdk = 21
        targetSdk = 34

        buildConfigField("String", "AETHER_SDK_VERSION", "\"${project.properties["sdkVersion"]}\"")

        consumerProguardFiles("consumer-rules.pro")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.lifecycle:lifecycle-process:2.7.0")
    implementation("androidx.lifecycle:lifecycle-common-java8:2.7.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    // Google Play Install Referrer — first-install attribution evidence
    implementation("com.android.installreferrer:installreferrer:2.2")
    // Optional interaction integrations (spec §12) — compileOnly so they are
    // only linked when the host app already depends on Compose / Navigation.
    compileOnly("androidx.compose.ui:ui:1.6.8")
    compileOnly("androidx.compose.foundation:foundation:1.6.8")
    compileOnly("androidx.navigation:navigation-runtime-ktx:2.7.7")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit:1.9.23")
    // Real org.json for JVM unit tests (the mockable android.jar stubs throw)
    testImplementation("org.json:json:20240303")
}

publishing {
    publications {
        create<MavenPublication>("release") {
            groupId = "com.aether"
            artifactId = "sdk-android"
            version = project.properties["sdkVersion"] as String

            afterEvaluate {
                from(components["release"])
            }

            pom {
                name.set("Aether Android SDK")
                description.set("Aether analytics, feature flags, and identity SDK for Android")
                url.set("https://github.com/DammnThatsCrazy/AETHER")
                licenses {
                    license {
                        name.set("UNLICENSED")
                    }
                }
                developers {
                    developer {
                        id.set("aether")
                        name.set("Aether")
                        email.set("sdk@aether.io")
                    }
                }
            }
        }
    }

    repositories {
        maven {
            name = "GitHubPackages"
            url = uri("https://maven.pkg.github.com/DammnThatsCrazy/AETHER")
            credentials {
                username = System.getenv("GITHUB_ACTOR") ?: ""
                password = System.getenv("GITHUB_TOKEN") ?: ""
            }
        }
    }
}
