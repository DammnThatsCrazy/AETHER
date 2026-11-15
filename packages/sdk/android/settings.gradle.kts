pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
    plugins {
        id("com.android.library") version "8.2.2"
        id("org.jetbrains.kotlin.android") version "1.9.22"
        // Maven Central (Sonatype Central Portal) publishing, signing, sources/javadoc jars.
        // 0.30.x is the last line supporting AGP 8.2 / Kotlin 1.9 / Gradle 8.5.
        id("com.vanniktech.maven.publish") version "0.30.0"
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_SETTINGS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "aether-android-sdk"
