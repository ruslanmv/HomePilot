/**
 * Expo config plugin: add a real Android *release* signing config that reads
 * its keystore from Gradle properties (provided by CI secrets), with a safe
 * fallback to debug signing when no keystore is supplied.
 *
 * Why a plugin and not a one-off `sed` in the workflow: `expo prebuild`
 * regenerates `android/` from scratch every run, so the signing config must be
 * (re)applied at prebuild time. Doing it through the config-plugin API keeps it
 * idempotent and resilient to template changes instead of brittle text patching.
 *
 * CI passes the keystore via env → Gradle properties (any of):
 *   ORG_GRADLE_PROJECT_HP_STORE_FILE      (absolute path to the .keystore)
 *   ORG_GRADLE_PROJECT_HP_STORE_PASSWORD
 *   ORG_GRADLE_PROJECT_HP_KEY_ALIAS
 *   ORG_GRADLE_PROJECT_HP_KEY_PASSWORD
 *
 * When HP_STORE_FILE is absent (forks, local dev, no secrets), the release
 * build falls back to the debug keystore so the workflow still produces an
 * installable (debug-signed) APK — never a broken unsigned one.
 */

const { withAppBuildGradle } = require("@expo/config-plugins");

const MARKER = "// >>> HomePilot release signing (managed by withAndroidReleaseSigning)";

const RELEASE_SIGNING_BLOCK = `        release {
            ${MARKER}
            if (project.hasProperty('HP_STORE_FILE')) {
                storeFile file(project.property('HP_STORE_FILE'))
                storePassword project.property('HP_STORE_PASSWORD')
                keyAlias project.property('HP_KEY_ALIAS')
                keyPassword project.property('HP_KEY_PASSWORD')
            }
        }
`;

function applyReleaseSigning(contents) {
  if (contents.includes(MARKER)) return contents; // idempotent

  // 1) Add a `release {}` signing config right after `signingConfigs {`.
  contents = contents.replace(
    /signingConfigs\s*\{\s*\n/,
    (match) => match + RELEASE_SIGNING_BLOCK
  );

  // 2) Point the *release* build type at it when a keystore is present,
  //    else keep debug. The release buildType's `signingConfig` line is the
  //    last occurrence (debug buildType precedes release in the template).
  const needle = "signingConfig signingConfigs.debug";
  const replacement =
    "signingConfig project.hasProperty('HP_STORE_FILE') ? signingConfigs.release : signingConfigs.debug";
  const last = contents.lastIndexOf(needle);
  if (last !== -1) {
    contents = contents.slice(0, last) + replacement + contents.slice(last + needle.length);
  }
  return contents;
}

module.exports = function withAndroidReleaseSigning(config) {
  return withAppBuildGradle(config, (cfg) => {
    if (cfg.modResults.language === "groovy") {
      cfg.modResults.contents = applyReleaseSigning(cfg.modResults.contents);
    }
    return cfg;
  });
};
