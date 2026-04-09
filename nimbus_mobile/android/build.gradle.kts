import org.gradle.api.tasks.Delete
import org.gradle.api.file.Directory

allprojects {
    repositories {
        google()
        mavenCentral()
    }

    configurations.all {
        resolutionStrategy {
            force("androidx.core:core-ktx:1.13.1")
            force("androidx.core:core:1.13.1")
        }
    }
}

// Fix build directory location
val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()

rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}

// Ensure app builds first
subprojects {
    project.evaluationDependsOn(":app")
}

// Aggressive fix for lStar and SDK versions
subprojects {
    val fixProject = {
        if (project.hasProperty("android")) {
            val extension = project.extensions.findByName("android")
            if (extension is com.android.build.gradle.BaseExtension) {
                // Force SDK 36 on all subprojects EXCEPT the main app
                if (project.name != "app") {
                    extension.compileSdkVersion(36)
                    extension.defaultConfig.targetSdkVersion(36)
                    
                    if (extension.namespace == null) {
                        extension.namespace = "com.nimbus.bluetooth_fix.${project.name}"
                    }
                    
                    val manifestFile = file("src/main/AndroidManifest.xml")
                    if (manifestFile.exists()) {
                        val content = manifestFile.readText()
                        if (content.contains("package=")) {
                            val newContent = content.replace(Regex("""package="[^"]*""""), "")
                            manifestFile.writeText(newContent)
                        }
                    }
                }
            }
        }
    }

    if (project.state.executed) {
        fixProject()
    } else {
        project.afterEvaluate { fixProject() }
    }
}

// Clean task
tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}