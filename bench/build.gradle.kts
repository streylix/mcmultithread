plugins {
    java
    id("me.champeau.jmh") version "0.7.3"
}

repositories { mavenCentral() }

java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }

jmh {
    jmhVersion = "1.37"
    fork = 1
    warmupIterations = 3
    iterations = 5
    resultFormat = "JSON"
}
