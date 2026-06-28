// Resolve the shared @homepilot/* packages from ../../packages/*/src at build
// time (same alias strategy as the web frontend — no npm workspace linking, so
// nothing else in the repo changes). Metro transpiles the package TS via
// watchFolders (see metro.config.js).
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      [
        'module-resolver',
        {
          alias: {
            '@homepilot/types': '../../packages/types/src',
            '@homepilot/config': '../../packages/config/src',
            '@homepilot/api-client': '../../packages/api-client/src',
            '@homepilot/compute-client': '../../packages/compute-client/src',
            '@homepilot/auth': '../../packages/auth/src',
            '@homepilot/core': '../../packages/core/src',
            '@homepilot/ui': '../../packages/ui/src',
          },
        },
      ],
    ],
  };
};
