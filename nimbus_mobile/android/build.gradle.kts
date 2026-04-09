allprojects {
    repositories {
        google()
        mavenCentral()
    }
    configurations.all {
        resolutionStrategy {
            force("androidx.core:core:1.13.1")
            force("androidx.core:core-ktx:1.13.1")
        }
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

subprojects {
    val fixProject = {
        if (project.hasProperty("android")) {
            val extension = project.extensions.findByName("android")
            if (extension is com.android.build.gradle.BaseExtension) {
                if (extension.namespace == null) {
                    extension.namespace = "com.nimbus.bluetooth_fix.${project.name}"
                }
                
                // FIX FOR "package=" in AndroidManifest.xml
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
    if (project.state.executed) {
        fixProject()
    } else {
        project.afterEvaluate { fixProject() }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
