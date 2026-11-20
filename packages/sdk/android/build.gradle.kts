import com.vanniktech.maven.publish.AndroidSingleVariantLibrary
import com.vanniktech.maven.publish.SonatypeHost

plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("com.vanniktech.maven.publish")
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
    // Optional Play Integrity device-integrity evidence — compileOnly: only
    // linked when the host app opts in and depends on the library itself.
    compileOnly("com.google.android.play:integrity:1.3.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit:1.9.23")
    // Real org.json for JVM unit tests (the mockable android.jar stubs throw)
    testImplementation("org.json:json:20240303")
}

// Published to Maven Central as com.olympuslabsml:aether-android.
// The Kotlin package stays com.aether.sdk (Maven coordinates and code packages
// are independent; see docs/reference/SDK-ANDROID.md).
//
// CI supplies credentials and the signing key as Gradle properties via env:
//   ORG_GRADLE_PROJECT_mavenCentralUsername / ORG_GRADLE_PROJECT_mavenCentralPassword
//   ORG_GRADLE_PROJECT_signingInMemoryKey / ORG_GRADLE_PROJECT_signingInMemoryKeyPassword
// Signing is only configured when a key is present, so `publishToMavenLocal`
// (sdk-release-validation, local builds) works without secrets. Maven Central
// rejects unsigned uploads, so a real publish without the key fails loudly.
mavenPublishing {
    coordinates(
        groupId = "com.olympuslabsml",
        artifactId = "aether-android",
        version = project.properties["sdkVersion"] as String,
    )

    configure(
        AndroidSingleVariantLibrary(
            variant = "release",
            sourcesJar = true,
            publishJavadocJar = true,
        )
    )

    publishToMavenCentral(SonatypeHost.CENTRAL_PORTAL, automaticRelease = true)

    if (project.hasProperty("signingInMemoryKey")) {
        signAllPublications()
    }

    pom {
        name.set("Aether Android SDK")
        description.set("Aether event collection, identity, consent, and attribution SDK for Android")
        inceptionYear.set("2024")
        url.set("https://github.com/DammnThatsCrazy/AETHER")
        licenses {
            license {
                name.set("The Apache License, Version 2.0")
                url.set("https://www.apache.org/licenses/LICENSE-2.0.txt")
                distribution.set("repo")
            }
        }
        developers {
            developer {
                id.set("olympuslabs")
                name.set("Olympus Labs")
                url.set("https://olympuslabsml.com")
            }
        }
        scm {
            url.set("https://github.com/DammnThatsCrazy/AETHER")
            connection.set("scm:git:git://github.com/DammnThatsCrazy/AETHER.git")
            developerConnection.set("scm:git:ssh://git@github.com/DammnThatsCrazy/AETHER.git")
        }
    }
}
