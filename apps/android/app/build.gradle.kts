plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.roborazzi)
}

android {
    namespace = "com.handover.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.handover.app"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        // Ray-Ban Meta glasses in Developer Mode need no credentials ("0"); release builds need the
        // Wearables Developer Center app id and client token here.
        manifestPlaceholders["mwdat_application_id"] = "0"
        manifestPlaceholders["mwdat_client_token"] = "0"
    }

    buildTypes {
        // Phones that run HandOver are 64-bit ARM; packing only arm64-v8a native code (CameraX, media3, the
        // glasses toolkit) keeps the APK small. An x86_64 emulator needs this line removed locally.
        debug {
            ndk { abiFilters += "arm64-v8a" }
        }
        release {
            ndk { abiFilters += "arm64-v8a" }
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }

    testOptions {
        unitTests {
            // The core package is plain Kotlin; this only keeps a stray android.* call from crashing a JVM test.
            isReturnDefaultValues = true
            // Screenshot tests draw Compose on the JVM with Robolectric's native graphics (as vibeflux does).
            isIncludeAndroidResources = true
            all {
                it.systemProperty("robolectric.graphicsMode", "NATIVE")
                it.systemProperty("robolectric.pixelCopyRenderMode", "hardware")
                it.maxHeapSize = "2g"
            }
        }
    }

    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/versions/9/OSGI-INF/MANIFEST.MF")
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
    }
}

// Screenshots: ./gradlew :app:testDebugUnitTest --tests '*Screenshot*' -Proborazzi.test.record=true
roborazzi {
    outputDir.set(file("../screenshots"))
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    // Learn uses media3 for the clip player and these CameraX pieces for its own preview too.
    // The phone as the hub's camera, and the QR scanner (ZXing on the camera's luminance plane, no Play Services).
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    // Teach: recording a take (VideoCapture with audio).
    implementation(libs.camera.video)
    implementation(libs.zxing.core)
    // The learner's Ray-Ban Meta glasses as the hub camera, through this phone.
    implementation(libs.mwdat.core)
    implementation(libs.mwdat.camera)
    // Learn: the expert clip player (looping, side-loaded WebVTT captions, preloading the next clip).
    implementation(libs.media3.exoplayer)
    debugImplementation(libs.compose.ui.tooling)
    debugImplementation(libs.compose.ui.test.manifest)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.androidx.test.junit)
    testImplementation(libs.robolectric)
    testImplementation(platform(libs.compose.bom))
    testImplementation(libs.compose.ui.test.junit4)
    testImplementation(libs.roborazzi)
    testImplementation(libs.roborazzi.compose)
    testImplementation(libs.roborazzi.junit.rule)
}
