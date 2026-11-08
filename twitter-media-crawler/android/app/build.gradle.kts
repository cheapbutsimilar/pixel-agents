import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// 앱에 넣는 다운로드 엔진 버전 (pip 설치와 앱의 '받아 둔 엔진이 더 새로운가' 비교에 함께 쓴다)
val galleryDlVersion = "1.32.19"

// PC/Termux 버전과 같은 핵심 파일(../../x_media_downloader.py)을 빌드할 때 복사해 넣는다.
// (심볼릭 링크는 Windows에서 내려받으면 깨진다)
val sharedPythonDir = layout.buildDirectory.dir("generated/sharedPython")
val copySharedPython by tasks.registering(Copy::class) {
    from(rootProject.file("../x_media_downloader.py"))
    into(sharedPythonDir)
}

// 릴리스 서명: 저장소의 이 앱 전용 키(signing/)로 서명한다. 키가 바뀌면 휴대폰에 덮어 설치(업데이트)가 안 되고,
// 지우고 다시 설치하면 로그인과 받은 기록이 사라져 전부 다시 받게 되므로 키는 항상 같아야 한다.
val keystoreProps = Properties().apply {
    val file = rootProject.file("signing/signing.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "io.github.xmedia.downloader"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.xmedia.downloader"
        minSdk = 29 // MediaStore RELATIVE_PATH / IS_PENDING
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        buildConfigField("String", "GALLERY_DL_VERSION", "\"$galleryDlVersion\"")
        ndk {
            // 갤럭시 등 요즘 폰은 모두 arm64. x86_64는 에뮬레이터용으로만 필요해서 뺀다(용량 절약).
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // 서명 키가 없으면 디버그 키로 몰래 대신 서명하지 않고 서명 안 된 APK(설치 불가)를 만든다
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            // PC/Termux 버전과 같은 엔진. 앱 안에서 '엔진 업데이트'로 최신 버전을 받을 수 있다.
            install("gallery-dl==$galleryDlVersion")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(copySharedPython) // 작업을 넘겨야 Gradle이 '복사 먼저'를 안다
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    testImplementation("junit:junit:4.13.2")
}
