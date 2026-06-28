// Expo + monorepo Metro config: let Metro watch and transpile the shared
// @homepilot/* package sources that live outside this app folder.
const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, '../..');

const config = getDefaultConfig(projectRoot);
config.watchFolders = [path.resolve(monorepoRoot, 'packages')];
config.resolver.nodeModulesPaths = [path.resolve(projectRoot, 'node_modules')];

module.exports = config;
